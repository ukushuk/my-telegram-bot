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
from aiogram.types import Message, BotCommand

from keep_alive import keep_alive

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
DB_PATH = Path("bot_data.sqlite3")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

class BroadcastStates(StatesGroup):
    waiting_for_content = State()

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS forwarded_messages (user_id INTEGER, created_at INTEGER DEFAULT (strftime('%s','now')))")
        conn.execute("CREATE TABLE IF NOT EXISTS blocked_users (user_id INTEGER PRIMARY KEY, blocked_at INTEGER DEFAULT (strftime('%s','now')))")
        conn.commit()

def is_blocked(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("SELECT 1 FROM blocked_users WHERE user_id = ?", (user_id,)).fetchone() is not None

# Функция для безопасного извлечения ID из инфо-карточки
def extract_user_id(text: str) -> int:
    for line in text.split("\n"):
        if line.startswith("ID:"):
            return int(line.replace("ID:", "").strip())
    raise ValueError("ID не найден в тексте")

@dp.message(Command("start"), F.from_user.id == ADMIN_ID)
async def admin_start(message: Message):
    await message.answer("🛠 <b>Панель администратора включена.</b>\nВведите /help для списка команд.")

@dp.message(Command("help"), F.from_user.id == ADMIN_ID)
async def admin_help(message: Message):
    await message.answer(
        "📣 /broadcast — Рассылка всем\n"
        "📊 /stats — Статистика и ТОП\n"
        "🚫 /block [id] — Забанить (или Reply на сообщение)\n"
        "✅ /unblock [id] — Разбанить\n"
        "📋 /blocked — Список банов\n"
        "✖️ /cancel — Отмена рассылки\n\n"
        "Чтобы ответить пользователю — просто сделайте <b>Reply</b> на сообщение-карточку с его ID."
    )

@dp.message(Command("stats"), F.from_user.id == ADMIN_ID)
async def admin_stats(message: Message):
    with sqlite3.connect(DB_PATH) as conn:
        total = conn.execute("SELECT COUNT(*) FROM forwarded_messages").fetchone()
        unique = conn.execute("SELECT COUNT(DISTINCT user_id) FROM forwarded_messages").fetchone()
        top = conn.execute("SELECT user_id, COUNT(*) as c FROM forwarded_messages GROUP BY user_id ORDER BY c DESC LIMIT 5").fetchall()
    
    top_text = "\n".join([f"👤 {u}: {u} сообщ." for u in top])
    await message.answer(f"📊 <b>Статистика:</b>\nВсего сообщений: {total[0] if total else 0}\nЛюдей: {unique[0] if unique else 0}\n\n<b>ТОП 5:</b>\n{top_text}")

@dp.message(Command("block"), F.from_user.id == ADMIN_ID)
async def admin_block(message: Message):
    uid = None
    if message.reply_to_message:
        try:
            reply_text = message.reply_to_message.text or message.reply_to_message.caption or ""
            uid = extract_user_id(reply_text)
        except: pass
    elif len(message.text.split()) > 1:
        try: uid = int(message.text.split()[1])
        except: pass
    
    if uid:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("INSERT OR IGNORE INTO blocked_users (user_id) VALUES (?)", (uid,))
        await message.answer(f"🚫 Пользователь {uid} заблокирован.")
    else:
        await message.answer("Укажите ID или ответьте на сообщение-карточку пользователя.")

@dp.message(Command("unblock"), F.from_user.id == ADMIN_ID)
async def admin_unblock(message: Message):
    try:
        uid = int(message.text.split()[1])
        with sqlite3.connect(DB_PATH) as conn:
            conn.
[08.08.2026 23:22] ゛: execute("DELETE FROM blocked_users WHERE user_id = ?", (uid,))
        await message.answer(f"✅ Пользователь {uid} разблокирован.")
    except:
        await message.answer("Пример: /unblock 12345678")

@dp.message(Command("blocked"), F.from_user.id == ADMIN_ID)
async def admin_blocked_list(message: Message):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT user_id FROM blocked_users").fetchall()
    text = "\n".join([f"• {r[0]}" for r in rows]) if rows else "Список пуст."
    await message.answer(f"📋 <b>Заблокированы:</b>\n{text}")

@dp.message(Command("cancel"), F.from_user.id == ADMIN_ID)
async def admin_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("✖️ Действие отменено.")

@dp.message(Command("broadcast"), F.from_user.id == ADMIN_ID)
async def admin_broad(message: Message, state: FSMContext):
    await message.answer("Введите сообщение для рассылки (это может быть текст, фото, стикер или любое медиа):")
    await state.set_state(BroadcastStates.waiting_for_content)

@dp.message(BroadcastStates.waiting_for_content, F.from_user.id == ADMIN_ID)
async def admin_broad_send(message: Message, state: FSMContext):
    with sqlite3.connect(DB_PATH) as conn:
        users = conn.execute("SELECT DISTINCT user_id FROM forwarded_messages").fetchall()
    count = 0
    for (uid,) in users:
        try:
            await message.send_copy(chat_id=uid)
            count += 1
        except: pass
    await message.answer(f"✅ Рассылка завершена. Отправлено: {count}")
    await state.clear()

@dp.message(CommandStart())
async def user_start(message: Message):
    await message.answer("━━━━━━━━━━━━━\n° 𝔠𝔩𝔞𝔴 𝔫𝔬𝔦𝔯\n━━━━━━━━━━━━━━\n\n— Приветствую. Что тебя сюда занесло?)")

@dp.message(F.chat.type == "private")
async def handle_private(message: Message):
    # Если пишет АДМИНИСТРАТОР
    if message.from_user.id == ADMIN_ID:
        if message.reply_to_message:
            try:
                reply_text = message.reply_to_message.text or message.reply_to_message.caption or ""
                target_id = extract_user_id(reply_text)
                
                await message.send_copy(chat_id=target_id)
                await message.answer("✅ Ответ отправлен.")
            except Exception as e:
                await message.answer("❌ Ошибка: Сделайте Reply именно на инфо-карточку, где написан ID пользователя.")
        return

    # Если пишет обычный ПОЛЬЗОВАТЕЛЬ
    if is_blocked(message.from_user.id):
        return

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO forwarded_messages (user_id) VALUES (?)", (message.from_user.id,))
        conn.commit()

    # Сначала бот шлет инфо-карточку
    info_text = (
        f"📩 <b>Новое сообщение</b>\n"
        f"От: {message.from_user.full_name}\n"
        f"ID:{message.from_user.id}\n"
        f"---------------------------"
    )
    await bot.send_message(chat_id=ADMIN_ID, text=info_text)
    
    # Следом бот пересылает само медиа (фото, голос, стикер, видео)
    await message.send_copy(chat_id=ADMIN_ID)

async def main():
    init_db()
    keep_alive()
    await dp.start_polling(bot)

if name == "__main__":
    asyncio.run(main())
