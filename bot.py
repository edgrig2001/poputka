import os
import sqlite3
import threading
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler
)
# ---------------- Настройки ----------------
ADMIN_ID = 869818784
DONATE_URL = "https://t.me/grigelav"  # ссылка или QR на оплату
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # токен бота через Render Env

# ---------------- SQLite ----------------
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

# ---------------- Состояния пользователей ----------------
user_state = {}  # user_id -> {"add_ride": {...}, "rating": {...}, "report": {...}}

# ---------------- Главное меню ----------------
def main_menu(user_id):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚗 Найти поездку", callback_data="menu_find")],
        [InlineKeyboardButton("➕ Предложить поездку", callback_data="menu_add")],
        [InlineKeyboardButton("📋 Мои объявления", callback_data="menu_my")],
        [InlineKeyboardButton("👤 Профиль", callback_data="menu_profile")],
        [InlineKeyboardButton("💸 Поддержка", url=DONATE_URL)]
    ])
    # Добавляем админку только для тебя
    if user_id == ADMIN_ID:
        kb.add([InlineKeyboardButton("👑 Админка", callback_data="menu_admin")])
    return kb

# ---------------- Старт ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    await update.message.reply_text("🚗 Попутка Челны ↔ Казань", reply_markup=main_menu(chat_id))

# ---------------- Вспомогательные клавиатуры ----------------
def routes_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Челны → Казань", callback_data="route_1")],
        [InlineKeyboardButton("Казань → Челны", callback_data="route_2")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_main")]
    ])

def seats_kb(max_seats):
    kb = []
    row = []
    for i in range(1, max_seats+1):
        row.append(InlineKeyboardButton(str(i), callback_data=f"seats_{i}"))
        if len(row) == 4:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(kb)

def yes_no_kb(prefix):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да", callback_data=f"{prefix}_yes"),
         InlineKeyboardButton("❌ Нет", callback_data=f"{prefix}_no")]
    ])
    # ---------------- SQLite ----------------
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

# ---------------- Состояния пользователей ----------------
user_state = {}  # user_id -> {"add_ride": {...}, "rating": {...}, "report": {...}}

# ---------------- Главное меню ----------------
def main_menu(user_id):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚗 Найти поездку", callback_data="menu_find")],
        [InlineKeyboardButton("➕ Предложить поездку", callback_data="menu_add")],
        [InlineKeyboardButton("📋 Мои объявления", callback_data="menu_my")],
        [InlineKeyboardButton("👤 Профиль", callback_data="menu_profile")],
        [InlineKeyboardButton("💸 Поддержка", url=DONATE_URL)]
    ])
    # Добавляем админку только для тебя
    if user_id == ADMIN_ID:
        kb.add([InlineKeyboardButton("👑 Админка", callback_data="menu_admin")])
    return kb

# ---------------- Старт ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    await update.message.reply_text("🚗 Попутка Челны ↔ Казань", reply_markup=main_menu(chat_id))

# ---------------- Вспомогательные клавиатуры ----------------
def routes_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Челны → Казань", callback_data="route_1")],
        [InlineKeyboardButton("Казань → Челны", callback_data="route_2")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_main")]
    ])

def seats_kb(max_seats):
    kb = []
    row = []
    for i in range(1, max_seats+1):
        row.append(InlineKeyboardButton(str(i), callback_data=f"seats_{i}"))
        if len(row) == 4:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(kb)

def yes_no_kb(prefix):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да", callback_data=f"{prefix}_yes"),
         InlineKeyboardButton("❌ Нет", callback_data=f"{prefix}_no")]
    ])
    # ---------------- ПРОФИЛЬ ----------------
async def profile_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.callback_query.from_user.id
    avg_rating = cursor.execute("SELECT AVG(rating) FROM ratings WHERE user_id=?", (chat_id,)).fetchone()[0]
    avg_rating = round(avg_rating,1) if avg_rating else 0
    text = f"👤 Профиль:\n⭐ Рейтинг: {avg_rating}\n"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")]
    ])
    await update.callback_query.edit_message_text(text, reply_markup=kb)

# ---------------- РЕЙТИНГ ----------------
async def rate_ride(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.callback_query.from_user.id
    ride_id = int(update.callback_query.data.split("_")[1])
    user_state[chat_id]["rating"] = {"ride_id": ride_id}
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(str(i), callback_data=f"rate_{ride_id}_{i}") for i in range(1,6)],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_main")]
    ])
    await update.callback_query.edit_message_text("⭐ Выберите рейтинг:", reply_markup=kb)

async def save_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.callback_query.from_user.id
    parts = update.callback_query.data.split("_")
    ride_id = int(parts[1])
    rating = int(parts[2])
    cursor.execute("INSERT INTO ratings (ride_id, user_id, rating) VALUES (?, ?, ?)", (ride_id, chat_id, rating))
    conn.commit()
    await update.callback_query.answer("⭐ Спасибо за оценку!")
    await update.callback_query.edit_message_text("⭐ Рейтинг сохранен", reply_markup=main_menu(chat_id))
    user_state[chat_id].pop("rating", None)

# ---------------- ЖАЛОБЫ ----------------
async def report_ride(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.callback_query.from_user.id
    ride_id = int(update.callback_query.data.split("_")[1])
    user_state[chat_id]["report"] = {"ride_id": ride_id}
    await update.callback_query.edit_message_text("Введите причину жалобы:")

async def save_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    reason = update.message.text
    ride_id = user_state[chat_id]["report"]["ride_id"]
    cursor.execute("INSERT INTO reports (ride_id, reporter_id, reason) VALUES (?, ?, ?)", (ride_id, chat_id, reason))
    conn.commit()
    await update.message.reply_text("🚨 Жалоба отправлена администратору")
    await context.bot.send_message(ADMIN_ID, f"🚨 Жалоба на поездку {ride_id} от @{update.message.from_user.username}: {reason}")
    user_state[chat_id].pop("report", None)
    await update.message.reply_text("🏠 Главное меню", reply_markup=main_menu(chat_id))

# ---------------- АДМИНКА ----------------
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.callback_query.from_user.id
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Все объявления", callback_data="admin_all")],
        [InlineKeyboardButton("🚫 Бан/Разбан", callback_data="admin_ban")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")]
    ])
    await update.callback_query.edit_message_text("👑 Админ-панель", reply_markup=kb)

# ---------------- ПОВЫШЕНИЕ ПРИОРИТЕТА ----------------
async def promote_ride(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.callback_query.from_user.id
    ride_id = int(update.callback_query.data.split("_")[1])
    # В реальном проекте сюда можно вставить оплату через ссылку/QR
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Оплатить повышение", url=DONATE_URL)],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_main")]
    ])
    await update.callback_query.edit_message_text(f"Повышение приоритета поездки {ride_id}", reply_markup=kb)

# ---------------- BACK / Главное меню ----------------
async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.callback_query.from_user.id
    await update.callback_query.edit_message_text("🏠 Главное меню", reply_markup=main_menu(chat_id))
    # ---------------- ОБРАБОТЧИКИ CALLBACK ----------------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    chat_id = update.callback_query.from_user.id

    # Главное меню
    if data == "back_main":
        await back_main(update, context)
        return

    # Меню
    if data == "menu_add":
        await add_ride_start(update, context)
    elif data.startswith("route_"):
        await add_ride_route(update, context)
    elif data.startswith("seats_"):
        await add_ride_seats(update, context)
    elif data.startswith("book_"):
        await book_seat(update, context)
    elif data.startswith("rate_"):
        await save_rating(update, context)
    elif data.startswith("report_"):
        await report_ride(update, context)
    elif data == "menu_find":
        await find_rides(update, context)
    elif data == "menu_profile":
        await profile_menu(update, context)
    elif data == "menu_admin" and chat_id == ADMIN_ID:
        await admin_menu(update, context)
    elif data.startswith("promote_"):
        await promote_ride(update, context)
    else:
        await update.callback_query.answer("❗ Функция в разработке")

# ---------------- ОБРАБОТЧИКИ TEXT ----------------
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    # Добавление времени и цены
    if chat_id in user_state:
        state = user_state[chat_id].get("add_ride")
        if state:
            if "time" not in state:
                await add_ride_time(update, context)
                return
            elif "price" not in state:
                await add_ride_price(update, context)
                return
            elif "photo" not in state:
                if update.message.text == "/skip":
                    await skip_photo(update, context)
                else:
                    await add_ride_photo(update, context)
                return
    # Жалобы
    if chat_id in user_state and "report" in user_state[chat_id]:
        await save_report(update, context)
        return

# ---------------- ЗАПУСК ----------------
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", start))

    # CallbackQuery
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Сообщения (ввод времени, цены, фото, жалобы)
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_handler))
    app.add_handler(MessageHandler(filters.PHOTO, message_handler))

    print("✅ BOT STARTED")
    app.run_polling(close_loop=False)
