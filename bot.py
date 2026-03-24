import os
import sqlite3
import threading
from flask import Flask

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
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
    photo TEXT,
    contact TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ride_id INTEGER,
    from_user INTEGER,
    to_user INTEGER,
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
        [InlineKeyboardButton("🚗 Найти поездку", callback_data="find")],
        [InlineKeyboardButton("➕ Предложить поездку", callback_data="add")],
        [InlineKeyboardButton("📋 Мои объявления", callback_data="my")],
        [InlineKeyboardButton("👤 Профиль", callback_data="profile")],
    ]

    # только тебе админка
    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton("👑 Админка", callback_data="admin")])

    return InlineKeyboardMarkup(kb)
    

# ---------------- START ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    await update.message.reply_text(
        "🚗 Попутка Челны ↔ Казань",
        reply_markup=main_menu(chat_id)
    )

# ---------------- СОЗДАНИЕ ПОЕЗДКИ ----------------

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

# старт создания
async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    user_state[uid] = {"step": "route"}
    await update.callback_query.edit_message_text("Выбери маршрут:", reply_markup=routes_kb())

# выбор маршрута
async def set_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id

    route = "Челны → Казань" if "1" in update.callback_query.data else "Казань → Челны"
    user_state[uid]["route"] = route
    user_state[uid]["step"] = "time"

    await update.callback_query.edit_message_text("Введи время (например 18:30):")

# ввод времени
async def set_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat.id

    if uid not in user_state or user_state[uid].get("step") != "time":
        return

    user_state[uid]["time"] = update.message.text
    user_state[uid]["step"] = "seats"

    await update.message.reply_text("Сколько мест?", reply_markup=seats_kb())

# выбор мест
async def set_seats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id

    if user_state.get(uid, {}).get("step") != "seats":
        return

    seats = int(update.callback_query.data.split("_")[1])
    user_state[uid]["seats"] = seats
    user_state[uid]["step"] = "price"

    await update.callback_query.edit_message_text("Введи цену (или 'договорная'):")

# ввод цены
async def set_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat.id

    if user_state.get(uid, {}).get("step") != "price":
        return
user_state[uid]["step"] = "contact"
await update.message.reply_text("Напиши @никнейм или номер для связи:")

    user_state[uid]["price"] = "update.message.text"
    user_state[uid]["step"] = "photo"

    await update.message.reply_text("Отправь фото или /skip")

# фото или пропуск
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat.id

    if user_state.get(uid, {}).get("step") != "photo":
        return

    photo_id = update.message.photo[-1].file_id
    await save_ride(uid, photo_id, context)

async def skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat.id

    if user_state.get(uid, {}).get("step") != "photo":
        return

    await save_ride(uid, None, context)

# сохранение
async def save_ride(uid, photo, context):
    data = user_state[uid]

    cursor.execute("""
       INSERT INTO rides (user_id, route, time, seats_total, price, photo, contact)
VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (uid, ..., photo, data["contact"])

    conn.commit()

    await context.bot.send_message(uid, "✅ Поездка создана!", reply_markup=main_menu(uid))

    user_state.pop(uid, None)
    
# ---------------- ПОИСК ----------------

async def find_rides(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id

    rides = cursor.execute("SELECT * FROM rides ORDER BY id DESC").fetchall()

    if not rides:
        await update.callback_query.edit_message_text("❌ Нет поездок", reply_markup=main_menu(uid))
        return

    await update.callback_query.edit_message_text("🔎 Найденные поездки:")

    for r in rides:
        text = f"🚗 {r[2]}\n🕒 {r[3]}\n💺 {r[5]}/{r[4]}\n💰 {r[6]}"

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💺 Бронировать", callback_data=f"book_{r[0]}")],
            [InlineKeyboardButton("⭐ Оценить", callback_data=f"rate_{r[0]}")],
            [InlineKeyboardButton("🚨 Жалоба", callback_data=f"report_{r[0]}")]
        ])

        if r[7]:
            await context.bot.send_photo(uid, r[7], caption=text, reply_markup=kb)
        else:
            await context.bot.send_message(uid, text, reply_markup=kb)


# ---------------- БРОНИРОВАНИЕ ----------------

async def book_seat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    ride_id = int(update.callback_query.data.split("_")[1])

    ride = cursor.execute(
        "SELECT seats_total, seats_taken, user_id FROM rides WHERE id=?",
        (ride_id,)
    ).fetchone()

    if not ride:
        await update.callback_query.answer("Ошибка")
        return

    seats_total, seats_taken, driver_id = ride

    if seats_taken >= seats_total:
        await update.callback_query.answer("❌ Мест нет")
        return

    cursor.execute(
        "UPDATE rides SET seats_taken = seats_taken + 1 WHERE id=?",
        (ride_id,)
    )
    conn.commit()

    await update.callback_query.answer("✅ Забронировано")

    # уведомление водителю
    await context.bot.send_message(
        driver_id,
        f"📩 У вас новая бронь! Поездка ID {ride_id}"
    )
# ---------------- ПРОФИЛЬ ----------------
photos = await context.bot.get_user_profile_photos(uid)

if photos.total_count > 0:
    photo_id = photos.photos[0][0].file_id
else:
    photo_id = None
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id

    avg = cursor.execute(
        "SELECT AVG(rating) FROM ratings WHERE user_id=?",
        (uid,)
    ).fetchone()[0]

    avg = round(avg, 1) if avg else 0

    text = f"👤 Профиль\n⭐ Рейтинг: {avg}"

   if photo_id:
    await context.bot.send_photo(
        uid,
        photo_id,
        caption=text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data="back")]
        ])
    )
else:
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data="back")]
        ])
    )

# ---------------- МОИ ОБЪЯВЛЕНИЯ ----------------

async def my_rides(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id

    rides = cursor.execute(
        "SELECT * FROM rides WHERE user_id=? ORDER BY id DESC",
        (uid,)
    ).fetchall()

    if not rides:
        await update.callback_query.edit_message_text("❌ У тебя нет поездок", reply_markup=main_menu(uid))
        return

    await update.callback_query.edit_message_text("📋 Твои поездки:")

    for r in rides:
        text = f"ID {r[0]}\n🚗 {r[2]}\n🕒 {r[3]}\n💺 {r[5]}/{r[4]}\n💰 {r[6]}"

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Повысить", callback_data=f"promote_{r[0]}")]
        ])

       user = update.callback_query.from_user

await context.bot.send_message(
    driver_id,
    f"📩 Бронь!\n👤 @{user.username}\nID: {user.id}"
)


# ---------------- РЕЙТИНГ ----------------

async def rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    ride_id = int(update.callback_query.data.split("_")[1])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(str(i), callback_data=f"rate_send_{ride_id}_{i}") for i in range(1,6)]
    ])

    await update.callback_query.edit_message_text("Выбери оценку:", reply_markup=kb)


async def save_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id

    _, _, ride_id, rating = update.callback_query.data.split("_")
    ride_id = int(ride_id)
    rating = int(rating)

# находим владельца поездки
driver_id = cursor.execute(
    "SELECT user_id FROM rides WHERE id=?",
    (ride_id,)
).fetchone()[0]

# если водитель оценивает → значит оценивает пассажира (пока пропустим)
# если обычный пользователь → оценивает водителя

cursor.execute(
    "INSERT INTO ratings (ride_id, from_user, to_user, rating) VALUES (?, ?, ?, ?)",
    (ride_id, uid, driver_id, rating)
)
    conn.commit()

    await update.callback_query.answer("⭐ Оценка сохранена")
    await update.callback_query.edit_message_text("Спасибо!", reply_markup=main_menu(uid))


# ---------------- ЖАЛОБЫ ----------------

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    ride_id = int(update.callback_query.data.split("_")[1])

    user_state[uid] = {"report": ride_id}

    await update.callback_query.edit_message_text("Напиши причину жалобы:")


async def handle_report_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat.id

    if uid not in user_state or "report" not in user_state[uid]:
        return

    ride_id = user_state[uid]["report"]
    reason = update.message.text

    cursor.execute(
        "INSERT INTO reports (ride_id, reporter_id, reason) VALUES (?, ?, ?)",
        (ride_id, uid, reason)
    )
    conn.commit()

    await update.message.reply_text("🚨 Жалоба отправлена")

    # админу
    await context.bot.send_message(
        ADMIN_ID,
        f"🚨 Жалоба\nПоездка: {ride_id}\nПричина: {reason}"
    )

    user_state.pop(uid)

# ---------------- ПОВЫШЕНИЕ ----------------

async def promote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    ride_id = int(update.callback_query.data.split("_")[1])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Оплатить", url=DONATE_URL)],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back")]
    ])

    await update.callback_query.edit_message_text(
        f"🚀 Повышение поездки ID {ride_id}\nПосле оплаты напиши админу",
        reply_markup=kb
    )

# ---------------- АДМИНКА ----------------

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Все поездки", callback_data="admin_all")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back")]
    ])

    await update.callback_query.edit_message_text("👑 Админка", reply_markup=kb)

# ---------------- CALLBACK ROUTER ----------------

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data

    if data == "back":
        await update.callback_query.edit_message_text(
            "Меню",
            reply_markup=main_menu(update.callback_query.from_user.id)
        )

    elif data == "add":
        await add_start(update, context)

    elif data.startswith("route_"):
        await set_route(update, context)

    elif data.startswith("seats_"):
        await set_seats(update, context)

    elif data == "find":
        await find_rides(update, context)

    elif data.startswith("book_"):
        await book_seat(update, context)

    elif data == "profile":
        await profile(update, context)

    elif data == "my":
        await my_rides(update, context)

    elif data.startswith("rate_send_"):
        await save_rating(update, context)

    elif data.startswith("rate_"):
        await rate(update, context)

    elif data.startswith("report_"):
        await report(update, context)

    elif data.startswith("promote_"):
        await promote(update, context)

    elif data == "admin":
        await admin(update, context)

    else:
        await update.callback_query.answer("❗ Неизвестная команда")
async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat.id

    # создание поездки
    if uid in user_state:
        state = user_state[uid]

        if state.get("step") == "time":
            await set_time(update, context)
            return

        if state.get("step") == "price":
            await set_price(update, context)
            return

        if state.get("step") == "photo":
            if update.message.text == "/skip":
                await skip_photo(update, context)
            elif update.message.photo:
                await handle_photo(update, context)
            return

    # жалобы
    await handle_report_text(update, context)

if __name__ == "__main__":
    threading.Thread(target=run_web).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, messages))

    print("✅ BOT STARTED")
    app.run_polling(close_loop=False)
