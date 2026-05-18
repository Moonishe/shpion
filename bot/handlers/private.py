import asyncio
import html
import logging

from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from bot.models.game import Role, GameType, GameState
from bot.services import lobby_service
from bot.services.game_service import (
    check_victory, check_all_described, get_next_player,
    check_rate_limit, update_session_activity, record_stats
)
from bot.keyboards.inline import play_again_keyboard, i_said_keyboard, round_end_keyboard, host_confirm_keyboard
from bot.models.database import save_letter

logger = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type == "private")

_started_users: set[int] = set()


def is_user_started(user_id: int) -> bool:
    return user_id in _started_users


def get_unstarted(players) -> list[str]:
    return [p.full_name for p in players if p.user_id not in _started_users]


# ═══════════════════════════════════════════════════════════════
# 📱 ПРИВАТНЫЕ КОМАНДЫ
# ═══════════════════════════════════════════════════════════════

@router.message(Command("start"))
async def cmd_start_private(message: Message):
    """Приветствие в ЛС."""
    _started_users.add(message.from_user.id)
    await message.answer("""
🎭 <b>ШПИОН</b> — бот для игры

Добавь меня в группу, напиши /spy — и играйте!

🕵️ <b>Шпион:</b>
/guess Имя — угадать персонажа
/hint — подсказка (1 раз)

💌 <b>Письма:</b>
/send @username Текст — отправить (1 раз)

👤 Мирные знают персонажа
🕵️ Шпионы — нет, угадывают
🤡 Провокатор — знает фейкового

⚠️ Напиши /start до начала игры, чтобы получать роли!
""".strip())


@router.message(Command("guess"))
async def cmd_guess(message: Message, bot: Bot):
    """Попытка шпиона угадать персонажа."""
    user_id = message.from_user.id
    if not check_rate_limit(user_id, cooldown=2.0):
        await message.answer("⏳ Слишком часто. Подожди секунду.")
        return
    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        await message.answer(
            "📝 <code>/guess Имя</code>\nНапример: <code>/guess Гарри Поттер</code>"
        )
        return

    guess = args[1].strip()
    if not guess:
        await message.answer("❌ Напиши имя после /guess")
        return

    # Находим сессию, где пользователь — шпион
    session = None
    player = None
    for s in lobby_service.get_all_sessions():
        p = s.get_player(user_id)
        if p and p.role == Role.SPY:
            session = s
            player = p
            break

    if not session or not player:
        await message.answer(
            "🎭 Ты не в игре."
        )
        return

    if session.game_type == GameType.BLIND_SPY:
        await message.answer("🎭 Ты мирный, угадывать не нужно. Слушай описания.")
        return

    if player.role != Role.SPY:
        await message.answer("🎭 Ты мирный, угадывать не нужно. Слушай описания.")
        return

    session.spy_guess = guess
    await lobby_service.persist_session(session)
    result = check_victory(session)

    if result == "spy_guess":
        try:
            await record_stats(session, civilians_won=False, spy_guess=True)
        except Exception as e:
            logger.warning("Не удалось записать статистику: %s", e)

        await bot.send_message(session.chat_id, f"""
🕵️ <b>ШПИОН ПОБЕДИЛ!</b>

<b>{html.escape(message.from_user.full_name)}</b> угадал: <code>{html.escape(session.character)}</code>
""".strip(), reply_markup=play_again_keyboard())

        await message.answer("🎉 Ты угадал! Победа за шпионами!")
        # Отменяем таймер хода если был
        from bot.handlers.group import _cancel_turn_timer
        await _cancel_turn_timer(session.chat_id)
        await lobby_service.end_session(session.chat_id)
    elif result == "all_traitors_win":
        try:
            await record_stats(session, civilians_won=False, spy_guess=True)
        except Exception as e:
            logger.warning("Не удалось записать статистику: %s", e)

        await bot.send_message(session.chat_id, f"""
👿 <b>ПОБЕДИТЕЛЬ!</b>

<b>{html.escape(message.from_user.full_name)}</b> угадал первым: <code>{html.escape(session.character)}</code>
Все были предателями!
""".strip(), reply_markup=play_again_keyboard())

        await message.answer("🎉 Ты угадал первым! Победа в режиме «Все предатели»!")
        from bot.handlers.group import _cancel_turn_timer
        await _cancel_turn_timer(session.chat_id)
        await lobby_service.end_session(session.chat_id)
    else:
        await message.answer(f"""
❌ Мимо. <code>{html.escape(guess)}</code> — не тот персонаж.

Слушай дальше, пробуй снова.
""".strip())


@router.message(Command("hint"))
async def cmd_hint(message: Message):
    """Запрос подсказки для шпиона."""
    user_id = message.from_user.id
    if not check_rate_limit(user_id, cooldown=2.0):
        await message.answer("⏳ Слишком часто. Подожди секунду.")
        return

    # Находим сессию, где пользователь — шпион
    session = None
    player = None
    for s in lobby_service.get_all_sessions():
        p = s.get_player(user_id)
        if p and p.role == Role.SPY:
            session = s
            player = p
            break

    if not session or not player:
        await message.answer("🎭 Ты не в игре.")
        return

    if session.game_type == GameType.ALL_TRAITORS:
        await message.answer("🚫 В этом режиме подсказки отключены. Догадывайся сам!")
        return

    if session.game_type == GameType.BLIND_SPY:
        await message.answer("🎭 Ты мирный, подсказки не для тебя. Слушай описания.")
        return

    if player.role != Role.SPY:
        await message.answer("🎭 Ты мирный, подсказки не для тебя. Слушай описания.")
        return

    await message.answer("💡 Подсказки приходят автоматически каждый раунд. Жди.")


@router.callback_query(F.data.startswith("hint_"))
async def cb_hint(callback: CallbackQuery):
    await callback.answer("💡 Подсказки приходят автоматически каждый раунд.", show_alert=True)


# ═══════════════════════════════════════════════════════════════
# ✅ "Я СКАЗАЛ" — переход хода (IRL описания)
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("i_said_"))
async def cb_i_said(callback: CallbackQuery, bot: Bot):
    """Игрок нажал 'Я сказал' — переход к следующему."""
    if not check_rate_limit(callback.from_user.id, cooldown=1.0):
        await callback.answer("⏳ Слишком быстро.", show_alert=True)
        return
    chat_id = int(callback.data.split("_")[2])
    session = lobby_service.get_session(chat_id)
    if not session or session.state != GameState.DESCRIBING:
        await callback.answer("❌ Сейчас не фаза описаний.", show_alert=True)
        return

    user_id = callback.from_user.id
    player = session.get_player(user_id)
    if not player:
        await callback.answer("❌ Ты не в этой игре.", show_alert=True)
        return

    # Проверяем, что это действительно ход этого игрока
    current = get_next_player(session)
    if not current or current.user_id != user_id:
        await callback.answer("⏳ Сейчас не твоя очередь.", show_alert=True)
        return

    if current.has_described:
        await callback.answer("✅ Ты уже сказал.", show_alert=True)
        return

    # Отмечаем, что игрок описал
    current.has_described = True
    session.current_turn_index += 1

    await callback.answer("✅ Принято!")
    await callback.message.edit_text("✅ Ты сказал. Жди остальных.")
    update_session_activity(session)

    await bot.send_message(chat_id, f"✅ <b>{html.escape(current.full_name)}</b> сказал!")

    if check_all_described(session):
        session.state = GameState.DISCUSSION
        await lobby_service.persist_session(session)

        await bot.send_message(chat_id,
            f"🎉 <b>Раунд завершён!</b> Пауза 1 минута..."
        )
        await asyncio.sleep(60)

        await bot.send_message(chat_id, """
⏰ <b>Что дальше?</b>

🗳️ Голосовать — выбрать шпиона
▶️ Следующий раунд — ещё описания
""".strip(), reply_markup=round_end_keyboard(chat_id))
        return

    next_player = get_next_player(session)
    if next_player:
        round_hint = "⚠️ Говори максимально обобщённо!" if session.description_round <= 2 else ""
        await bot.send_message(chat_id,
            f"🗣️ <b>{html.escape(next_player.full_name)}</b>, говори! 1 признак вслух."
            + (f"\n{round_hint}" if round_hint else "")
        )

        try:
            from bot.handlers.group import _get_role_hint
            role_hint = _get_role_hint(next_player)
            await bot.send_message(next_player.user_id,
                f"🎯 <b>Твоя очередь!</b>"
                + (f"\n\n{round_hint}" if round_hint else "")
                + role_hint
                + "\n\nСкажи вслух и жми кнопку.",
                reply_markup=i_said_keyboard(chat_id),
            )
        except Exception as e:
            logger.warning("Не удалось отправить кнопку Я-сказал (id=%d): %s", next_player.user_id, e)

    await lobby_service.persist_session(session)


@router.message(Command("mystats"))
async def cmd_mystats(message: Message):
    """Статистика игрока."""
    from bot.models.database import get_stats
    stats = await get_stats(message.from_user.id)
    if not stats:
        await message.answer(
            "📊 <b>Твоя статистика</b>\n\n"
            "Пока нет сыгранных игр. Сыграй первую!"
        )
        return

    winrate = (stats["games_won"] / stats["games_played"] * 100) if stats["games_played"] > 0 else 0

    await message.answer(f"""
📊 <b>ТВОЯ СТАТИСТИКА</b>

🎮 Сыграно игр: <b>{stats["games_played"]}</b>
🏆 Побед: <b>{stats["games_won"]}</b>
💔 Поражений: <b>{stats["games_lost"]}</b>
📈 Винрейт: <b>{winrate:.1f}%</b>
💡 Подсказок взято: <b>{stats["hints_used"]}</b>
💌 Писем отправлено: <b>{stats["letters_sent"]}</b>
""".strip())


@router.message(Command("help"))
async def cmd_help_private(message: Message):
    """Помощь в ЛС."""
    await message.answer("""
❓ <b>КОМАНДЫ</b>

/start — начать
/help — справка

🕵️ <b>Шпион:</b>
/guess Имя — угадать
/hint — подсказка (1 раз)

💌 <b>Письма:</b>
/send @username Текст (1 раз)

📊 /mystats — статистика (скоро)

🎮 Как играть: добавь бота в группу, напиши /spy
⚠️ Напиши /start до игры, чтобы получать роли!
""".strip())


@router.message(Command("send"))
async def cmd_send(message: Message, bot: Bot):
    """Отправить письмо другому игроку."""
    if not check_rate_limit(message.from_user.id, cooldown=2.0):
        await message.answer("⏳ Слишком часто. Подожди секунду.")
        return
    args = message.text.split(maxsplit=2)

    if message.reply_to_message and len(args) >= 2:
        if len(args) >= 3:
            target_username = args[1].strip()
            letter_text = args[2].strip()
        else:
            target_username = message.reply_to_message.from_user.full_name
            letter_text = args[1].strip()
    elif len(args) < 3:
        await message.answer(
            "💌 <code>/send @username Текст</code>\nПример: <code>/send @ivan Думаю, ты шпион...</code>\n\nИли ответь на сообщение: /send Текст"
        )
        return
    else:
        target_username = args[1].strip()
        letter_text = args[2].strip()

    if len(letter_text) < 3:
        await message.answer("❌ Слишком коротко. Минимум 3 символа.")
        return

    if len(letter_text) > 200:
        await message.answer("❌ Слишком длинно. Максимум 200 символов.")
        return

    # Находим сессию игрока
    session = None
    player = None
    for s in lobby_service.get_all_sessions():
        p = s.get_player(message.from_user.id)
        if p:
            session = s
            player = p
            break

    if not session or not player:
        await message.answer("🚫 Ты не в игре. Письма только во время игры.")
        return

    if player.letter_sent:
        await message.answer("⚠️ Ты уже отправил письмо. 1 раз за игру.")
        return

    # Находим получателя: по username, реплаю или по имени
    target_player = None

    # 1. По @username
    target_clean = target_username.lstrip('@')
    for p in session.players:
        if p.username and p.username.lower() == target_clean.lower():
            target_player = p
            break

    # 2. По реплаю
    if not target_player and message.reply_to_message:
        for p in session.players:
            if p.user_id == message.reply_to_message.from_user.id:
                target_player = p
                break

    # 3. По полному имени (без учёта регистра)
    if not target_player:
        for p in session.players:
            if p.full_name.lower() == target_clean.lower():
                target_player = p
                break

    if not target_player:
        await message.answer(f"❌ {target_username} не в этой игре.\n\n💡 /send @username Текст\nИли ответь реплаем: /send Текст")
        return

    if target_player.user_id == player.user_id:
        await message.answer("❌ Нельзя отправить письмо себе!")
        return

    player.letter_sent = True
    target_player.received_letters[player.user_id] = letter_text
    await save_letter(session.chat_id, player.user_id, target_player.user_id, letter_text)

    safe_letter_text = html.escape(letter_text)
    await message.answer(f"✅ Отправлено <b>{html.escape(target_player.full_name)}</b>!\n📝 <i>{safe_letter_text}</i>")

    try:
        await bot.send_message(target_player.user_id, f"""
💌 <b>ПИСЬМО</b> от <b>{html.escape(player.full_name)}</b>

<i>{safe_letter_text}</i>
""".strip())
    except Exception as e:
        logger.warning("Не удалось доставить письмо (id=%d): %s", target_player.user_id, e)


# ═══════════════════════════════════════════════════════════════
# 👤 ВЕДУЩИЙ: установка персонажа
# ═══════════════════════════════════════════════════════════════

@router.message(Command("setchar"))
async def cmd_setchar(message: Message):
    """Ведущий устанавливает своего персонажа."""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "📝 <code>/setchar Имя Персонажа</code>\n"
            "Пример: <code>/setchar Гарри Поттер</code>"
        )
        return

    char_name = args[1].strip()
    if len(char_name) < 2:
        await message.answer("❌ Слишком короткое имя (мин. 2 символа).")
        return
    if len(char_name) > 50:
        await message.answer("❌ Слишком длинное имя (макс. 50 символов).")
        return

    # Ищем сессию, где пользователь — ведущий
    session = None
    for s in lobby_service.get_all_sessions():
        if s.host_mode and s.host_id == message.from_user.id:
            session = s
            break

    if not session:
        await message.answer("🚫 Ты не ведущий в активной игре.")
        return

    if session.state != GameState.LOBBY:
        await message.answer("🚫 Нельзя менять персонажа во время игры.")
        return

    session.character = char_name
    await lobby_service.persist_session(session)

    await message.answer(
        f"✅ Персонаж установлен: <code>{html.escape(char_name)}</code>\n\n"
        f"Нажми ✅ Оставить чтобы начать игру, "
        f"или отправь ещё один <code>/setchar</code>.",
        reply_markup=host_confirm_keyboard(session.chat_id)
    )
