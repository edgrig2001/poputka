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

# ---------------- Состояние пользователей ----------------
user_state = {}

# ---------------- Клавиатуры ----------------
def main_menu(user_id=None):
    kb = [
        [InlineKeyboardButton("➕ Предложить поездку", callback_data="add")],
        [InlineKeyboardButton("🚗 Найти поездку", callback_data="find")],
        [InlineKeyboardButton("📋 Мои поездки", callback_data="my")],
        [InlineKeyboardButton("⭐ Оценить поездку", callback_data="rate")],
        [InlineKeyboardButton("🚨 Пожаловаться", callback_data="report")],
        [InlineKeyboardButton("💰 Повысить приоритет", url=DONATE_URL)]
    ]
    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton("👑 Админка", callback_data="admin")])
    return InlineKeyboardMarkup(kb)

def route_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Челны → Казань", callback_data="route_chkaz")],
        [InlineKeyboardButton("Казань → Челны", callback_data="route_kazch")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="menu")]
    ])

def seats_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(str(i), callback_data=f"seats_{i}") for i in range(1,5)],
        [InlineKeyboardButton("⬅️ Назад", callback_data="menu")]
    ])

def time_kb():
    kb = []
    for h in range(8, 23, 2):
        kb.append([InlineKeyboardButton(f"{h}:00", callback_data=f"time_{h}:00")])
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="menu")])
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
    if data=="menu":
        user_state.pop(chat_id, None)
        await query.edit_message_text("🏠 Главное меню:", reply_markup=main_menu(chat_id))
        return

    # Добавление поездки
    if data=="add":
        user_state[chat_id] = {"step":"route"}
        await query.edit_message_text("Выберите маршрут:", reply_markup=route_kb())
        return

    if data in ["route_chkaz", "route_kazch"]:
        state["route"] = "Челны → Казань" if data=="route_chkaz" else "Казань → Челны"
        state["step"]="time"
        user_state[chat_id] = state
        await query.edit_message_text("Выберите время отправления:", reply_markup=time_kb())
        return

    if data.startswith("time_"):
        state["time"]=data[5:]
        state["step"]="seats"
        user_state[chat_id] = state
        await query.edit_message_text("Выберите количество мест:", reply_markup=seats_kb())
        return

    if data.startswith("seats_"):
        state["seats"]=int(data[6:])
        state["step"]="price"
        user_state[chat_id]=state
        await query.edit_message_text("Введите цену (или 'договорная'):")
        return

    # Найти поездку
    if data=="find":
        cursor.execute("SELECT * FROM rides ORDER BY id DESC LIMIT 10")
        rides = cursor.fetchall()
        if not rides:
            await query.edit_message_text("🚫 Пока нет поездок", reply_markup=main_menu(chat_id))
            return
        for r in rides:
            text = f"🚗 {r[2]}\n🕒 {r[3]}\n💺 {r[5]}/{r[4]}\n💰 {r[6]}"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"💺 Забронировать {r[0]}", callback_data=f"book_{r[0]}")]])
            if r[7]:
                await context.bot.send_photo(chat_id, r[7], caption=text, reply_markup=kb)
            else:
                await query.edit_message_text(text, reply_markup=kb)
        return

    # Бронирование
    if data.startswith("book_"):
        ride_id=int(data[5:])
        cursor.execute("SELECT seats_total,seats_taken,user_id FROM rides WHERE id=?",(ride_id,))
        ride=cursor.fetchone()
        if not ride:
            await query.edit_message_text("Ошибка!", reply_markup=main_menu(chat_id))
            return
        seats_total,seats_taken,driver_id=ride
        if seats_taken>=seats_total:
            await query.edit_message_text("❌ Все места заняты", reply_markup=main_menu(chat_id))
            return
        cursor.execute("UPDATE rides SET seats_taken=seats_taken+1 WHERE id=?",(ride_id,))
        conn.commit()
        await query.edit_message_text("✅ Вы забронировали место!", reply_markup=main_menu(chat_id))
        await context.bot.send_message(driver_id,f"💬 @{query.from_user.username} забронировал(-а) у вас место {ride_id}")
        return
        # ---------------- Сообщения ----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id=update.message.chat.id
    state=user_state.get(chat_id,{})
    step=state.get("step")
    text=update.message.text

    if not step:
        await update.message.reply_text("🏠 Главное меню", reply_markup=main_menu(chat_id))
        return

    # Ввод цены
    if step=="price":
        state["price"]=text
        state["step"]="photo"
        user_state[chat_id]=state
        await update.message.reply_text("Можно отправить фото авто/себя или пропустить командой /skip")
        return

    # Фото
    if step=="photo" and update.message.photo:
        file_id=update.message.photo[-1].file_id
        state["photo"]=file_id
        cursor.execute(
            "INSERT INTO rides (user_id, route, time, seats_total, price, photo) VALUES (?,?,?,?,?,?)",
            (chat_id,state["route"],state["time"],state["seats"],state["price"],file_id)
        )
        conn.commit()
        await update.message.reply_text("✅ Объявление создано!", reply_markup=main_menu(chat_id))
        user_state.pop(chat_id)
        return

# Пропустить фото
async def skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id=update.message.chat.id
    state=user_state.get(chat_id)
    if state and state.get("step")=="photo":
        cursor.execute(
            "INSERT INTO rides (user_id, route, time, seats_total, price) VALUES (?,?,?,?,?)",
            (chat_id,state["route"],state["time"],state["seats"],state["price"])
        )
        conn.commit()
        await update.message.reply_text("✅ Объявление создано!", reply_markup=main_menu(chat_id))
        user_state.pop(chat_id)

# ---------------- Профиль пользователя ----------------
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id=update.message.chat.id
    cursor.execute("SELECT AVG(rating) FROM ratings WHERE user_id=?", (chat_id,))
    avg_rating=cursor.fetchone()[0]
    avg_rating=round(avg_rating,1) if avg_rating else 0

    cursor.execute("SELECT * FROM rides WHERE user_id=? ORDER BY id DESC", (chat_id,))
    rides=cursor.fetchall()
    ride_text="Нет поездок" if not rides else "\n".join([f"ID {r[0]}: {r[2]} {r[3]} {r[4]} мест" for r in rides])

    text=f"👤 Ваш профиль\n⭐ Рейтинг: {avg_rating}\n📋 Мои поездки:\n{ride_text}"
    await update.message.reply_text(text, reply_markup=main_menu(chat_id))

# ---------------- Оценка поездки ----------------
async def rate_ride(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id=update.message.chat.id
    user_state[chat_id]={"step":"rating"}
    await update.message.reply_text("Введите ID поездки и рейтинг 1-5 через пробел, например: 7 5")

async def handle_rating_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id=update.message.chat.id
    state=user_state.get(chat_id,{})
    if state.get("step")=="rating":
        parts=update.message.text.split()
        if len(parts)==2 and parts[0].isdigit() and parts[1].isdigit():
            ride_id,rating=int(parts[0]),int(parts[1])
            if 1<=rating<=5:
                cursor.execute("INSERT INTO ratings (ride_id,user_id,rating) VALUES (?,?,?)",(ride_id,chat_id,rating))
                conn.commit()
                await update.message.reply_text("⭐ Спасибо за оценку!", reply_markup=main_menu(chat_id))
                user_state.pop(chat_id)
            else:
                await update.message.reply_text("Введите рейтинг от 1 до 5")
        else:
            await update.message.reply_text("Формат: ID рейтинг, например: 7 5")

# ---------------- Жалобы ----------------
async def report_ride(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id=update.message.chat.id
    user_state[chat_id]={"step":"report"}
    await update.message.reply_text("Введите ID поездки и причину через пробел, например: 7 мошенник")

async def handle_report_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id=update.message.chat.id
    state=user_state.get(chat_id,{})
    if state.get("step")=="report":
        parts=update.message.text.split()
        if len(parts)>=2:
            ride_id=int(parts[0])
            reason=" ".join(parts[1:])
            cursor.execute("INSERT INTO reports (ride_id, reporter_id, reason) VALUES (?,?,?)",(ride_id,chat_id,reason))
            conn.commit()
            await update.message.reply_text("✅ Жалоба отправлена администратору", reply_markup=main_menu(chat_id))
            # уведомление админу
            await context.bot.send_message(ADMIN_ID,f"🚨 Жалоба на поездку {ride_id} от @{update.message.from_user.username}: {reason}")
            user_state.pop(chat_id)
# ---------------- Админка ----------------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id=update.callback_query.from_user.id
    if chat_id!=ADMIN_ID:
        await update.callback_query.answer("❌ Доступно только админу")
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Все поездки", callback_data="admin_rides")],
        [InlineKeyboardButton("🚨 Жалобы", callback_data="admin_reports")],
        [InlineKeyboardButton("🚫 Бан/Разбан", callback_data="admin_ban")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="menu")]
    ])
    await update.callback_query.edit_message_text("👑 Админ-панель", reply_markup=kb)

# Просмотр всех поездок
async def admin_all_rides(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rides = cursor.execute("SELECT * FROM rides ORDER BY id DESC").fetchall()
    if not rides:
        text="🚫 Нет поездок"
    else:
        text="\n\n".join([f"ID {r[0]}: {r[2]} {r[3]} {r[4]} мест, занято {r[5]}" for r in rides])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin")]
    ]))

# Просмотр жалоб
async def admin_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reports = cursor.execute("SELECT * FROM reports ORDER BY id DESC").fetchall()
    if not reports:
        text="🚫 Жалоб нет"
    else:
        text="\n\n".join([f"ID {r[0]}: Поездка {r[1]}, от {r[2]}, причина: {r[3]}" for r in reports])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin")]
    ]))

# Бан/разбан пользователей
banned_users = set()
async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text="Введите ID пользователя для бана/разбана через пробел: ID бан/разбан"
    user_state[ADMIN_ID]={"step":"ban"}
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin")]
    ]))

async def handle_admin_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id=update.message.chat.id
    if chat_id!=ADMIN_ID:
        return
    state=user_state.get(chat_id, {})
    if state.get("step")=="ban":
        parts=update.message.text.split()
        if len(parts)==2 and parts[0].isdigit():
            uid=int(parts[0])
            action=parts[1].lower()
            if action=="бан":
                banned_users.add(uid)
                await update.message.reply_text(f"✅ Пользователь {uid} заблокирован")
            elif action=="разбан":
                banned_users.discard(uid)
                await update.message.reply_text(f"✅ Пользователь {uid} разблокирован")
            else:
                await update.message.reply_text("❌ Действие: бан или разбан")
        else:
            await update.message.reply_text("❌ Формат: ID бан/разбан")
        user_state.pop(chat_id)

# ---------------- Регистрация всех хендлеров ----------------
def register_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_message))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_rating_msg))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_report_msg))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), skip_photo))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_admin_msg))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("rate", rate_ride))
    app.add_handler(CommandHandler("report", report_ride))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin$"))
    app.add_handler(CallbackQueryHandler(admin_all_rides, pattern="^admin_rides$"))
    app.add_handler(CallbackQueryHandler(admin_reports, pattern="^admin_reports$"))
    app.add_handler(CallbackQueryHandler(admin_ban, pattern="^admin_ban$"))

# ---------------- Запуск ----------------
if __name__=="__main__":
    threading.Thread(target=run_web).start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    register_handlers(app)
    print("✅ Бот запущен")
    app.bot.delete_webhook(drop_pending_updates=True)
    app.run_polling(close_loop=False)
