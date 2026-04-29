import asyncio
import logging
import os
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.types import Update
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 8000))
DB_NAME = "shop.db"

if not API_TOKEN:
    raise ValueError("Токен бота не найден в переменных окружения!")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

async def db_start():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER UNIQUE)")
        await db.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, price TEXT, description TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product_id INTEGER, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        
        cursor = await db.execute("SELECT COUNT(*) FROM products")
        count = (await cursor.fetchone())[0]
        if count == 0:
            await db.execute("INSERT INTO products (name, price, description) VALUES (?, ?, ?)", 
                             ("Spotify Premium", "299 руб", "Музыка без рекламы"))
            await db.execute("INSERT INTO products (name, price, description) VALUES (?, ?, ?)", 
                             ("Discord Nitro", "499 руб", "Расширенные функции"))
            await db.commit()

async def add_user(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            await db.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
            await db.commit()
        except aiosqlite.IntegrityError:
            pass

async def get_products():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM products")
        return await cursor.fetchall()

async def get_product_by_id(product_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM products WHERE id=?", (product_id,))
        return await cursor.fetchone()

async def create_order(user_id, product_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO orders (user_id, product_id) VALUES (?, ?)", (user_id, product_id))
        await db.commit()

def get_main_keyboard():
    kb = ReplyKeyboardBuilder()
    kb.add(KeyboardButton(text="📦 Каталог"))
    kb.adjust(1)
    return kb.as_markup(resize_keyboard=True)

def get_product_inline_keyboard(products):
    kb = InlineKeyboardBuilder()
    for product in products:
        kb.button(text=f"{product[1]} - {product[2]}", callback_data=f"product_{product[0]}")
    kb.adjust(1)
    return kb.as_markup()

def get_buy_keyboard(product_id):
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Купить", callback_data=f"buy_{product_id}")
    return kb.as_markup()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await add_user(message.from_user.id)
    await message.answer(f"Добро пожаловать, {message.from_user.full_name}!\nВыберите действие:", reply_markup=get_main_keyboard())

@dp.message(F.text == "📦 Каталог")
async def catalog_handler(message: types.Message):
    products = await get_products()
    if not products:
        await message.answer("Товары временно отсутствуют.")
        return
    kb = get_product_inline_keyboard(products)
    await message.answer("Выберите товар из списка:", reply_markup=kb)

@dp.callback_query(F.data.startswith("product_"))
async def product_callback(callback: types.CallbackQuery):
    product_id = int(callback.data.split("_")[1])
    product = await get_product_by_id(product_id)
    if product:
        text = f"<b>{product[1]}</b>\nЦена: {product[2]}\nОписание: {product[3]}"
        kb = get_buy_keyboard(product_id)
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await callback.answer("Товар не найден", show_alert=True)

@dp.callback_query(F.data.startswith("buy_"))
async def buy_callback(callback: types.CallbackQuery):
    product_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    await create_order(user_id, product_id)
    await callback.message.answer("✅ Покупка успешно оформлена! Менеджер свяжется с вами.")

async def on_startup():
    await bot.set_webhook(WEBHOOK_URL)

async def on_shutdown():
    await bot.delete_webhook()

async def handle_update(request: web.Request):
    update = Update(**await request.json())
    await dp.feed_update(bot, update)
    return web.Response(status=200)

async def main():
    await db_start()
    app = web.Application()
    app.router.add_post("/webhook", handle_update)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Бот запущен на порту {PORT}")
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")