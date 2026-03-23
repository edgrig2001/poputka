import os
import sqlite3
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler,
    MessageHandler, filters
)

# ---------------- Настройки ----------------
ADMIN_ID = 869818784
DONATE_URL = "https://t.me/grigelav"  # ссылка или QR на оплату
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # токен бота через Render Env

# ---------------- Flask ----------------
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "✅ Попутка Бот Работает"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

# ---------------- База данных ----------------
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

user_state = {}

# ---------------- Главное меню ----------------
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Предложить поездку", callback_data="add")],
        [InlineKeyboardButton("🚗 Найти поездку", callback_data="find")],
        [InlineKeyboardButton("📋 Мои объявления", callback_data="my")],
        [InlineKeyboardButton("⭐ Оценить поездку", callback_data="rate")],
        [InlineKeyboardButton("🚨 Пожаловаться", callback_data="report")],
        [InlineKeyboardButton("👑 Админка", callback_data="admin") if True else None]  # отображаем только админу
    ])

# ---------------- Команды ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    await update.message.reply_text("🚗 Попутка Челны ↔ Казань", reply_markup=main_keyboard())

# ---------------- CallbackHandler ----------------
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.from_user.id
    data = query.data

    # Главное меню
    if data == "menu":
        await query.edit_message_text("🏠 Главное меню:", reply_markup=main_keyboard())

    # Добавить поездку
    elif data == "add":
        user_state[chat_id] = {"step": "route"}
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Челны → Казань", callback_data="route_chkaz")],
            [InlineKeyboardButton("Казань → Челны", callback_data="route_kazch")],
            [InlineKeyboardButton("Отмена", callback_data="menu")]
        ])
        await query.edit_message_text("Выберите маршрут:", reply_markup=keyboard)

    elif data in ["route_chkaz", "route_kazch"]:
        route = "Челны → Казань" if data=="route_chkaz" else "Казань → Челны"
        user_state[chat_id]["route"] = route
        user_state[chat_id]["step"] = "time"
        await query.edit_message_text("Введите время отправления (например 18:00):")

    elif data == "skip_photo":
        state = user_state.get(chat_id)
        if state:
            # Сохраняем поездку без фото
            cursor.execute(
                "INSERT INTO rides (user_id, route, time, seats_total, price) VALUES (?,?,?,?,?)",
                (chat_id, state["route"], state["time"], state["seats"], state["price"])
            )
            conn.commit()
            await query.edit_message_text("✅ Объявление создано!", reply_markup=main_keyboard())
            user_state.pop(chat_id)

    # Найти поездку
    elif data == "find":
        rides = cursor.execute("SELECT * FROM rides ORDER BY id DESC LIMIT 10").fetchall()
        if not rides:
            await query.edit_message_text("Поездок пока нет", reply_markup=main_keyboard())
            return
        for r in rides:
            text = f"🚗 {r[2]}\n🕒 {r[3]}\n💺 {r[6]}/{r[4]}\n💰 {r[5]}"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"💺 Забронировать {r[0]}", callback_data=f"book_{r[0]}")]])
            if r[7]:
                await context.bot.send_photo(chat_id, r[7], caption=text, reply_markup=kb)
            else:
                await query.edit_message_text(text, reply_markup=kb)

    # Забронировать место
    elif data.startswith("book_"):
        ride_id = int(data.split("_")[1])
        ride = cursor.execute("SELECT seats_total, seats_taken, user_id FROM rides WHERE id=?", (ride_id,)).fetchone()
        if not ride:
            await query.edit_message_text("Ошибка бронирования")
            return
        seats_total, seats_taken, driver_id = ride
        if seats_taken >= seats_total:
            await query.edit_message_text("❌ Все места заняты")
            return
        cursor.execute("UPDATE rides SET seats_taken = seats_taken+1 WHERE id=?", (ride_id,))
        conn.commit()
        await query.edit_message_text("✅ Место забронировано!")
        await context.bot.send_message(driver_id, f"💬 @{query.from_user.username} забронировал(-а) у вас место в поездке {ride_id}")

# ---------------- Обработка сообщений ----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    state = user_state.get(chat_id, {})
    step = state.get("step")

    if not step:
        await update.message.reply_text("🏠 Главное меню", reply_markup=main_keyboard())
        return

    text = update.message.text

    if step == "time":
        state["time"] = text
        state["step"] = "seats"
        await update.message.reply_text("Сколько мест? (1-4)")

    elif step == "seats":
        try:
            seats = int(text)
            if seats <1 or seats>4:
                await update.message.reply_text("Введите число от 1 до 4")
                return
            state["seats"] = seats
            state["step"] = "price"
            await update.message.reply_text("Цена (или договорная):")
        except:
            await update.message.reply_text("Введите число")
            return

    elif step == "price":
        state["price"] = text
        state["step"] = "photo"
        await update.message.reply_text("Можно прикрепить фото (отправьте фото) или пропустить командой /skip")

    elif step == "photo" and update.message.photo:
        file_id = update.message.photo[-1].file_id
        state["photo"] = file_id
        cursor.execute(
            "INSERT INTO rides (user_id, route, time, seats_total, price, photo) VALUES (?,?,?,?,?,?)",
            (chat_id, state["route"], state["time"], state["seats"], state["price"], file_id)
        )
        conn.commit()
        await update.message.reply_text("✅ Объявление создано!", reply_markup=main_keyboard())
        user_state.pop(chat_id)

# ---------------- Запуск ----------------
if __name__ == "__main__":
    threading.Thread(target=run_web).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("🚀 Бот запущен")
    app.run_polling()
