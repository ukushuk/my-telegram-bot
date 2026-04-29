import asyncio
import logging
import os
import sqlite3
import sys
from pathlib import Path
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    Message,
)

# Подключаем веб-сервер для поддержания жизни
from keep_alive import keep_alive

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("relay-bot")

# Получаем настройки из переменных окружения (нужно будет вписать в панели хостинга)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID_RAW = os.environ.get("ADMIN_ID")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")
if not ADMIN_ID_RAW:
    raise RuntimeError("ADMIN_ID is not set")

try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except ValueError as e:
    raise RuntimeError("ADMIN_ID must be an integer Telegram user ID") from e

DB_PATH = Path(os.environ.get("BOT_DB_PATH", "bot_data.sqlite3"))

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher(storage=MemoryStorage())

class BroadcastStates(StatesGroup):
    waiting_for_content = State()

def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS forwarded_messages (
                admin_message_id INTEGER PRIMARY KEY,
                user_id          INTEGER NOT NULL,
                created_at       INTEGER NOT NULL DEFAULT (strftime('%s','now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS blocked_users (
                user_id    INTEGER PRIMARY KEY,
                blocked_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
            )
            """
        )
        conn.commit()

def is_blocked(user_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT 1 FROM blocked_users WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row is not None

def block_user(user_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO blocked_users (user_id) VALUES (?)", (user_id,)
        )
        conn.commit()
        return cur.rowcount > 0

def unblock_user(user_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "DELETE FROM blocked_users WHERE user_id = ?", (user_id,)
        )
        conn.commit()
        return cur.rowcount > 0

def remember_forward(admin_message_id: int, user_id: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO forwarded_messages (admin_message_id, user_id) VALUES (?, ?)",
            (admin_message_id, user_id),
        )
        conn.commit()

def lookup_user_for_reply(admin_message_id: int) -> int | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT user_id FROM forwarded_messages WHERE admin_message_id = ?",
            (admin_message_id,),
        ).fetchone()
    return int(row[0]) if row else None

def get_broadcast_recipients() -> list[int]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT user_id
            FROM forwarded_messages
            WHERE user_id NOT IN (SELECT user_id FROM blocked_users)
              AND user_id != ?
            """,
            (ADMIN_ID,),
        ).fetchall()
    return [int(r[0]) for r in rows]

def get_stats() -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        res = conn.execute(
            """
            SELECT
                COUNT(*),
                COUNT(DISTINCT user_id),
                MAX(created_at)
            FROM forwarded_messages
            """
        ).fetchone()
        total, unique_users, last_ts = res
        today = conn.execute(
            "SELECT COUNT(*) FROM forwarded_messages "
            "WHERE created_at >= strftime('%s','now','-1 day')"
        ).fetchone()[0]
        week = conn.execute(
            "SELECT COUNT(*) FROM forwarded_messages "
            "WHERE created_at >= strftime('%s','now','-7 day')"
        ).fetchone()[0]
        top = conn.execute(
            """
            SELECT user_id, COUNT(*) AS c
            FROM forwarded_messages
            GROUP BY user_id
            ORDER BY c DESC
            LIMIT 5
            """
        ).fetchall()
    return {
        "total": total or 0,
        "unique_users": unique_users or 0,
        "last_ts": last_ts,
        "today": today or 0,
        "week": week or 0,
        "top": top,
    }

ADMIN_COMMANDS: list[BotCommand] = [
    BotCommand(command="broadcast", description="📣 Рассылка всем пользователям"),
    BotCommand(command="stats", description="📊 Статистика по сообщениям"),
    BotCommand(command="block", description="🚫 Заблокировать пользователя"),
    BotCommand(command="unblock", description="✅ Разблокировать пользователя"),
    BotCommand(command="blocked", description="📋 Список заблокированных"),
    BotCommand(command="cancel", description="✖️ Отменить текущее действие"),
    BotCommand(command="help", description="ℹ️ Список команд"),
    BotCommand(command="start", description="Приветствие"),
]

USER_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Связаться с администратором"),
    BotCommand(command="help", description="Как пользоваться ботом"),
]

async def setup_bot_commands() -> None:
    await bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeAllPrivateChats())
    await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=ADMIN_ID))

@dp.message(Command("help"))
async def handle_help(message: Message) -> None:
    if message.from_user is None:
        return
    if message.from_user.id == ADMIN_ID:
        text = (
            "<b>Команды администратора</b>\n"
            "/broadcast — рассылка сообщения всем пользователям\n"
            "/stats — статистика сообщений и топ пользователей\n"
            "/block [id] — заблокировать пользователя\n"
            "/unblock [id] — разблокировать пользователя\n"
            "/blocked — список заблокированных\n"
            "/cancel — отменить действие\n"
            "/help — это сообщение"
        )
    else:
        text = "Просто напишите сообщение — оно будет передано администратору."
    await message.answer(text)

@dp.message(CommandStart())
async def handle_start(message: Message) -> None:
    await message.answer("━━━━━━━━━━━━━\n° 𝔠𝔩𝔞𝔴 𝔫𝔬𝔦𝔯\n━━━━━━━━━━━━━━\n\n— Приветствую. Что тебя сюда занесло?)")

@dp.message(F.chat.type == "private")
async def handle_forward(message: Message) -> None:
    if message.from_user.id == ADMIN_ID:
        if message.reply_to_message and message.reply_to_message.forward_from:
             # Логика ответа админа (упрощенно для примера)
             pass
        return
    
    if is_blocked(message.from_user.id):
        return

    # Пересылаем админу
    await message.forward(ADMIN_ID)

async def main() -> None:
    init_db()
    await setup_bot_commands()
    # Запускаем веб-сервер
    keep_alive()
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
