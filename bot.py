import os
import sqlite3
import threading
from flask import Flask

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)

# ---------------- НАСТРОЙКИ ----------------
ADMIN_ID = 869818784
DONATE_URL = "https://t.me/grigelav"
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# ---------------- WEB (для Render) ----------------
web_app = Flask(__name__)

@web_app.route("/")
def home():
    return "OK"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# ---------------- БАЗА ----------------
conn = sqlite3.connect("rides.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS rides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    route TEXT,
    time TEXT,
    seats_total INTEGER,
    seats_taken INTEGER DEFAULT 0,
    price TEXT,
    photo TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ride_id INTEGER,
    user_id INTEGER,
    rating INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ride_id INTEGER,
    reporter_id INTEGER,
    reason TEXT
)
""")

conn.commit()

# ---------------- STATE ----------------
user_state = {}

# ---------------- МЕНЮ ----------------
def main_menu(user_id):
    kb = [
        [InlineKeyboardButton("🚗 Найти поездку", callback_data="menu_find")],
        [InlineKeyboardButton("➕ Предложить поездку", callback_data="menu_add")],
        [InlineKeyboardButton("📋 Мои объявления", callback_data="menu_my")],
        [InlineKeyboardButton("👤 Профиль", callback_data="menu_profile")],
        [InlineKeyboardButton("💸 Поддержка", url=DONATE_URL)]
    ]
    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton("👑 Админка", callback_data="menu_admin")])
    return InlineKeyboardMarkup(kb)

def routes_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Челны → Казань", callback_data="route_1")],
        [InlineKeyboardButton("Казань → Челны", callback_data="route_2")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back")]
    ])

def seats_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(str(i), callback_data=f"seats_{i}") for i in range(1,5)],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back")]
    ])

# ---------------- START ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚗 Попутка Челны ↔ Казань", reply_markup=main_menu(update.message.chat.id))

# ---------------- ДОБАВИТЬ ПОЕЗДКУ ----------------
async def add_start(update, context):
    user_state[update.callback_query.from_user.id] = {}
    await update.callback_query.edit_message_text("Маршрут:", reply_markup=routes_kb())

async def set_route(update, context):
    uid = update.callback_query.from_user.id
    route = "Челны → Казань" if "1" in update.callback_query.data else "Казань → Челны"
    user_state[uid]["route"] = route
    await update.callback_query.edit_message_text("Введи время (например 18:30):")

async def set_time(update, context):
    uid = update.message.chat.id
    user_state[uid]["time"] = update.message.text
    await update.message.reply_text("Места:", reply_markup=seats_kb())

async def set_seats(update, context):
    uid = update.callback_query.from_user.id
    user_state[uid]["seats"] = int(update.callback_query.data.split("_")[1])
    await update.callback_query.edit_message_text("Цена:")

async def set_price(update, context):
    uid = update.message.chat.id
    user_state[uid]["price"] = update.message.text
    await update.message.reply_text("Фото или /skip")

async def set_photo(update, context):
    uid = update.message.chat.id
    photo = update.message.photo[-1].file_id if update.message.photo else None

    data = user_state.get(uid)
    cursor.execute(
        "INSERT INTO rides (user_id, route, time, seats_total, price, photo) VALUES (?,?,?,?,?,?)",
        (uid, data["route"], data["time"], data["seats"], data["price"], photo)
    )
    conn.commit()

    await update.message.reply_text("✅ Создано", reply_markup=main_menu(uid))
    user_state.pop(uid, None)

# ---------------- ПОИСК ----------------
async def find(update, context):
    uid = update.callback_query.from_user.id
    rides = cursor.execute("SELECT * FROM rides ORDER BY id DESC").fetchall()

    if not rides:
        await update.callback_query.edit_message_text("Нет поездок")
        return

    for r in rides:
        text = f"🚗 {r[2]}\n🕒 {r[3]}\n💺 {r[5]}/{r[4]}\n💰 {r[6]}"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💺 Забронировать", callback_data=f"book_{r[0]}")],
            [InlineKeyboardButton("🚨 Жалоба", callback_data=f"report_{r[0]}")]
        ])
        if r[7]:
            await context.bot.send_photo(uid, r[7], caption=text, reply_markup=kb)
        else:
            await context.bot.send_message(uid, text, reply_markup=kb)

# ---------------- БРОНЬ ----------------
async def book(update, context):
    ride_id = int(update.callback_query.data.split("_")[1])
    r = cursor.execute("SELECT seats_total,seats_taken,user_id FROM rides WHERE id=?", (ride_id,)).fetchone()

    if r[1] >= r[0]:
        await update.callback_query.answer("Нет мест")
        return

    cursor.execute("UPDATE rides SET seats_taken=seats_taken+1 WHERE id=?", (ride_id,))
    conn.commit()

    await update.callback_query.answer("Забронировано")
    await context.bot.send_message(r[2], "📩 У вас бронь!")

# ---------------- ПРОФИЛЬ ----------------
async def profile(update, context):
    uid = update.callback_query.from_user.id
    avg = cursor.execute("SELECT AVG(rating) FROM ratings WHERE user_id=?", (uid,)).fetchone()[0]
    avg = round(avg,1) if avg else 0
    await update.callback_query.edit_message_text(f"⭐ Рейтинг: {avg}", reply_markup=main_menu(uid))

# ---------------- ЖАЛОБА ----------------
async def report(update, context):
    ride_id = int(update.callback_query.data.split("_")[1])
    user_state[update.callback_query.from_user.id] = {"report": ride_id}
    await update.callback_query.edit_message_text("Напиши причину:")

async def save_report(update, context):
    uid = update.message.chat.id
    if uid in user_state and "report" in user_state[uid]:
        cursor.execute("INSERT INTO reports (ride_id, reporter_id, reason) VALUES (?,?,?)",
                       (user_state[uid]["report"], uid, update.message.text))
        conn.commit()
        await update.message.reply_text("Отправлено")
        user_state.pop(uid)

# ---------------- CALLBACK ----------------
async def callback(update, context):
    data = update.callback_query.data

    if data == "menu_add": await add_start(update, context)
    elif data.startswith("route_"): await set_route(update, context)
    elif data.startswith("seats_"): await set_seats(update, context)
    elif data == "menu_find": await find(update, context)
    elif data.startswith("book_"): await book(update, context)
    elif data == "menu_profile": await profile(update, context)
    elif data.startswith("report_"): await report(update, context)
    elif data == "back":
        await update.callback_query.edit_message_text("Меню", reply_markup=main_menu(update.callback_query.from_user.id))

# ---------------- TEXT ----------------
async def text(update, context):
    uid = update.message.chat.id

    if uid in user_state:
        if "time" not in user_state[uid]:
            await set_time(update, context)
        elif "price" not in user_state[uid]:
            await set_price(update, context)
        else:
            await set_photo(update, context)
    else:
        await update.message.reply_text("Используй кнопки", reply_markup=main_menu(uid))

# ---------------- ЗАПУСК ----------------
if __name__ == "__main__":
    threading.Thread(target=run_web).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text))
    app.add_handler(MessageHandler(filters.PHOTO, text))

    app.bot.delete_webhook(drop_pending_updates=True)

    print("BOT STARTED")
    app.run_polling()

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)
