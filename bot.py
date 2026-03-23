import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InputFile
from config import TOKEN, ADMIN_ID
import db

bot = Bot(token=TOKEN)
dp = Dispatcher()

db.init_db()

# --- КНОПКИ ---
def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🚗 Найти поездку", "➕ Предложить поездку")
    kb.add("📋 Мои объявления", "👤 Профиль")
    return kb

def routes_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Челны → Казань", "Казань → Челны")
    kb.add("⬅️ Назад")
    return kb

def seats_kb(max_seats):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    for i in range(1, max_seats+1):
        kb.add(str(i))
    kb.add("⬅️ Назад")
    return kb

def yes_no_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("✅ Да", "❌ Нет")
    return kb

# --- ПОЛЬЗОВАТЕЛЬСКИЕ ДАННЫЕ ---
user_data = {}
book_data = {}
report_data = {}

# --- СТАРТ ---
@dp.message(lambda msg: msg.text == "/start")
async def start(msg: types.Message):
    await msg.answer("🚗 Попутка Челны ↔ Казань", reply_markup=main_menu())

# --- ПРЕДЛОЖИТЬ ПОЕЗДКУ ---
@dp.message(lambda msg: msg.text == "➕ Предложить поездку")
async def create_ride(msg: types.Message):
    await msg.answer("Выберите маршрут:", reply_markup=routes_kb())

@dp.message(lambda msg: msg.text in ["Челны → Казань", "Казань → Челны"])
async def set_route(msg: types.Message):
    user_data[msg.from_user.id] = {"route": msg.text}
    await msg.answer("Введите время (например 18:00):")

@dp.message()
async def handle_input(msg: types.Message):
    user = user_data.get(msg.from_user.id)
    if not user:
        return

    if "time" not in user:
        user["time"] = msg.text
        await msg.answer("Сколько мест? (1-4)", reply_markup=seats_kb(4))
        return

    if "seats" not in user:
        try:
            seats = int(msg.text)
            if seats <1 or seats>4:
                await msg.answer("Введите число от 1 до 4")
                return
            user["seats"] = seats
            await msg.answer("Введите цену (или 'договорная'):")
        except:
            await msg.answer("Введите число")
        return

    if "price" not in user:
        user["price"] = msg.text
        await msg.answer("Можно прикрепить фото авто/себя. Отправьте или пропустите командой /skip")
        return

# --- Фото ---
@dp.message(lambda msg: msg.photo)
async def handle_photo(msg: types.Message):
    user = user_data.get(msg.from_user.id)
    if user and "price" in user and "photo" not in user:
        file_id = msg.photo[-1].file_id
        user["photo"] = file_id
        # сохраняем объявление
        db.cursor.execute("""
        INSERT INTO rides (user_id, route, time, seats_total, price, photo)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            msg.from_user.id,
            user["route"],
            user["time"],
            user["seats"],
            user["price"],
            file_id
        ))
        db.conn.commit()
        await msg.answer("✅ Объявление создано!", reply_markup=main_menu())
        user_data.pop(msg.from_user.id)

# Пропустить фото
@dp.message(lambda msg: msg.text == "/skip")
async def skip_photo(msg: types.Message):
    user = user_data.get(msg.from_user.id)
    if user and "price" in user:
        db.cursor.execute("""
        INSERT INTO rides (user_id, route, time, seats_total, price)
        VALUES (?, ?, ?, ?, ?)
        """, (
            msg.from_user.id,
            user["route"],
            user["time"],
            user["seats"],
            user["price"]
        ))
        db.conn.commit()
        await msg.answer("✅ Объявление создано!", reply_markup=main_menu())
        user_data.pop(msg.from_user.id)

# --- ПОИСК ---
@dp.message(lambda msg: msg.text == "🚗 Найти поездку")
async def find_rides(msg: types.Message):
    db.cursor.execute("SELECT * FROM rides ORDER BY id DESC LIMIT 10")
    rides = db.cursor.fetchall()
    if not rides:
        await msg.answer("Поездок пока нет")
        return
    for r in rides:
        text = f"🚗 {r[2]}\n🕒 {r[3]}\n💺 {r[5]}/{r[4]}\n💰 {r[6]}"
        if r[7]:
            await bot.send_photo(msg.from_user.id, r[7], caption=text)
        else:
            await msg.answer(text)
        # Добавляем кнопку для брони
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(f"💺 Забронировать {r[0]}")
        await msg.answer("Забронировать?", reply_markup=kb)

# --- БРОНИРОВАНИЕ ---
@dp.message(lambda msg: msg.text.startswith("💺 Забронировать"))
async def book_seat(msg: types.Message):
    ride_id = int(msg.text.split()[-1])
    db.cursor.execute("SELECT seats_total, seats_taken, user_id FROM rides WHERE id=?", (ride_id,))
    ride = db.cursor.fetchone()
    if not ride:
        await msg.answer("Ошибка")
        return
    seats_total, seats_taken, driver_id = ride
    if seats_taken >= seats_total:
        await msg.answer("❌ Все места заняты")
        return
    # увеличиваем количество занятых мест
    db.cursor.execute("UPDATE rides SET seats_taken = seats_taken+1 WHERE id=?", (ride_id,))
    db.conn.commit()
    await msg.answer("✅ Вы забронировали место!")
    # уведомление водителю
    await bot.send_message(driver_id, f"💬 @{msg.from_user.username} забронировал(-а) у вас место в поездке {ride_id}")

# --- ОЦЕНКА ПОСЛЕ ПОЕЗДКИ ---
@dp.message(lambda msg: msg.text == "⭐ Оценить поездку")
async def rate(msg: types.Message):
    await msg.answer("Введите ID поездки и рейтинг 1-5 через пробел, например: 7 5")

@dp.message()
async def handle_rating(msg: types.Message):
    if msg.text.count(" ") == 1 and msg.text.split()[0].isdigit() and msg.text.split()[1].isdigit():
        ride_id, rating = map(int, msg.text.split())
        if 1 <= rating <= 5:
            db.cursor.execute("INSERT INTO ratings (ride_id, user_id, rating) VALUES (?, ?, ?)", (ride_id, msg.from_user.id, rating))
            db.conn.commit()
            await msg.answer("⭐ Спасибо за оценку!")
        else:
            await msg.answer("Введите рейтинг от 1 до 5")

# --- ЖАЛОБЫ ---
@dp.message(lambda msg: msg.text == "🚨 Пожаловаться")
async def report(msg: types.Message):
    await msg.answer("Введите ID поездки и причину через пробел, например: 7 мошенник")

@dp.message()
async def handle_report(msg: types.Message):
    if msg.text.count(" ") >=1:
        parts = msg.text.split()
        ride_id = int(parts[0])
        reason = " ".join(parts[1:])
        db.cursor.execute("INSERT INTO reports (ride_id, reporter_id, reason) VALUES (?, ?, ?)", (ride_id, msg.from_user.id, reason))
        db.conn.commit()
        await msg.answer("✅ Жалоба отправлена администратору")
        # уведомление админу
        await bot.send_message(ADMIN_ID, f"🚨 Жалоба на поездку {ride_id} от @{msg.from_user.username}: {reason}")

# --- АДМИН ---
@dp.message(lambda msg: msg.from_user.id == ADMIN_ID)
async def admin_panel(msg: types.Message):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("📋 Все объявления", "🚫 Бан/Разбан")
    await msg.answer("👑 Админ-панель", reply_markup=kb)

# --- МОЙ ПРОФИЛЬ ---
@dp.message(lambda msg: msg.text == "👤 Профиль")
async def profile(msg: types.Message):
    db.cursor.execute("SELECT AVG(rating) FROM ratings WHERE user_id=?", (msg.from_user.id,))
    rating = db.cursor.fetchone()[0]
    rating = round(rating,1) if rating else 0
    await msg.answer(f"⭐ Ваш рейтинг: {rating}")

# --- МОИ ОБЪЯВЛЕНИЯ ---
@dp.message(lambda msg: msg.text == "📋 Мои объявления")
async def my_rides(msg: types.Message):
    db.cursor.execute("SELECT * FROM rides WHERE user_id=? ORDER BY id DESC", (msg.from_user.id,))
    rides = db.cursor.fetchall()
    if not rides:
        await msg.answer("У вас пока нет объявлений")
        return
    for r in rides:
        text = f"🚗 {r[2]} 🕒 {r[3]} 💺 {r[5]}/{r[4]} 💰 {r[6]} (ID {r[0]})"
        await msg.answer(text)

# --- ЗАПУСК ---
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
