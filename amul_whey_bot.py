"""
Amul Whey Protein stock watcher -> Telegram alert.

Checks shop.amul.com for the chosen products at YOUR pincode and messages you on
Telegram when something goes from Sold Out -> In Stock.

Usage:
  python amul_whey_bot.py                # one check (used by GitHub Actions / Task Scheduler)
  python amul_whey_bot.py --loop         # keep running, check every CHECK_EVERY_MIN minutes
  python amul_whey_bot.py --test         # send current status to Telegram right now
  python amul_whey_bot.py --get-chat-id  # print your Telegram chat id (message the bot first)

Config comes from environment variables or a .env file next to this script:
  TELEGRAM_BOT_TOKEN   token from @BotFather            (required)
  TELEGRAM_CHAT_ID     your chat id                      (required)
  PINCODE              delivery pincode, e.g. 110001     (required)
  PRODUCTS             comma-separated product links (default: the 3 in DEFAULT_PRODUCTS)
  CHECK_EVERY_MIN      loop interval, default 15
  NOTIFY_SOLD_OUT      "true" to also alert when it sells out again
"""

import hashlib
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "state.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
BASE = "https://shop.amul.com/en/browse/protein"
API = "https://shop.amul.com/api/1.1/entity"
STORE_ID = "62fa94df8c13af2e242eba16"  # Amul's StoreHippo store id
FAIL_ALERT_AFTER = 4                     # warn on Telegram after N failed checks in a row

# Products to watch (override with PRODUCTS=link1,link2,... in .env / GitHub variable)
DEFAULT_PRODUCTS = ",".join([
    "https://shop.amul.com/en/product/amul-chocolate-whey-protein-34-g-or-pack-of-60-sachets",
    "https://shop.amul.com/en/product/amul-high-protein-plain-lassi-200-ml-or-pack-of-30",
    "https://shop.amul.com/en/product/amul-high-protein-buttermilk-200-ml-or-pack-of-30",
])


# ---------------------------------------------------------------- config
def load_env():
    env_file = HERE / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def cfg(name, default=None, required=False):
    val = os.environ.get(name) or default  # empty value (e.g. unset GitHub var) -> default
    if required and not val:
        sys.exit(f"Missing {name}. Put it in .env or set it as an environment variable.")
    return val


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------- telegram
def tg_send(text):
    token = cfg("TELEGRAM_BOT_TOKEN", required=True)
    chat = cfg("TELEGRAM_CHAT_ID", required=True)
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": True},
        timeout=20,
    )
    if not r.ok:
        log(f"Telegram error {r.status_code}: {r.text[:200]}")
    return r.ok


def get_chat_id():
    token = cfg("TELEGRAM_BOT_TOKEN", required=True)
    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20).json()
    chats = {(u.get("message") or {}).get("chat", {}).get("id") for u in r.get("result", [])}
    chats.discard(None)
    if not chats:
        print("No messages found. Open your bot in Telegram, press Start / send 'hi', then rerun.")
    for c in chats:
        print(f"TELEGRAM_CHAT_ID={c}")


# ---------------------------------------------------------------- amul
class Amul:
    """Minimal client for Amul's StoreHippo API (per-pincode stock)."""

    def __init__(self):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        html = self.s.get(BASE, timeout=25).text
        ts = re.search(r'serverTimestamp\s*=\s*"([^"]+)"', html)
        tok = re.search(r'token\s*=\s*"([^"]+)"', html)
        if not (ts and tok):
            raise RuntimeError("Could not read session token from Amul page (site may have changed).")
        self.ts, self.tok = ts.group(1), tok.group(1)

    def _h(self):
        r = random.randint(100, 999)
        sig = hashlib.sha256(f"{STORE_ID}:{self.ts}:{r}:{self.tok}".encode()).hexdigest()
        return {"tid": f"{self.ts}:{r}:{sig}", "frontend": "1", "base_url": BASE,
                "Referer": BASE, "Origin": "https://shop.amul.com",
                "Accept": "application/json, text/plain, */*"}

    def set_pincode(self, pincode):
        f = json.dumps([{"field": "pincode", "value": pincode, "operator": "regex"}])
        r = self.s.get(f"{API}/pincode", params={"filters": f, "limit": 10},
                       headers=self._h(), timeout=25)
        r.raise_for_status()
        data = r.json().get("data") or []
        match = next((d for d in data if d.get("pincode") == pincode), None)
        if not match:
            raise RuntimeError(f"Pincode {pincode} is not serviced by shop.amul.com.")
        sub = match["substore"]
        r = self.s.put(f"{API}/ms.settings/_/setPreferences", json={"store": sub},
                       headers=self._h(), timeout=25)
        r.raise_for_status()
        return sub

    def products(self, aliases):
        q = json.dumps({"alias": {"$in": aliases}})
        fields = json.dumps({"name": 1, "alias": 1, "available": 1,
                             "inventory_quantity": 1, "price": 1})
        r = self.s.get(f"{API}/ms.products", params={"q": q, "limit": 100, "fields": fields},
                       headers=self._h(), timeout=25)
        r.raise_for_status()
        data = r.json().get("data") or []
        if not data:
            # Empty list = session/pincode not applied. Treat as a failed check, NOT "sold out".
            raise RuntimeError("Amul returned no products (session not applied or bad product links).")
        return data


def watched_aliases():
    """PRODUCTS = comma-separated product links or slugs."""
    raw = cfg("PRODUCTS", DEFAULT_PRODUCTS)
    out = []
    for item in re.split(r"[,\s]+", raw):
        item = item.strip().rstrip("/")
        if item:
            out.append(item.split("/product/")[-1].split("?")[0])
    return out


def check():
    """Returns (substore, list of watched products)."""
    pincode = re.sub(r"\s", "", cfg("PINCODE", required=True))
    aliases = watched_aliases()
    a = Amul()
    sub = a.set_pincode(pincode)
    items = a.products(aliases)
    missing = set(aliases) - {p["alias"] for p in items}
    if missing:
        log(f"WARNING: not found on Amul (check the link): {', '.join(missing)}")
    return sub, items


def in_stock(p):
    return str(p.get("available")) in ("1", "True", "true")


def link(p):
    return f"https://shop.amul.com/en/product/{p['alias']}"


# ---------------------------------------------------------------- state
def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"products": {}, "fails": 0}


def save_state(st):
    STATE_FILE.write_text(json.dumps(st, indent=2, sort_keys=True))


# ---------------------------------------------------------------- run
def run_once():
    st = load_state()
    try:
        sub, items = check()
    except Exception as e:
        st["fails"] = st.get("fails", 0) + 1
        log(f"Check failed ({st['fails']} in a row): {e}")
        if st["fails"] == FAIL_ALERT_AFTER:
            tg_send(f"⚠️ Amul checker has failed {FAIL_ALERT_AFTER} times in a row.\n<code>{e}</code>")
        save_state(st)  # product states untouched on failure
        return

    st["fails"] = 0
    prev = st.setdefault("products", {})
    new_in, new_out = [], []
    for p in items:
        now = "in" if in_stock(p) else "out"
        was = prev.get(p["alias"])
        log(f"{now.upper():3}  {p['name']}  (was {was or 'unknown'})")
        if now == "in" and was != "in":
            new_in.append(p)
        elif now == "out" and was == "in":
            new_out.append(p)
        prev[p["alias"]] = now

    if new_in:
        lines = [f"🟢 <b>Amul IN STOCK</b> at pincode {cfg('PINCODE')} ({sub})\n"]
        for p in new_in:
            lines.append(f"• <a href=\"{link(p)}\">{p['name']}</a> — ₹{p.get('price')}")
        lines.append("\nGo buy before it's gone.")
        tg_send("\n".join(lines))
    if new_out and cfg("NOTIFY_SOLD_OUT", "false").lower() == "true":
        tg_send("🔴 Sold out again:\n" + "\n".join(f"• {p['name']}" for p in new_out))
    save_state(st)


def send_status():
    sub, items = check()
    lines = [f"📋 <b>Amul stock status</b> — pincode {cfg('PINCODE')} ({sub})\n"]
    for p in items:
        mark = "🟢 In stock" if in_stock(p) else "🔴 Sold out"
        lines.append(f"{mark} — <a href=\"{link(p)}\">{p['name']}</a>")
    ok = tg_send("\n".join(lines))
    print("\n".join(lines))
    print("\nTelegram message sent." if ok else "\nTelegram send FAILED - check token/chat id.")


def main():
    load_env()
    if os.environ.get("PINCODE"):
        os.environ["PINCODE"] = re.sub(r"\s", "", os.environ["PINCODE"])  # "400 072" -> "400072"
    args = sys.argv[1:]
    if "--get-chat-id" in args:
        return get_chat_id()
    if "--test" in args:
        return send_status()
    if "--loop" in args:
        mins = float(cfg("CHECK_EVERY_MIN", "15"))
        log(f"Running every {mins:g} min. Ctrl+C to stop.")
        while True:
            run_once()
            time.sleep(mins * 60)
    run_once()


if __name__ == "__main__":
    main()
