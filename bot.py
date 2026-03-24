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

# Поездки
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
    contact TEXT,
    priority INTEGER DEFAULT 0
)
""")

# Рейтинг
cursor.execute("""
CREATE TABLE IF NOT EXISTS ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ride_id INTEGER,
    from_user INTEGER,
    to_user INTEGER,
    rating INTEGER
)
""")

# Жалобы
cursor.execute("""
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ride_id INTEGER,
    reporter_id INTEGER,
    reason TEXT
)
""")

# Пользователи
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    photo TEXT
)
""")

# Анонимный чат
cursor.execute("""
CREATE TABLE IF NOT EXISTS chat (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ride_id INTEGER,
    from_user INTEGER,
    to_user INTEGER,
    message TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
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
        [InlineKeyboardButton("🎮 Скоротать время", callback_data="play_game")]
    ]
    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton("👑 Админка", callback_data="admin")])
    return InlineKeyboardMarkup(kb)

# ---------------- СОЗДАНИЕ ПОЕЗДКИ ----------------
def routes_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Челны → Казань", callback_data="route_1")],
        [InlineKeyboardButton("Казань → Челны", callback_data="route_2")],
        [InlineKeyboardButton("🏠 Меню", callback_data="back")]
    ])

def seats_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(str(i), callback_data=f"seats_{i}") for i in range(1, 5)],
        [InlineKeyboardButton("🏠 Меню", callback_data="back")]
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
    await update.callback_query.edit_message_text("Введи время (например 18:30):")

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
    await update.message.reply_text("Контакт (номер или @ник):")

async def set_contact(update, context):
    uid = update.message.chat.id
    if user_state.get(uid, {}).get("step") != "contact":
        return
    user_state[uid]["contact"] = update.message.text
    user_state[uid]["step"] = "photo"
    await update.message.reply_text("Отправь фото или /skip")
    
# ---------------- СОХРАНЕНИЕ ФОТО ПОЕЗДКИ ----------------
async def handle_photo(update, context):
    uid = update.message.chat.id
    if user_state.get(uid, {}).get("step") != "photo":
        return

    photo_id = update.message.photo[-1].file_id
    await save_ride(uid, photo_id, context)

async def skip_photo(update, context):
    uid = update.message.chat.id
    if user_state.get(uid, {}).get("step") != "photo":
        return
    await save_ride(uid, None, context)

async def save_ride(uid, photo, context):
    d = user_state[uid]
    cursor.execute("""
    INSERT INTO rides (user_id, route, time, seats_total, seats_taken, price, photo)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        uid,
        d["route"],
        d["time"],
        d["seats"],
        0,
        d["price"],
        photo
    ))
    conn.commit()
    user_state.pop(uid, None)
    await context.bot.send_message(
        uid,
        "✅ Поездка создана!",
        reply_markup=main_menu(uid)
    )

# ---------------- ПОИСК ПОЕЗДОК ----------------
async def find_rides(update, context):
    uid = update.callback_query.from_user.id
    rides = cursor.execute(
        "SELECT * FROM rides ORDER BY priority DESC, id DESC"
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
            f"{'🚀 ' if r[9] else ''}🚗 {r[2]}\n"
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
    # уведомление водителю
    await context.bot.send_message(
        driver_id,
        f"📩 Новая бронь!\n"
        f"👤 @{user.username if user.username else 'нет юзернейма'}\n"
        f"ID: {user.id}"
    )


# ---------------- ПРОФИЛЬ ----------------

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
        [InlineKeyboardButton("⬅️ Меню", callback_data="back")]
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
        "SELECT * FROM rides WHERE user_id=? ORDER BY priority DESC, id DESC",
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
            f"{'🚀 ' if r[9] else ''}ID {r[0]}\n"
            f"🚗 {r[2]}\n"
            f"🕒 {r[3]}\n"
            f"💺 {r[5]}/{r[4]}\n"
            f"💰 {r[6]}"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Повысить", callback_data=f"promote_{r[0]}")],
            [InlineKeyboardButton("⬅️ Меню", callback_data="back")]
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
    await update.callback_query.edit_message_text("Выбери оценку:", reply_markup=kb)

async def save_rating(update, context):
    uid = update.callback_query.from_user.id
    _, _, ride_id, rating = update.callback_query.data.split("_")
    ride_id, rating = int(ride_id), int(rating)

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
    await context.bot.send_message(driver_id, f"⭐ Тебя оценили!\nНовый рейтинг: {new_rating}")
    await update.callback_query.answer("⭐ Оценка сохранена")
    await update.callback_query.edit_message_text("Спасибо!", reply_markup=main_menu(uid))

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

# ---------------- ПОВЫШЕНИЕ ПРИОРИТЕТА ----------------
async def promote(update, context):
    ride_id = int(update.callback_query.data.split("_")[1])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Оплатить", url=DONATE_URL)],
        [InlineKeyboardButton("⬅️ Меню", callback_data="back")]
    ])

    await update.callback_query.edit_message_text(
        f"🚀 Повышение поездки ID {ride_id}\nПосле оплаты отметь админа",
        reply_markup=kb
    )

# ---------------- АДМИНКА ----------------
async def admin(update, context):
    uid = update.callback_query.from_user.id
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Все поездки", callback_data="admin_all")],
        [InlineKeyboardButton("⬅️ Меню", callback_data="back")]
    ])
    await update.callback_query.edit_message_text("👑 Админка", reply_markup=kb)

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
            f"ID {r[0]} | {r[2]} | {r[3]} | {r[6]} | {'🚀' if r[9] else ''}"
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

    # Создание поездки
    if uid in user_state:
        state = user_state[uid]

        # Время
        if state.get("step") == "time":
            await set_time(update, context)
            return

        # Места
        elif state.get("step") == "seats":
            await update.message.reply_text("Выбери кнопкой количество мест")
            return

        # Цена
        elif state.get("step") == "price":
            await set_price(update, context)
            return

        # Контакт
        elif state.get("step") == "contact":
            await set_contact(update, context)
            return

        # Фото поездки
        elif state.get("step") == "photo":
            text = update.message.text or ""
            if text.startswith("/skip"):
                await save_ride(uid, None, context)
            elif update.message.photo:
                photo_id = update.message.photo[-1].file_id
                await save_ride(uid, photo_id, context)
            else:
                await update.message.reply_text("Отправь фото или напиши /skip")
            return

        # Фото профиля
        elif state.get("step") == "set_photo":
            await handle_profile_photo(update, context)
            return

        # Анонимная переписка
        elif state.get("step") == "chat_anon":
            chat_data = state.get("chat_data")
            if chat_data:
                # Отправка другому участнику, только админ видит всех
                for participant_id in chat_data["participants"]:
                    if participant_id != uid:
                        await context.bot.send_message(participant_id, f"💬 Аноним: {update.message.text}")
                await context.bot.send_message(ADMIN_ID, f"💬 Аноним сообщение от {uid}: {update.message.text}")
            return

        # Мини-игра
        elif state.get("step") == "mini_game":
            await update.message.reply_text("🎲 Игра ещё в разработке. Скоро можно будет сыграть!")
            return

    # Жалобы
    await handle_report_text(update, context)

    # Если ничего не в процессе
    if uid not in user_state:
        # Меню всегда внизу, чтобы не писать /start
        kb = main_menu(uid)
        await update.message.reply_text(
            "Используй меню 👇",
            reply_markup=kb
        )

# ---------------- ФОТО ПОЕЗДКИ ----------------
async def handle_photo(update, context):
    uid = update.message.chat.id
    if user_state.get(uid, {}).get("step") != "photo":
        return
    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
        await save_ride(uid, photo_id, context)

async def skip_photo(update, context):
    uid = update.message.chat.id
    if user_state.get(uid, {}).get("step") != "photo":
        return
    await save_ride(uid, None, context)

# ---------------- МИНИ-ИГРА ----------------
async def mini_game(update, context):
    uid = update.callback_query.from_user.id
    user_state[uid] = {"step": "mini_game"}
    await update.callback_query.edit_message_text(
        "🎮 Мини-игра пока простая: нажми любую кнопку для случайного события!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎲 Бросить кубик", callback_data="roll_dice")],
                                          [InlineKeyboardButton("⬅️ Меню", callback_data="back")]])
    )

async def roll_dice(update, context):
    import random
    uid = update.callback_query.from_user.id
    result = random.randint(1, 6)
    await update.callback_query.answer(f"🎲 Выпало: {result}")
    # ---------------- ОБНОВЛЕНИЕ ПОИСКА С ПРИОРИТЕТОМ ----------------
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
        # Если поездка оплачена (например, повышенный приоритет)
        priority = "🚀 " if r[9] if len(r) > 9 else False else ""
        text = (
            f"{priority}🚗 {r[2]}\n"
            f"🕒 {r[3]}\n"
            f"💺 {r[5]}/{r[4]}\n"
            f"💰 {r[6]}\n"
            f"📞 {r[8]}"
        )

        kb = [
            [InlineKeyboardButton("💺 Бронировать", callback_data=f"book_{r[0]}")],
            [InlineKeyboardButton("⭐ Оценить", callback_data=f"rate_{r[0]}")],
            [InlineKeyboardButton("🚨 Жалоба", callback_data=f"report_{r[0]}")],
        ]

        # Добавляем кнопку для анонимного чата после брони
        if r[5] > 0 and r[5] > r[5]:  # если места забронированы (пример логики)
            kb.append([InlineKeyboardButton("💬 Анонимный чат", callback_data=f"chat_{r[0]}")])

        kb_markup = InlineKeyboardMarkup(kb)

        # Фото поездки
        if r[7]:
            await context.bot.send_photo(uid, r[7], caption=text, reply_markup=kb_markup)
        else:
            await context.bot.send_message(uid, text, reply_markup=kb_markup)

# ---------------- АНОНИМНЫЙ ЧАТ ----------------
async def start_anon_chat(update, context):
    uid = update.callback_query.from_user.id
    ride_id = int(update.callback_query.data.split("_")[1])

    # Получаем участников, кроме текущего юзера
    participants = [row[0] for row in cursor.execute(
        "SELECT user_id FROM rides WHERE id=?",
        (ride_id,)
    ).fetchall()]

    participants = [p for p in participants if p != uid]

    user_state[uid] = {"step": "chat_anon", "chat_data": {"ride_id": ride_id, "participants": participants}}

    await update.callback_query.edit_message_text(
        "💬 Анонимный чат активирован. Пиши сообщения. Админ видит всё.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="back")]])
    )
# ---------------- CALLBACK ROUTER ОБНОВЛЕНИЕ ----------------
async def callbacks(update, context):
    data = update.callback_query.data
    uid = update.callback_query.from_user.id

    if data == "back":
        await update.callback_query.edit_message_text(
            "Меню",
            reply_markup=main_menu(uid)
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
    elif data.startswith("chat_"):
        await start_anon_chat(update, context)
    elif data == "game":
        await mini_game(update, context)
    else:
        await update.callback_query.answer("❗ Неизвестная команда")


# ---------------- МИНИ-ИГРА ----------------
async def mini_game(update, context):
    uid = update.callback_query.from_user.id
    await update.callback_query.edit_message_text(
        "🎮 Мини-игра: угадай число от 1 до 5. Напиши число:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="back")]])
    )
    user_state[uid] = {"step": "game", "number": str(random.randint(1, 5))}

async def handle_game(update, context):
    uid = update.message.chat.id
    state = user_state.get(uid, {})

    if state.get("step") != "game":
        return

    guess = update.message.text.strip()
    if guess == state["number"]:
        await update.message.reply_text("🎉 Правильно! Вы выиграли!", reply_markup=main_menu(uid))
    else:
        await update.message.reply_text(f"❌ Неправильно. Было {state['number']}", reply_markup=main_menu(uid))

    user_state.pop(uid, None)
    # ---------------- ОБРАБОТКА СООБЩЕНИЙ ОБНОВЛЕНИЕ ----------------
async def messages(update, context):
    uid = update.message.chat.id
    text = update.message.text or ""

    # --- Создание поездки ---
    if uid in user_state:
        state = user_state[uid]

        # Ввод времени
        if state.get("step") == "time":
            await set_time(update, context)
            return
        # Выбор мест
        elif state.get("step") == "seats":
            await update.message.reply_text("Выбери кнопкой количество мест")
            return
        # Ввод цены
        elif state.get("step") == "price":
            await set_price(update, context)
            return
        # Ввод контакта
        elif state.get("step") == "contact":
            await set_contact(update, context)
            return
        # Фото поездки
        elif state.get("step") == "photo":
            if text.startswith("/skip"):
                await save_ride(uid, None, context)
            elif update.message.photo:
                photo_id = update.message.photo[-1].file_id
                await save_ride(uid, photo_id, context)
            else:
                await update.message.reply_text("Отправь фото или напиши /skip")
            return
        # Фото профиля
        elif state.get("step") == "set_photo":
            await handle_profile_photo(update, context)
            return
        # Мини-игра
        elif state.get("step") == "game":
            await handle_game(update, context)
            return
        # Анонимный чат
        elif state.get("step") == "anon_chat":
            ride_id = state["ride_id"]
            other_user = state["other_user"]
            # отправляем сообщение другому участнику
            await context.bot.send_message(
                other_user,
                f"✉ Анонимное сообщение:\n{text}"
            )
            # админ видит все
            await context.bot.send_message(
                ADMIN_ID,
                f"[Анонимный чат] {uid} -> {other_user}:\n{text}"
            )
            await update.message.reply_text("✅ Сообщение отправлено", reply_markup=main_menu(uid))
            return

    # --- Жалобы ---
    await handle_report_text(update, context)

    # --- Если ничего не в процессе ---
    if uid not in user_state:
        await update.message.reply_text(
            "Используй меню 👇",
            reply_markup=main_menu(uid)
        )
        # ---------------- ПРИОРИТЕТ И ОТОБРАЖЕНИЕ ОПЛАЧЕННЫХ ----------------

# Добавим поле "priority" в таблицу rides (0 = обычная, 1 = оплачено)
cursor.execute("""
ALTER TABLE rides
ADD COLUMN priority INTEGER DEFAULT 0
""")
conn.commit()

# Функция для пометки поездки как оплаченной
async def mark_priority(update, context, ride_id):
    cursor.execute(
        "UPDATE rides SET priority=1 WHERE id=?",
        (ride_id,)
    )
    conn.commit()

    await update.callback_query.edit_message_text(
        f"🚀 Поездка ID {ride_id} помечена как оплаченная!",
        reply_markup=main_menu(update.callback_query.from_user.id)
    )

# Обновление отображения поездки в поиске и в моих объявлениях
def ride_text(r):
    # Если priority == 1, добавляем эмодзи 🔥
    prio = " 🔥" if r[9] == 1 else ""
    return (
        f"ID {r[0]}{prio}\n"
        f"🚗 {r[2]}\n"
        f"🕒 {r[3]}\n"
        f"💺 {r[5]}/{r[4]}\n"
        f"💰 {r[6]}\n"
        f"📞 {r[8]}"
    )

# Обновление поиска поездок
async def find_rides(update, context):
    uid = update.callback_query.from_user.id

    rides = cursor.execute("SELECT * FROM rides ORDER BY priority DESC, id DESC").fetchall()

    if not rides:
        await update.callback_query.edit_message_text(
            "❌ Нет поездок",
            reply_markup=main_menu(uid)
        )
        return

    await update.callback_query.edit_message_text("🔎 Найденные поездки:")

    for r in rides:
        text = ride_text(r)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💺 Бронировать", callback_data=f"book_{r[0]}")],
            [InlineKeyboardButton("⭐ Оценить", callback_data=f"rate_{r[0]}")],
            [InlineKeyboardButton("🚨 Жалоба", callback_data=f"report_{r[0]}")]
        ])
        if r[7]:
            await context.bot.send_photo(uid, r[7], caption=text, reply_markup=kb)
        else:
            await context.bot.send_message(uid, text, reply_markup=kb)

# Обновление "Мои поездки"
async def my_rides(update, context):
    uid = update.callback_query.from_user.id

    rides = cursor.execute("SELECT * FROM rides WHERE user_id=? ORDER BY priority DESC, id DESC", (uid,)).fetchall()

    if not rides:
        await update.callback_query.edit_message_text(
            "❌ У тебя нет поездок",
            reply_markup=main_menu(uid)
        )
        return

    await update.callback_query.edit_message_text("📋 Твои поездки:")

    for r in rides:
        text = ride_text(r)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Повысить", callback_data=f"promote_{r[0]}")]
        ])
        if r[7]:
            await context.bot.send_photo(uid, r[7], caption=text, reply_markup=kb)
        else:
            await context.bot.send_message(uid, text, reply_markup=kb)
            # ---------------- ВСЕГДА КНОПКА МЕНЮ ----------------
def reply_with_menu(uid, text, context, extra_kb=None):
    """
    Отправляет сообщение с прикрепленной кнопкой меню.
    extra_kb - можно передать дополнительную клавиатуру
    """
    kb = [[InlineKeyboardButton("🏠 Меню", callback_data="back")]]
    if extra_kb:
        kb = extra_kb + kb
    markup = InlineKeyboardMarkup(kb)
    context.bot.send_message(uid, text, reply_markup=markup)


# ---------------- АНОНИМНЫЙ ЧАТ ----------------
# структура: {ride_id: [user1_id, user2_id]}
anon_chat = {}  

async def start_anon_chat(update, context, ride_id, uid):
    """
    Инициализация анонимного чата между пользователями, видят только они и админ.
    """
    if ride_id not in anon_chat:
        # Получаем участников
        ride = cursor.execute("SELECT user_id FROM rides WHERE id=?", (ride_id,)).fetchone()
        if not ride:
            await update.callback_query.answer("Ошибка")
            return
        driver_id = ride[0]
        if uid == driver_id:
            await update.callback_query.answer("Ты водитель, жди пассажиров")
            return
        anon_chat[ride_id] = [driver_id, uid]

    await update.callback_query.edit_message_text(
        "🗨 Анонимный чат активирован. Пиши сообщения, их видит только другой участник и админ.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Меню", callback_data="back")]])
    )

async def handle_anon_message(update, context):
    uid = update.message.chat.id
    text = update.message.text
    for ride_id, users in anon_chat.items():
        if uid in users:
            # Отправка сообщения другому участнику
            other = [u for u in users if u != uid][0]
            await context.bot.send_message(other, f"💬 Аноним: {text}")
            # Админ видит все
            await context.bot.send_message(ADMIN_ID, f"🕵 Анонимный чат {ride_id} | {uid}: {text}")
            return
            # ---------------- ВСЕГДА КНОПКА МЕНЮ ----------------
def reply_with_menu(uid, text, context, extra_kb=None):
    """
    Отправляет сообщение с прикрепленной кнопкой меню.
    extra_kb - можно передать дополнительную клавиатуру
    """
    kb = [[InlineKeyboardButton("🏠 Меню", callback_data="back")]]
    if extra_kb:
        kb = extra_kb + kb
    markup = InlineKeyboardMarkup(kb)
    context.bot.send_message(uid, text, reply_markup=markup)


# ---------------- АНОНИМНЫЙ ЧАТ ----------------
# структура: {ride_id: [user1_id, user2_id]}
anon_chat = {}  

async def start_anon_chat(update, context, ride_id, uid):
    """
    Инициализация анонимного чата между пользователями, видят только они и админ.
    """
    if ride_id not in anon_chat:
        # Получаем участников
        ride = cursor.execute("SELECT user_id FROM rides WHERE id=?", (ride_id,)).fetchone()
        if not ride:
            await update.callback_query.answer("Ошибка")
            return
        driver_id = ride[0]
        if uid == driver_id:
            await update.callback_query.answer("Ты водитель, жди пассажиров")
            return
        anon_chat[ride_id] = [driver_id, uid]

    await update.callback_query.edit_message_text(
        "🗨 Анонимный чат активирован. Пиши сообщения, их видит только другой участник и админ.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Меню", callback_data="back")]])
    )

async def handle_anon_message(update, context):
    uid = update.message.chat.id
    text = update.message.text
    for ride_id, users in anon_chat.items():
        if uid in users:
            # Отправка сообщения другому участнику
            other = [u for u in users if u != uid][0]
            await context.bot.send_message(other, f"💬 Аноним: {text}")
            # Админ видит все
            await context.bot.send_message(ADMIN_ID, f"🕵 Анонимный чат {ride_id} | {uid}: {text}")
            return
            # ---------------- ОБНОВЛЕНИЕ CALLBACK ROUTER ----------------

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
        ride_id = int(data.split("_")[1])
        await promote(update, context)
        # Можно отметить как оплачено после подтверждения
        # await mark_priority(update, context, ride_id)
    elif data == "admin":
        await admin(update, context)
    elif data == "admin_all":
        await admin_all(update, context)
    elif data == "set_photo":
        await set_profile_photo(update, context)
    elif data == "play_game":
        await start_game(update, context)
    elif data.startswith("guess_"):
        await handle_guess(update, context)
    else:
        await update.callback_query.answer("❗ Неизвестная команда")
        # ---------------- ОБНОВЛЕНИЕ CALLBACK ROUTER ----------------

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
        ride_id = int(data.split("_")[1])
        await promote(update, context)
        # Можно отметить как оплачено после подтверждения
        # await mark_priority(update, context, ride_id)
    elif data == "admin":
        await admin(update, context)
    elif data == "admin_all":
        await admin_all(update, context)
    elif data == "set_photo":
        await set_profile_photo(update, context)
    elif data == "play_game":
        await start_game(update, context)
    elif data.startswith("guess_"):
        await handle_guess(update, context)
    else:
        await update.callback_query.answer("❗ Неизвестная команда")

# ---------------- ЗАПУСК ----------------

if __name__ == "__main__":
    threading.Thread(target=run_web).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, messages))

    print("✅ BOT STARTED")
    app.run_polling(close_loop=False)
