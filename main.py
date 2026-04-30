import asyncio
import logging
import os
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.types import Update
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 10000))
DB_NAME = "shop.db"

if not API_TOKEN:
    raise ValueError("Токен бота не найден в переменных окружения!")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

class ProductState(StatesGroup):
    selecting_category = State()
    selecting_service = State()
    selecting_period = State()
    confirming_purchase = State()

async def db_start():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER UNIQUE, balance REAL DEFAULT 0.0)")
        await db.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, category TEXT, price TEXT, description TEXT, service_type TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product_id INTEGER, period TEXT, amount REAL, status TEXT DEFAULT 'completed', date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        
        cursor = await db.execute("SELECT COUNT(*) FROM products")
        count = (await cursor.fetchone())[0]
        if count == 0:
            services = [
                ("Spotify Premium", "foreign_services", "299", "Музыка без рекламы", "3 месяца"),
                ("Spotify Premium", "foreign_services", "549", "Музыка без рекламы", "6 месяцев"),
                ("Spotify Premium", "foreign_services", "999", "Музыка без рекламы", "12 месяцев"),
                ("YouTube Premium", "foreign_services", "349", "Видео без рекламы", "3 месяца"),
                ("YouTube Premium", "foreign_services", "649", "Видео без рекламы", "6 месяцев"),
                ("YouTube Premium", "foreign_services", "1199", "Видео без рекламы", "12 месяцев"),
                ("Discord Nitro", "foreign_services", "499", "Расширенные функции", "3 месяца"),
                ("Discord Nitro", "foreign_services", "899", "Расширенные функции", "6 месяцев"),
                ("Discord Nitro", "foreign_services", "1599", "Расширенные функции", "12 месяцев"),
                ("Steam Gift Card $10", "gift_cards", "750", "Пополнение аккаунта Steam", None),
                ("Steam Gift Card $25", "gift_cards", "1850", "Пополнение аккаунта Steam", None),
                ("Steam Gift Card $50", "gift_cards", "3650", "Пополнение аккаунта Steam", None),
                ("Genshin Impact 600 Genesis", "game_donations", "450", "Валюта для игры", None),
                ("Genshin Impact 1980 Genesis", "game_donations", "1450", "Валюта для игры", None),
                ("Genshin Impact 3280 Genesis", "game_donations", "2350", "Валюта для игры", None),
                ("PUBG Mobile 60 UC", "game_donations", "89", "Валюта для игры", None),
                ("PUBG Mobile 325 UC", "game_donations", "449", "Валюта для игры", None),
                ("PUBG Mobile 660 UC", "game_donations", "899", "Валюта для игры", None),
            ]
            for name, category, price, desc, period in services:
                await db.execute("INSERT INTO products (name, category, price, description, service_type) VALUES (?, ?, ?, ?, ?)", (name, category, price, desc, period))
            await db.commit()

async def add_user(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            await db.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
            await db.commit()
        except aiosqlite.IntegrityError:
            pass

async def get_products_by_category(category):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM products WHERE category=?", (category,))
        return await cursor.fetchall()

async def get_product_by_id(product_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM products WHERE id=?", (product_id,))
        return await cursor.fetchone()

async def create_order(user_id, product_id, period, amount):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO orders (user_id, product_id, period, amount) VALUES (?, ?, ?, ?)", (user_id, product_id, period, amount))
        await db.commit()

async def get_user_orders(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT o.id, p.name, o.period, o.amount, o.date FROM orders o JOIN products p ON o.product_id = p.id WHERE o.user_id=? ORDER BY o.date DESC", (user_id,))
        return await cursor.fetchall()

def get_main_keyboard():
    kb = ReplyKeyboardBuilder()
    kb.add(KeyboardButton(text="📦 Каталог товаров"))
    kb.add(KeyboardButton(text="ℹ️ О нас"))
    kb.add(KeyboardButton(text="🆘 Поддержка"))
    kb.add(KeyboardButton(text="💰 Пополнение баланса"))
    kb.add(KeyboardButton(text="👤 Личный кабинет"))
    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)

def get_catalog_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="🌍 Зарубежные сервисы", callback_data="cat_foreign")
    kb.button(text="🎁 Подарочные карты", callback_data="cat_gifts")
    kb.button(text="🎮 Донат в игры", callback_data="cat_games")
    kb.button(text="🔙 Назад", callback_data="main_menu")
    kb.adjust(1)
    return kb.as_markup()

def get_services_keyboard(category):
    products = get_products_by_category_sync(category)
    kb = InlineKeyboardBuilder()
    seen = set()
    for prod in products:
        name = prod[1]
        if name not in seen:
            kb.button(text=name, callback_data=f"svc_{prod[0]}")
            seen.add(name)
    kb.button(text="🔙 Назад", callback_data="catalog")
    kb.adjust(1)
    return kb.as_markup()

def get_periods_keyboard(service_name):
    products = get_products_by_category_sync("foreign_services")
    kb = InlineKeyboardBuilder()
    for prod in products:
        if prod[1] == service_name and prod[5]:
            kb.button(text=f"{prod[5]} — {prod[3]} ₽", callback_data=f"per_{prod[0]}")
    kb.button(text="🔙 Назад", callback_data="foreign_services")
    kb.adjust(1)
    return kb.as_markup()

def get_gifts_keyboard():
    products = get_products_by_category_sync("gift_cards")
    kb = InlineKeyboardBuilder()
    for prod in products:
        kb.button(text=f"{prod[1]} — {prod[3]} ₽", callback_data=f"buy_{prod[0]}_gift")
    kb.button(text="🔙 Назад", callback_data="catalog")
    kb.adjust(1)
    return kb.as_markup()

def get_games_keyboard():
    products = get_products_by_category_sync("game_donations")
    kb = InlineKeyboardBuilder()
    for prod in products:
        kb.button(text=f"{prod[1]} — {prod[3]} ₽", callback_data=f"buy_{prod[0]}_game")
    kb.button(text="🔙 Назад", callback_data="catalog")
    kb.adjust(1)
    return kb.as_markup()

def get_buy_keyboard(product_id, period=None, amount=None):
    kb = InlineKeyboardBuilder()
    callback = f"confirm_{product_id}_{period}_{amount}" if period else f"confirm_{product_id}_none_{amount}"
    kb.button(text="💳 Купить", callback_data=callback)
    kb.button(text="🔙 Назад", callback_data="back_catalog")
    kb.adjust(1)
    return kb.as_markup()

def get_products_by_category_sync(category):
    import sqlite3
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.execute("SELECT * FROM products WHERE category=?", (category,))
    result = cursor.fetchall()
    conn.close()
    return result

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await add_user(message.from_user.id)
    await message.answer(f"Добро пожаловать, {message.from_user.full_name}!\nВыберите раздел:", reply_markup=get_main_keyboard())

@dp.message(F.text == "📦 Каталог товаров")
async def catalog_handler(message: types.Message):
    await message.answer("Выберите категорию:", reply_markup=get_catalog_keyboard())

@dp.message(F.text == "ℹ️ О нас")
async def about_handler(message: types.Message):
    text = "🤖 <b>О боте</b>\n\nЭтот бот был создан в качестве прототипа для дипломной работы студента Колледжа АлтГУ.\nГод создания: 2026.\nБот предназначен для автоматизации продажи цифровых товаров и подписок через мессенджер Telegram."
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "🆘 Поддержка")
async def support_handler(message: types.Message):
    await message.answer("По всем вопросам обращаться @drugsober")

@dp.message(F.text == "💰 Пополнение баланса")
async def topup_handler(message: types.Message):
    await message.answer("⚠️ <b>Раздел в разработке</b>\n\nФункция пополнения баланса будет доступна в следующих обновлениях бота.", parse_mode="HTML")

@dp.message(F.text == "👤 Личный кабинет")
async def profile_handler(message: types.Message):
    orders = await get_user_orders(message.from_user.id)
    if not orders:
        text = "👤 <b>Личный кабинет</b>\n\nУ вас пока нет завершённых заказов.\n💰 Баланс: 0.00 ₽\n<em>Пополнение баланса — в разработке</em>"
    else:
        text = "👤 <b>Личный кабинет</b>\n\n<b>Завершённые заказы:</b>\n"
        for order in orders:
            text += f"• {order[1]} | {order[2] or '—'} | {order[3]} ₽ | {order[4][:10]}\n"
        text += f"\n💰 Баланс: 0.00 ₽\n<em>Пополнение баланса — в разработке</em>"
    await message.answer(text, parse_mode="HTML")

@dp.callback_query(F.data == "main_menu")
async def back_to_main(callback: types.CallbackQuery):
    await callback.message.edit_text("Выберите раздел:", reply_markup=get_main_keyboard())

@dp.callback_query(F.data == "catalog")
async def back_to_catalog(callback: types.CallbackQuery):
    await callback.message.edit_text("Выберите категорию:", reply_markup=get_catalog_keyboard())

@dp.callback_query(F.data == "cat_foreign")
async def foreign_services(callback: types.CallbackQuery):
    kb = get_services_keyboard("foreign_services")
    await callback.message.edit_text("🌍 <b>Зарубежные сервисы</b>\n\nВыберите сервис для оплаты подписки:", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "cat_gifts")
async def gift_cards(callback: types.CallbackQuery):
    kb = get_gifts_keyboard()
    await callback.message.edit_text("🎁 <b>Подарочные карты</b>\n\nВыберите карту для покупки:", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "cat_games")
async def game_donations(callback: types.CallbackQuery):
    kb = get_games_keyboard()
    await callback.message.edit_text("🎮 <b>Донат в игры</b>\n\nВыберите игру для пополнения:", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("svc_"))
async def select_service(callback: types.CallbackQuery):
    product_id = int(callback.data.split("_")[1])
    product = await get_product_by_id(product_id)
    if product:
        kb = get_periods_keyboard(product[1])
        text = f"<b>{product[1]}</b>\n{product[4]}\n\nВыберите период подписки:"
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("per_"))
async def select_period(callback: types.CallbackQuery):
    product_id = int(callback.data.split("_")[1])
    product = await get_product_by_id(product_id)
    if product:
        kb = get_buy_keyboard(product_id, product[5], product[3])
        text = f"<b>{product[1]}</b>\nПериод: {product[5]}\nЦена: {product[3]} ₽\n{product[4]}\n\nПодтвердите покупку:"
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("buy_") and ("_gift" in callback.data or "_game" in callback.data))
async def buy_direct(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    product_id = int(parts[1])
    product = await get_product_by_id(product_id)
    if product:
        kb = get_buy_keyboard(product_id, None, product[3])
        text = f"<b>{product[1]}</b>\nЦена: {product[3]} ₽\n{product[4]}\n\nПодтвердите покупку:"
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("confirm_"))
async def confirm_purchase(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    product_id = int(parts[1])
    period = parts[2] if parts[2] != "none" else None
    amount = float(parts[3])
    user_id = callback.from_user.id
    
    await create_order(user_id, product_id, period, amount)
    
    product = await get_product_by_id(product_id)
    await callback.message.answer(f"✅ <b>Покупка оформлена!</b>\n\n{product[1]}\nПериод: {period or '—'}\nСумма: {amount} ₽\n\nМенеджер свяжется с вами в ближайшее время.", parse_mode="HTML")
    await callback.message.delete_reply_markup()

@dp.callback_query(F.data == "back_catalog")
async def back_to_catalog_from_buy(callback: types.CallbackQuery):
    await callback.message.edit_text("Выберите категорию:", reply_markup=get_catalog_keyboard())

async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)

async def on_shutdown(app):
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
