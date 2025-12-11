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

# === CONFIG ===
import os

# ---- FIXED BOT TOKEN ----
BOT_TOKEN = os.environ.get("7648577586:AAG10G2khDJyFiQtwhVT7fyhjjo_AX8jFeI")  # IMPORTANT: Set BOT_TOKEN in environment

# ---- FIXED ADMIN ID ----
try:
    ADMIN_USER_ID = int(os.environ.get("ADMIN_USER_ID", "5654093580"))
except ValueError:
    ADMIN_USER_ID = 5654093580

PREMIUM_FILE = "premium_users.json"
USAGE_FILE = "usage_tracker.json"
QR_IMAGE_PATH = "qr.png"
UPI_ID = "xyzxyzxyz.@ibl"

# === LOGGING ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === TOKEN VALIDATION ===
import sys, re
from telegram import Bot as TgBot

def looks_like_token(t):
    return bool(t and re.match(r"^\d{6,20}:[A-Za-z0-9_-]{35,}$", t.strip()))

if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN environment variable not set. Set BOT_TOKEN and restart.")
    sys.exit(1)

if not looks_like_token(BOT_TOKEN):
    print("ERROR: BOT_TOKEN invalid. Check for extra spaces/quotes or get new token from BotFather.")
    print("TOKEN repr:", repr(BOT_TOKEN))
    sys.exit(1)

try:
    TgBot(BOT_TOKEN)
except Exception as e:
    print("ERROR: Telegram rejected your token:", e)
    sys.exit(1)

# === PREMIUM MANAGEMENT ===
def load_json(file):
    try:
        with open(file, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        logger.warning(f"Corrupt JSON in {file}, resetting.")
        return {}
    except Exception:
        logger.exception(f"Unexpected error reading {file}")
        return {}

def save_json(file, data):
    try:
        with open(file, "w") as f:
            json.dump(data, f)
    except Exception:
        logger.exception(f"Failed to write {file}")

def is_premium(user_id):
    users = load_json(PREMIUM_FILE)
    if str(user_id) in users:
        expiry = datetime.strptime(users[str(user_id)], "%Y-%m-%d")
        return datetime.now() <= expiry
    return False

def add_premium(user_id, days):
    users = load_json(PREMIUM_FILE)
    expiry = datetime.now() + timedelta(days=days)
    users[str(user_id)] = expiry.strftime("%Y-%m-%d")
    save_json(PREMIUM_FILE, users)

# === USAGE TRACKING ===
def can_use_free(user_id):
    usage = load_json(USAGE_FILE)
    last_used = usage.get(str(user_id))
    if not last_used:
        return True
    last_time = datetime.strptime(last_used, "%Y-%m-%d %H:%M:%S")
    return datetime.now() - last_time >= timedelta(hours=24)

def update_usage(user_id):
    usage = load_json(USAGE_FILE)
    usage[str(user_id)] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_json(USAGE_FILE, usage)

# === DISKWALA VIDEO EXTRACTOR ===
def get_direct_link(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, "html.parser")
        video_tag = soup.find("video")
        if video_tag:
            source = video_tag.find("source")
            if source and source.get("src"):
                return source["src"]
        return None
    except Exception:
        logger.exception("Error extracting video link")
        return None

# === HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [[InlineKeyboardButton("💎 Buy Premium", callback_data="buy_premium")]]
    await update.message.reply_text(
        "👋 Welcome! Send me a Diskwala link.\n\nFree = 1 video / 24 hrs.\nPremium = Unlimited!",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()

    if "diskwala" not in text:
        await update.message.reply_text("❌ Please send a valid Diskwala link.")
        return

    allowed = is_premium(user_id) or can_use_free(user_id)

    if not allowed:
        await update.message.reply_text(
            "⚠️ Only 1 free video every 24 hours.\nUpgrade to premium for unlimited!",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("💎 Buy Premium", callback_data="buy_premium")]]
            )
        )
        return

    await update.message.reply_text("🔄 Processing your link...")

    direct_link = get_direct_link(text)

    if direct_link:
        try:
            await update.message.reply_video(video=direct_link)
        except:
            await update.message.reply_text(f"✅ Direct link: {direct_link}")
        if not is_premium(user_id):
            update_usage(user_id)
    else:
        await update.message.reply_text("❌ Failed to extract video.")

async def add_premium_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_USER_ID:
        await update.message.reply_text("❌ Unauthorized.")
        return

    try:
        if len(context.args) < 2:
            raise ValueError("Missing arguments")
        target_id = int(context.args[0])
        days = int(context.args[1])
        add_premium(target_id, days)
        await update.message.reply_text(f"✅ Upgraded {target_id} for {days} days.")
    except ValueError:
        await update.message.reply_text("❌ Usage: /addpremium <user_id> <days>")
    except Exception:
        logger.exception("Premium command failed")
        await update.message.reply_text("❌ Error occurred.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "buy_premium":
        await query.message.reply_photo(
            photo=InputFile(QR_IMAGE_PATH),
            caption=(
                "💎 *Premium Plans:*\n\n"
                "• 7 Days = ₹15\n"
                "• 30 Days = ₹60\n"
                "• 3 Months = ₹150\n"
                "• Lifetime = Contact Admin\n\n"
                f"📲 UPI: `{UPI_ID}`\n"
                "Send screenshot to admin after payment."
            ),
            parse_mode="Markdown"
        )

# === MAIN ===
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addpremium", add_premium_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(CallbackQueryHandler(button_callback))
    print("Bot is running...")
    app.run_polling()
