#!/usr/bin/env python3
# bot.py
import os
import sys
import re
import json
import logging
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputFile,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler
)

# ===== CONFIG =====
# Read BOT_TOKEN from environment first, else from .env (python-dotenv)
BOT_TOKEN = os.environ.get("7648577586:AAG10G2khDJyFiQtwhVT7fyhjjo_AX8jFeI")
if not BOT_TOKEN:
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
        BOT_TOKEN = os.environ.get("7648577586:AAG10G2khDJyFiQtwhVT7fyhjjo_AX8jFeI")
    except Exception:
        pass

# Admin id (optional override via env)
try:
    ADMIN_USER_ID = int(os.environ.get("ADMIN_USER_ID", "5654093580"))
except ValueError:
    ADMIN_USER_ID = 5654093580

PREMIUM_FILE = "premium_users.json"
USAGE_FILE = "usage_tracker.json"
QR_IMAGE_PATH = "qr.png"
UPI_ID = "xyzxyzxyz.@ibl"

# ===== LOGGING =====
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ===== TOKEN VALIDATION =====
def _looks_like_token(t):
    return bool(t and re.match(r"^\d{6,20}:[A-Za-z0-9_-]{35,}$", t.strip()))

if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN not found. Put BOT_TOKEN=your_token in .env or set env var and restart.")
    sys.exit(1)

if not _looks_like_token(BOT_TOKEN):
    print("ERROR: BOT_TOKEN format invalid. Check token from @BotFather.")
    print("TOKEN repr:", repr(BOT_TOKEN)[:120])
    sys.exit(1)

# optional lightweight check (may do a small validation)
try:
    from telegram import Bot as TgBot
    TgBot(BOT_TOKEN)
except Exception as e:
    print("ERROR: Token validation failed:", e)
    sys.exit(1)

# ===== JSON helpers =====
def load_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        logger.warning("Corrupt JSON %s — resetting.", path)
        return {}
    except Exception:
        logger.exception("Error reading %s", path)
        return {}

def save_json(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f)
    except Exception:
        logger.exception("Error writing %s", path)

# ===== Premium / Usage =====
def is_premium(user_id):
    users = load_json(PREMIUM_FILE)
    if str(user_id) in users:
        try:
            expiry = datetime.strptime(users[str(user_id)], "%Y-%m-%d")
            return datetime.now() <= expiry
        except Exception:
            return False
    return False

def add_premium(user_id, days):
    users = load_json(PREMIUM_FILE)
    expiry = datetime.now() + timedelta(days=days)
    users[str(user_id)] = expiry.strftime("%Y-%m-%d")
    save_json(PREMIUM_FILE, users)

def can_use_free(user_id):
    usage = load_json(USAGE_FILE)
    last = usage.get(str(user_id))
    if not last:
        return True
    try:
        last_time = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return True
    return datetime.now() - last_time >= timedelta(hours=24)

def update_usage(user_id):
    usage = load_json(USAGE_FILE)
    usage[str(user_id)] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_json(USAGE_FILE, usage)

# ===== Diskwala extractor (basic) =====
def get_direct_link(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=20)
        if res.status_code != 200:
            logger.warning("Non-200 from %s: %s", url, res.status_code)
            return None
        soup = BeautifulSoup(res.text, "html.parser")
        video_tag = soup.find("video")
        if video_tag:
            src = None
            source = video_tag.find("source")
            if source and source.get("src"):
                src = source.get("src")
            # fallback: video tag src attribute
            if not src and video_tag.get("src"):
                src = video_tag.get("src")
            if src:
                return src
        # fallback heuristic: look for .mp4 links
        for tag in soup.find_all(["a", "source", "meta", "script"]):
            v = tag.get("href") or tag.get("src") or tag.get("content")
            if v and (v.endswith(".mp4") or ".mp4?" in v or "cdn" in v or "video" in v):
                return v
        return None
    except Exception:
        logger.exception("Failed to extract direct link")
        return None

# ===== Handlers =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [[InlineKeyboardButton("💎 Buy Premium", callback_data="buy_premium")]]
    await update.message.reply_text(
        "👋 Welcome! Send me a Diskwala link.\n\nFree = 1 video / 24 hrs.\nPremium = Unlimited!",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = (update.message.text or "").strip()
    if "diskwala" not in text.lower():
        await update.message.reply_text("❌ Please send a valid Diskwala link.")
        return

    if not (is_premium(user_id) or can_use_free(user_id)):
        await update.message.reply_text(
            "⚠️ Free users: 1 video every 24 hours. Upgrade to premium for unlimited access.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Buy Premium", callback_data="buy_premium")]])
        )
        return

    await update.message.reply_text("🔄 Processing your link...")
    direct = get_direct_link(text)
    if direct:
        try:
            await update.message.reply_video(video=direct)
        except Exception:
            await update.message.reply_text(f"✅ Direct link: {direct}")
        if not is_premium(user_id):
            update_usage(user_id)
    else:
        await update.message.reply_text("❌ Failed to extract video from that link.")

async def add_premium_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_USER_ID:
        await update.message.reply_text("❌ Unauthorized.")
        return
    try:
        if len(context.args) < 2:
            raise ValueError("missing args")
        target = int(context.args[0])
        days = int(context.args[1])
        add_premium(target, days)
        await update.message.reply_text(f"✅ User {target} upgraded for {days} days.")
    except ValueError:
        await update.message.reply_text("❌ Usage: /addpremium <user_id> <days>")
    except Exception:
        logger.exception("addpremium failed")
        await update.message.reply_text("❌ Error occurred.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "buy_premium":
        caption = (
            "💎 *Premium Plans:*\n\n"
            "• 7 Days = ₹15\n"
            "• 30 Days = ₹60\n"
            "• 3 Months = ₹150\n"
            "• Lifetime = Contact Admin\n\n"
            f"📲 UPI: `{UPI_ID}`\nSend screenshot to admin after payment."
        )
        try:
            await q.message.reply_photo(photo=InputFile(QR_IMAGE_PATH), caption=caption, parse_mode="Markdown")
        except Exception:
            await q.message.reply_text(caption, parse_mode="Markdown")

# ===== MAIN =====
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addpremium", add_premium_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(CallbackQueryHandler(button_callback))
    print("Bot is running...")
    app.run_polling()
