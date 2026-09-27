# Amul Stock Bot (Telegram)

Checks shop.amul.com every 15 minutes at pincode **400072** and sends you a Telegram message when a watched product goes from Sold Out to In Stock. It sends one alert per restock, so you won't get the same message every 15 minutes. On the very first run it also tells you about anything that's already in stock.

Products watched:
- Amul Chocolate Whey Protein, 34 g × 60 sachets
- Amul High Protein Plain Lassi, 200 ml × 30
- Amul High Protein Buttermilk, 200 ml × 30

To change the list, set `PRODUCTS` to comma-separated product links (in `.env`, or as a GitHub Variable).

---

## Step 1: Create the bot in Telegram (2 min)

1. In Telegram, search **@BotFather** and open it. Check that it has the blue tick.
2. Send `/newbot`. Give it a name (e.g. `My Amul Alert`) and a username ending in `bot` (e.g. `my_amul_alert_bot`).
3. BotFather replies with a **token** like `123456789:AAH...`. Keep it private, because anyone with it controls your bot.
4. Open your new bot (BotFather gives you a link) and press **Start**. The bot can't message you until you've done this.

## Step 2: Get your chat ID

Easiest way: message **@userinfobot** in Telegram and it replies with your numeric ID.
(Or, after Step 3A, run `python amul_whey_bot.py --get-chat-id`.)

---

## Step 3: Choose where it runs

The bot is just a script that has to run somewhere every 15 minutes. Telegram only delivers the messages.

### Option A: GitHub (recommended: free, runs 24/7, PC can be off)

1. Create a free account at github.com.
2. Click **New repository** → name it `amul-whey-bot` → choose **Public** → Create.
   *Why public:* public repos get unlimited free run-minutes. A private repo would use about 2,900 min/month, which is more than the 2,000 free. Your token, chat ID and pincode are stored as encrypted **Secrets** and are never visible.
3. Click **uploading an existing file** and drag in everything from this folder **except `.env`**.
   The `.github` folder is hidden in Windows Explorer. If upload skips it, click **Add file → Create new file**, type `.github/workflows/check.yml` as the name, and paste the contents of that file.
4. Go to **Settings → Secrets and variables → Actions → New repository secret** and add three secrets:
   - `TELEGRAM_BOT_TOKEN`: the token from BotFather
   - `TELEGRAM_CHAT_ID`: your numeric ID
   - `PINCODE`: `400072`
5. Go to the **Actions** tab. If asked, click **Enable workflows**. Open **Amul whey check** → **Run workflow** to test it.
   The run should go green. From then on it runs automatically every 15 minutes.

Things to know:
- GitHub's scheduler can run a few minutes late when it's busy. Expect checks roughly every 15–20 minutes.
- The first run alerts you about anything already in stock. After that, you only get alerts when something restocks.

### Option B: Your Windows PC (works only while the PC is on)

1. Install Python from python.org and tick **"Add Python to PATH"** during install.
2. In this folder, copy `.env.example` → rename the copy to `.env` → fill in token, chat ID and pincode.
3. Test it: open a terminal in this folder and run
   `python -m pip install requests` then `python amul_whey_bot.py --test`
   You should get a status message in Telegram straight away.
4. Double-click **`run_on_pc.bat`**. Leave the window open and it checks every 15 minutes.

---

## Settings (optional)

| Setting | Default | What it does |
|---|---|---|
| `PRODUCTS` | the 3 above | Comma-separated Amul product links to watch |
| `NOTIFY_SOLD_OUT` | `false` | `true` = also message you when it sells out again |
| `CHECK_EVERY_MIN` | `15` | PC mode only |

On GitHub, set these under **Settings → Secrets and variables → Actions → Variables**.

## If something breaks

- After 4 failed checks in a row (about an hour), the bot messages you a warning.
- The bot uses Amul's website API, which isn't officially public. If Amul changes their site, the checker may stop working until the code is updated.
