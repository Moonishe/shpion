import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats

from bot.config import BOT_TOKEN
from bot.models.database import init_db, get_all_active_sessions, cleanup_stale_sessions
from bot.handlers import group, private
from bot.services.lobby_service import restore_session

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO)


# Команды для личных сообщений
PRIVATE_COMMANDS = [
    BotCommand(command="start", description="🎭 Начать работу с ботом"),
    BotCommand(command="help", description="❓ Помощь и команды"),
    BotCommand(command="guess", description="🎯 Угадать персонажа (для шпиона)"),
    BotCommand(command="hint", description="💡 Получить подсказку (для шпиона)"),
    BotCommand(command="send", description="💌 Написать тайное письмо"),
    BotCommand(command="mystats", description="📊 Моя статистика"),
    BotCommand(command="version", description="ℹ️ Версия бота"),
]

# Команды для групп
GROUP_COMMANDS = [
    BotCommand(command="spy", description="🎮 Создать новую игру"),
    BotCommand(command="join", description="👥 Присоединиться к игре"),
    BotCommand(command="vote", description="🗳️ Начать голосование"),
    BotCommand(command="stop", description="🛑 Остановить игру"),
    BotCommand(command="status", description="📋 Статус текущей игры"),
    BotCommand(command="players", description="👥 Список игроков"),
    BotCommand(command="kick", description="👢 Исключить игрока"),
    BotCommand(command="addchar", description="✨ Добавить персонажа"),
    BotCommand(command="delchar", description="🗑️ Удалить персонажа"),
    BotCommand(command="listchars", description="📋 Список кастомных персонажей"),
    BotCommand(command="help", description="❓ Помощь и правила"),
    BotCommand(command="reroll", description="🔄 Перевыбрать персонажа"),
    BotCommand(command="version", description="ℹ️ Версия бота"),
]


async def set_bot_commands(bot: Bot):
    """Устанавливает команды бота для меню с таймаутом."""
    try:
        await asyncio.wait_for(
            bot.set_my_commands(PRIVATE_COMMANDS, scope=BotCommandScopeAllPrivateChats()),
            timeout=10
        )
        await asyncio.wait_for(
            bot.set_my_commands(GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats()),
            timeout=10
        )
        logging.info("Команды бота установлены.")
    except asyncio.TimeoutError:
        logging.warning("Таймаут при установке команд (нет интернета?). Продолжаю...")
    except Exception as e:
        logging.warning("Не удалось установить команды: %s. Продолжаю...", e)


def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(private.router)
    dp.include_router(group.router)

    async def on_startup():
        await init_db()
        await set_bot_commands(bot)
        await private.init_started_users()
        # Восстанавливаем активные сессии из БД
        try:
            active = await get_all_active_sessions()
            for chat_id in active:
                try:
                    s = await restore_session(chat_id)
                    if s:
                        logger.info("Восстановлена сессия для чата %d (состояние: %s)", chat_id, s.state.value)
                except Exception as e:
                    logger.warning("Не удалось восстановить сессию %d: %s", chat_id, e)
            logger.info("Бот запущен. Восстановлено %d сессий.", len(active))
        except Exception as e:
            logger.warning("Не удалось загрузить активные сессии: %s", e)

    async def cleanup_loop():
        """Фоновая задача: очистка старых сессий каждые 15 минут."""
        while True:
            await asyncio.sleep(900)
            try:
                await cleanup_stale_sessions(max_age=7200)
            except Exception as e:
                logger.warning("Ошибка при очистке сессий: %s", e)

    async def start():
        await on_startup()
        cleanup_task = asyncio.create_task(cleanup_loop())
        try:
            await dp.start_polling(bot)
        finally:
            cleanup_task.cancel()
            await bot.session.close()

    try:
        asyncio.run(start())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем.")


if __name__ == "__main__":
    main()
