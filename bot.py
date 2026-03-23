import os
import sqlite3
import threading
from datetime import datetime, timedelta
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

# Таблицы
cursor.execute("""
CREATE TABLE IF NOT EXISTS rides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    route TEXT,
    date TEXT,
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

# ---------------- Состояние пользователей ----------------
user_state = {}

# ---------------- Клавиатуры ----------------
def main_menu(user_id=None):
    kb = []
    kb.append([InlineKeyboardButton("➕ Предложить поездку", callback_data="add")])
    kb.append([InlineKeyboardButton("🚗 Найти поездку", callback_data="find")])
    kb.append([InlineKeyboardButton("📋 Мои поездки", callback_data="my")])
    kb.append([InlineKeyboardButton("⭐ Оценить поездку", callback_data="rate")])
    kb.append([InlineKeyboardButton("🚨 Пожаловаться", callback_data="report")])
    kb.append([InlineKeyboardButton("💰 Повысить приоритет", url=DONATE_URL)])
    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton("👑 Админка", callback_data="admin")])
    return InlineKeyboardMarkup(kb)

def route_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Челны → Казань", callback_data="route_chkaz")],
        [InlineKeyboardButton("Казань → Челны", callback_data="route_kazch")],
        [InlineKeyboardButton("Отмена", callback_data="menu")]
    ])

def seats_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(str(i), callback_data=f"seats_{i}") for i in range(1,5)],
        [InlineKeyboardButton("Отмена", callback_data="menu")]
    ])

def date_kb():
    kb = []
    today = datetime.now()
    for i in range(0, 3):  # следующие 3 дня
        day = today + timedelta(days=i)
        kb.append([InlineKeyboardButton(day.strftime("%d.%m"), callback_data=f"date_{day.strftime('%Y-%m-%d')}")])
    kb.append([InlineKeyboardButton("Отмена", callback_data="menu")])
    return InlineKeyboardMarkup(kb)

def time_kb():
    kb = []
    for h in range(8, 23, 2):
        kb.append([InlineKeyboardButton(f"{h}:00", callback_data=f"time_{h}:00")])
    kb.append([InlineKeyboardButton("Отмена", callback_data="menu")])
    return InlineKeyboardMarkup(kb)

# ---------------- Команды ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    await update.message.reply_text("🚗 Попутка Челны ↔ Казань", reply_markup=main_menu(chat_id))

# ---------------- CallbackHandler ----------------
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.from_user.id
    data = query.data
    state = user_state.get(chat_id, {})

    # Главное меню
    if data == "menu":
        user_state.pop(chat_id, None)
        await query.edit_message_text("🏠 Главное меню:", reply_markup=main_menu(chat_id))
        return

    # Добавление поездки
    if data == "add":
        user_state[chat_id] = {"step":"route"}
        await query.edit_message_text("Выберите маршрут:", reply_markup=route_kb())
        return

    # Выбор маршрута
    if data in ["route_chkaz", "route_kazch"]:
        state["route"] = "Челны → Казань" if data=="route_chkaz" else "Казань → Челны"
        state["step"] = "date"
        user_state[chat_id] = state
        await query.edit_message_text("Выберите дату:", reply_markup=date_kb())
        return

    # Выбор даты
    if data.startswith("date_"):
        state["date"] = data[5:]
        state["step"] = "time"
        user_state[chat_id] = state
        await query.edit_message_text("Выберите время отправления:", reply_markup=time_kb())
        return

    # Выбор времени
    if data.startswith("time_"):
        state["time"] = data[5:]
        state["step"] = "seats"
        user_state[chat_id] = state
        await query.edit_message_text("Выберите количество мест:", reply_markup=seats_kb())
        return

    # Выбор мест
    if data.startswith("seats_"):
        state["seats"] = int(data[6:])
        state["step"] = "price"
        user_state[chat_id] = state
        await query.edit_message_text("Введите цену (или 'договорная'):")
        return

# ---------------- Сообщения ----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    state = user_state.get(chat_id, {})
    step = state.get("step")
    text = update.message.text

    if not step:
        await update.message.reply_text("🏠 Главное меню", reply_markup=main_menu(chat_id))
        return

    # Ввод цены
    if step == "price":
        state["price"] = text
        state["step"] = "photo"
        user_state[chat_id] = state
        await update.message.reply_text("Можно отправить фото или пропустить командой /skip")
        return

    # Фото
    if step == "photo" and update.message.photo:
        file_id = update.message.photo[-1].file_id
        state["photo"] = file_id
        cursor.execute(
            "INSERT INTO rides (user_id, route, date, time, seats_total, price, photo) VALUES (?,?,?,?,?,?,?)",
            (chat_id, state["route"], state["date"], state["time"], state["seats"], state["price"], file_id)
        )
        conn.commit()
        await update.message.reply_text("✅ Объявление создано!", reply_markup=main_menu(chat_id))
        user_state.pop(chat_id)
        return

# Пропустить фото
async def skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    state = user_state.get(chat_id)
    if state and state.get("step")=="photo":
        cursor.execute(
            "INSERT INTO rides (user_id, route, date, time, seats_total, price) VALUES (?,?,?,?,?,?)",
            (chat_id, state["route"], state["date"], state["time"], state["seats"], state["price"])
        )
        conn.commit()
        await update.message.reply_text("✅ Объявление создано!", reply_markup=main_menu(chat_id))
        user_state.pop(chat_id)

# ---------------- Запуск ----------------
if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("skip", skip_photo))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("🚀 Бот запущен")
    app.run_polling()
