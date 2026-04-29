import asyncio
import logging
import os
import sqlite3
import sys
from pathlib import Path
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat, Message

from keep_alive import keep_alive

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("relay-bot")

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
DB_PATH = Path("bot_data.sqlite3")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

class BroadcastStates(StatesGroup):
    waiting_for_content = State()

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS forwarded_messages (admin_message_id INTEGER PRIMARY KEY, user_id INTEGER, created_at INTEGER DEFAULT (strftime('%s','now')))")
        conn.execute("CREATE TABLE IF NOT EXISTS blocked_users (user_id INTEGER PRIMARY KEY, blocked_at INTEGER DEFAULT (strftime('%s','now')))")
        conn.commit()

def is_blocked(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("SELECT 1 FROM blocked_users WHERE user_id = ?", (user_id,)).fetchone() is not None

def get_stats():
    with sqlite3.connect(DB_PATH) as conn:
        total = conn.execute("SELECT COUNT(*) FROM forwarded_messages").fetchone()[0]
        users = conn.execute("SELECT COUNT(DISTINCT user_id) FROM forwarded_messages").fetchone()[0]
        return f"📊 Статистика:\nВсего сообщений: {total}\nУникальных пользователей: {users}"

def get_broadcast_recipients():
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT DISTINCT user_id FROM forwarded_messages WHERE user_id != ?", (ADMIN_ID,)).fetchall()
    return [r[0] for r in rows]

@dp.message(Command("start"))
async def handle_start(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Привет, Админ! Ты можешь отвечать на сообщения пользователей, делая Reply на них.")
    else:
        await message.answer("━━━━━━━━━━━━━\n° 𝔠𝔩𝔞𝔴 𝔫𝔬𝔦𝔯\n━━━━━━━━━━━━━━\n\n— Приветствую. Что тебя сюда занесло?)")

@dp.message(Command("stats"), F.from_user.id == ADMIN_ID)
async def handle_stats(message: Message):
    await message.answer(get_stats())

@dp.message(Command("broadcast"), F.from_user.id == ADMIN_ID)
async def start_broadcast(message: Message, state: FSMContext):
    await message.answer("Введите текст или прикрепите фото для рассылки всем пользователям:")
    await state.set_state(BroadcastStates.waiting_for_content)

@dp.message(BroadcastStates.waiting_for_content, F.from_user.id == ADMIN_ID)
async def perform_broadcast(message: Message, state: FSMContext):
    users = get_broadcast_recipients()
    count = 0
    for user_id in users:
        try:
            await message.copy_to(chat_id=user_id)
            count += 1
        except Exception: pass
    await message.answer(f"📢 Рассылка завершена! Отправлено {count} пользователям.")
    await state.clear()

@dp.message(F.chat.type == "private")
async def handle_all(message: Message):
    # Если пишет админ (ответ на пересланное сообщение)
    if message.from_user.id == ADMIN_ID:
        if message.reply_to_message and message.reply_to_message.forward_from:
            user_id = message.reply_to_message.forward_from.id
            try:
                await message.copy_to(chat_id=user_id)
                await message.answer("✅ Ответ отправлен.")
            except Exception as e:
                await message.answer(f"❌ Ошибка: {e}")
        return

    # Если пишет обычный пользователь
    if is_blocked(message.from_user.id): return
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO forwarded_messages (user_id) VALUES (?)", (message.from_user.id,))
    
    await message.forward(ADMIN_ID)

async def main():
    init_db()
    keep_alive()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

