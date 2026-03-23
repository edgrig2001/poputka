import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from config import TOKEN, ADMIN_ID
import db

bot = Bot(token=TOKEN)
dp = Dispatcher()

db.init_db()

# --- КНОПКИ ---

def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🚗 Найти поездку", "➕ Предложить поездку")
    kb.add("📋 Мои объявления")
    return kb

def routes_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Челны → Казань", "Казань → Челны")
    kb.add("⬅️ Назад")
    return kb

# --- СТАРТ ---

@dp.message(lambda msg: msg.text == "/start")
async def start(msg: types.Message):
    await msg.answer("🚗 Попутка Челны ↔ Казань", reply_markup=main_menu())

# --- ПРЕДЛОЖИТЬ ПОЕЗДКУ ---

user_data = {}

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

    if user and "time" not in user:
        user["time"] = msg.text
        await msg.answer("Сколько мест? (1-4)")
        return

    if user and "seats" not in user:
        user["seats"] = int(msg.text)
        await msg.answer("Цена? (или 'договорная')")
        return

    if user and "price" not in user:
        user["price"] = msg.text

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
async def find(msg: types.Message):
    db.cursor.execute("SELECT * FROM rides ORDER BY id DESC LIMIT 5")
    rides = db.cursor.fetchall()

    if not rides:
        await msg.answer("Нет поездок")
        return

    for r in rides:
        text = f"""
🚗 {r[2]}
🕒 {r[3]}
💺 {r[5]}/{r[4]}
💰 {r[6]}
        """
        await msg.answer(text)

# --- ЗАПУСК ---

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())