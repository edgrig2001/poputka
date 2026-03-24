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
ADMIN_ID = 869818784  # ВСТАВЬ СВОЙ ID
DONATE_URL = "https://t.me/grigelav"
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# ---------------- WEB ----------------
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

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    photo TEXT
)
""")

conn.commit()

# ---------------- STATE ----------------
user_state = {}

# ---------------- UTILS ----------------
def get_user_rating(user_id):
    avg = cursor.execute(
        "SELECT AVG(rating) FROM ratings WHERE to_user=?",
        (user_id,)
    ).fetchone()[0]
    return round(avg, 1) if avg else 0

# ---------------- МЕНЮ ----------------
def main_menu(user_id):
    kb = [
        [InlineKeyboardButton("🚗 Найти поездку", callback_data="find")],
        [InlineKeyboardButton("➕ Предложить поездку", callback_data="add")],
        [InlineKeyboardButton("📋 Мои объявления", callback_data="my")],
        [InlineKeyboardButton("👤 Профиль", callback_data="profile")],
    ]

    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton("👑 Админка", callback_data="admin")])

    return InlineKeyboardMarkup(kb)

# ---------------- START ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚗 Попутка Челны ↔ Казань",
        reply_markup=main_menu(update.message.chat.id)
    )

# ---------------- СОЗДАНИЕ ----------------
def routes_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Челны → Казань", callback_data="route_1")],
        [InlineKeyboardButton("Казань → Челны", callback_data="route_2")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back")]
    ])

def seats_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(str(i), callback_data=f"seats_{i}") for i in range(1, 5)],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back")]
    ])

async def add_start(update, context):
    uid = update.callback_query.from_user.id
    user_state[uid] = {"step": "route"}
    await update.callback_query.edit_message_text(
        "Выбери маршрут:",
        reply_markup=routes_kb()
    )

async def set_route(update, context):
    uid = update.callback_query.from_user.id

    route = "Челны → Казань" if "1" in update.callback_query.data else "Казань → Челны"

    user_state[uid]["route"] = route
    user_state[uid]["step"] = "time"

    await update.callback_query.edit_message_text("Введи время:")

async def set_time(update, context):
    uid = update.message.chat.id

    if user_state.get(uid, {}).get("step") != "time":
        return

    user_state[uid]["time"] = update.message.text
    user_state[uid]["step"] = "seats"

    await update.message.reply_text("Сколько мест?", reply_markup=seats_kb())

async def set_seats(update, context):
    uid = update.callback_query.from_user.id

    if user_state.get(uid, {}).get("step") != "seats":
        return

    seats = int(update.callback_query.data.split("_")[1])

    user_state[uid]["seats"] = seats
    user_state[uid]["step"] = "price"

    await update.callback_query.edit_message_text("Цена:")

async def set_price(update, context):
    uid = update.message.chat.id

    if user_state.get(uid, {}).get("step") != "price":
        return

    user_state[uid]["price"] = update.message.text
    user_state[uid]["step"] = "contact"

    await update.message.reply_text("Контакт:")

async def set_contact(update, context):
    uid = update.message.chat.id

    if user_state.get(uid, {}).get("step") != "contact":
        return

    user_state[uid]["contact"] = update.message.text
    user_state[uid]["step"] = "photo"

    await update.message.reply_text("Фото или /skip")

async def save_ride(uid, photo, context):
    d = user_state[uid]

    cursor.execute("""
    INSERT INTO rides (user_id, route, time, seats_total, seats_taken, price, photo, contact)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        uid,
        d["route"],
        d["time"],
        d["seats"],
        0,
        d["price"],
        photo,
        d["contact"]
    ))

    conn.commit()
    user_state.pop(uid, None)

    await context.bot.send_message(
        uid,
        "✅ Поездка создана!",
        reply_markup=main_menu(uid)
    )
    
# ---------------- ПОИСК ----------------

async def find_rides(update, context):
    uid = update.callback_query.from_user.id

    rides = cursor.execute(
        "SELECT * FROM rides ORDER BY id DESC"
    ).fetchall()

    if not rides:
        await update.callback_query.edit_message_text(
            "❌ Нет поездок",
            reply_markup=main_menu(uid)
        )
        return

    await update.callback_query.edit_message_text("🔎 Найденные поездки:")

    for r in rides:
        text = (
            f"🚗 {r[2]}\n"
            f"🕒 {r[3]}\n"
            f"💺 {r[5]}/{r[4]}\n"
            f"💰 {r[6]}\n"
            f"📞 {r[8]}"
        )

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

async def book_seat(update, context):
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

    user = update.callback_query.from_user

    await context.bot.send_message(
        driver_id,
        f"📩 Новая бронь!\n"
        f"👤 @{user.username if user.username else 'нет юзернейма'}\n"
        f"ID: {user.id}"
    )


# ---------------- ПРОФИЛЬ ----------------

async def profile(update, context):
    uid = update.callback_query.from_user.id

    rating = get_user_rating(uid)

    text = f"👤 Профиль\n⭐ Рейтинг: {rating}"

    user_photo = cursor.execute(
        "SELECT photo FROM users WHERE user_id=?",
        (uid,)
    ).fetchone()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📷 Загрузить фото", callback_data="set_photo")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back")]
    ])

    if user_photo and user_photo[0]:
        await context.bot.send_photo(
            uid,
            user_photo[0],
            caption=text,
            reply_markup=kb
        )
    else:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=kb
        )


# ---------------- МОИ ОБЪЯВЛЕНИЯ ----------------

async def my_rides(update, context):
    uid = update.callback_query.from_user.id

    rides = cursor.execute(
        "SELECT * FROM rides WHERE user_id=? ORDER BY id DESC",
        (uid,)
    ).fetchall()

    if not rides:
        await update.callback_query.edit_message_text(
            "❌ У тебя нет поездок",
            reply_markup=main_menu(uid)
        )
        return

    await update.callback_query.edit_message_text("📋 Твои поездки:")

    for r in rides:
        text = (
            f"ID {r[0]}\n"
            f"🚗 {r[2]}\n"
            f"🕒 {r[3]}\n"
            f"💺 {r[5]}/{r[4]}\n"
            f"💰 {r[6]}"
        )

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Повысить", callback_data=f"promote_{r[0]}")]
        ])

        if r[7]:
            await context.bot.send_photo(uid, r[7], caption=text, reply_markup=kb)
        else:
            await context.bot.send_message(uid, text, reply_markup=kb)

# ---------------- РЕЙТИНГ ----------------

async def rate(update, context):
    ride_id = int(update.callback_query.data.split("_")[1])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(str(i), callback_data=f"rate_send_{ride_id}_{i}") for i in range(1, 6)]
    ])

    await update.callback_query.edit_message_text(
        "Выбери оценку:",
        reply_markup=kb
    )


async def save_rating(update, context):
    uid = update.callback_query.from_user.id

    _, _, ride_id, rating = update.callback_query.data.split("_")
    ride_id = int(ride_id)
    rating = int(rating)

    driver_id = cursor.execute(
        "SELECT user_id FROM rides WHERE id=?",
        (ride_id,)
    ).fetchone()[0]

    cursor.execute(
        "INSERT INTO ratings (ride_id, from_user, to_user, rating) VALUES (?, ?, ?, ?)",
        (ride_id, uid, driver_id, rating)
    )
    conn.commit()

    new_rating = get_user_rating(driver_id)

    await context.bot.send_message(
        driver_id,
        f"⭐ Тебя оценили!\nНовый рейтинг: {new_rating}"
    )

    await update.callback_query.answer("⭐ Оценка сохранена")
    await update.callback_query.edit_message_text(
        "Спасибо!",
        reply_markup=main_menu(uid)
    )


# ---------------- ЖАЛОБЫ ----------------

async def report(update, context):
    uid = update.callback_query.from_user.id
    ride_id = int(update.callback_query.data.split("_")[1])

    user_state[uid] = {"report": ride_id}
    await update.callback_query.edit_message_text("Напиши причину жалобы:")


async def handle_report_text(update, context):
    uid = update.message.chat.id

    if uid in user_state and "report" in user_state[uid]:
        ride_id = user_state[uid]["report"]
        reason = update.message.text

        cursor.execute(
            "INSERT INTO reports (ride_id, reporter_id, reason) VALUES (?, ?, ?)",
            (ride_id, uid, reason)
        )
        conn.commit()

        await update.message.reply_text("🚨 Жалоба отправлена")
        await context.bot.send_message(
            ADMIN_ID,
            f"🚨 Жалоба\nПоездка: {ride_id}\nПричина: {reason}"
        )
        user_state.pop(uid, None)


# ---------------- ЗАГРУЗКА ФОТО ПРОФИЛЯ ----------------

async def set_profile_photo(update, context):
    uid = update.callback_query.from_user.id
    user_state[uid] = {"step": "set_photo"}
    await update.callback_query.edit_message_text("Отправь фото профиля:")


async def handle_profile_photo(update, context):
    uid = update.message.chat.id
    if user_state.get(uid, {}).get("step") != "set_photo":
        return

    if update.message.photo:
        photo_id = update.message.photo[-1].file_id

        cursor.execute(
            "INSERT OR REPLACE INTO users (user_id, photo) VALUES (?, ?)",
            (uid, photo_id)
        )
        conn.commit()
        user_state.pop(uid, None)

        await update.message.reply_text("✅ Фото профиля обновлено", reply_markup=main_menu(uid))
    else:
        await update.message.reply_text("❌ Отправь фото!")


# ---------------- ПОВЫШЕНИЕ ----------------

async def promote(update, context):
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

async def admin(update, context):
    uid = update.callback_query.from_user.id

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Все поездки", callback_data="admin_all")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back")]
    ])

    await update.callback_query.edit_message_text(
        "👑 Админка",
        reply_markup=kb
    )


async def admin_all(update, context):
    uid = update.callback_query.from_user.id
    if uid != ADMIN_ID:
        await update.callback_query.answer("Нет доступа")
        return

    rides = cursor.execute("SELECT * FROM rides ORDER BY id DESC").fetchall()
    if not rides:
        await update.callback_query.edit_message_text("Нет поездок")
        return

    for r in rides:
        await context.bot.send_message(
            uid,
            f"ID {r[0]} | {r[2]} | {r[3]} | {r[6]}"
        )


# ---------------- CALLBACK ROUTER ----------------

async def callbacks(update, context):
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
    elif data == "admin_all":
        await admin_all(update, context)
    elif data == "set_photo":
        await set_profile_photo(update, context)
    else:
        await update.callback_query.answer("❗ Неизвестная команда")


# ---------------- ОБРАБОТКА СООБЩЕНИЙ ----------------

async def messages(update, context):
    uid = update.message.chat.id

    # создание поездки
    if uid in user_state:
        state = user_state[uid]

        if state.get("step") == "time":
            await set_time(update, context)
            return
        elif state.get("step") == "seats":
            await update.message.reply_text("Выбери кнопкой количество мест")
            return
        elif state.get("step") == "price":
            await set_price(update, context)
            return
        elif state.get("step") == "contact":
            await set_contact(update, context)
            return
        elif state.get("step") == "photo":
            text = update.message.text or ""
            if text.startswith("/skip"):
                await save_ride(uid, None, context)
            elif update.message.photo:
                await handle_photo(update, context)
            else:
                await update.message.reply_text("Отправь фото или напиши /skip")
            return
        elif state.get("step") == "set_photo":
            await handle_profile_photo(update, context)
            return

    # жалобы
    await handle_report_text(update, context)

    # если ничего не в процессе
    if uid not in user_state:
        await update.message.reply_text(
            "Используй меню 👇",
            reply_markup=main_menu(uid)
        )


# ---------------- ЗАПУСК ----------------

if __name__ == "__main__":
    threading.Thread(target=run_web).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, messages))

    print("✅ BOT STARTED")
    app.run_polling(close_loop=False)
