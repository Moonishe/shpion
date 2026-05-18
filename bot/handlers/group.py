import asyncio
import html
import logging

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from bot.models.game import GameState, GameMode, GameType, SettingsMode, Role
from bot.services import lobby_service
from bot.services.game_service import (
    check_all_described, randomize_settings,
    create_turn_order, get_next_player, process_vote_result,
    check_rate_limit, update_session_activity, record_stats,
    send_auto_hints, get_hint_for_spy, HINT_TYPES, count_votes
)
from bot.keyboards.inline import (
    lobby_keyboard, vote_keyboard, start_vote_keyboard,
    spy_count_keyboard, settings_keyboard, category_keyboard,
    game_type_keyboard, question_target_keyboard, yes_no_keyboard,
    play_again_keyboard, host_confirm_keyboard, reroll_keyboard, host_pick_keyboard,
    round_end_keyboard
)
from bot.config import (
    get_category_name, add_custom_character, remove_custom_character,
    get_custom_characters, clear_custom_characters, is_admin, ADMIN_USERNAME,
    get_categories
)
logger = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))


def _can_control(session, user_id: int, username: str | None = None) -> bool:
    """Проверяет, может ли пользователь управлять игрой (создатель или админ бота)."""
    if session.creator_id == user_id:
        return True
    if is_admin(username):
        return True
    return False


# ═══════════════════════════════════════════════════════════════
# 📜 ТЕКСТЫ
# ═══════════════════════════════════════════════════════════════

RULES_TEXT = """
📜 <b>ПРАВИЛА</b>

🎯 Мирные — вычислить шпиона по описаниям
🕵️ Шпионы — понять кто загадан и угадать

👤 Мирные — знают персонажа
🕵️ Шпионы — не знают, вычисляют на слух
🤡 Провокатор — знает другого персонажа из категории, играет за шпионов

🤡 <b>Провокатор:</b>
• Получает другого персонажа из той же категории
• Описывает его, путая мирных
• Побеждает вместе со шпионами
• Если раскроют — выбывает, игра дальше

⚠️ Перед игрой каждый пишет /start в ЛС боту
""".strip()


HOWTO_TEXT = """
❓ <b>КАК ИГРАТЬ</b>

1. <code>/spy</code> — создать лобби
2. Жми <b>Присоединиться</b>
3. Настрой: шпионы, категория, режим, провокатор
4. Жми <b>Начать игру</b>
5. Роли придут в ЛС:
   👤 Мирные — имя персонажа
   🕵️ Шпионы — ничего
   🤡 Провокатор — другой персонаж из категории (играет за шпионов)
6. Говорите <b>вслух</b>, в чат не пишите подсказки!
7. Шпион: <code>/guess Имя</code> | Мирные: <code>/vote</code>

💡 Шпион: <code>/hint</code> в ЛС — 1 подсказка за игру
💌 <code>/send @username Текст</code> — 1 письмо за игру
👤 В настройках можно включить <b>режим ведущего</b> — он загадывает персонажа, но не играет
🔄 <code>/reroll</code> — голосование за смену персонажа во время игры
""".strip()


# ═══════════════════════════════════════════════════════════════
# 🎮 ЛОББИ
# ═══════════════════════════════════════════════════════════════

def _lobby_text(session) -> str:
    """Формирует текст лобби."""
    players_list = "\n".join([f"• {html.escape(p.full_name)}{' 👑' if p.is_creator else ''}" for p in session.players])
    if not players_list:
        players_list = "— пока никого"
    
    if session.settings_mode == SettingsMode.RANDOM:
        settings_block = "🎲 <b>Рандом</b> — настройки выберутся при старте"
    else:
        mode_text = f"{session.spy_count} шпион(ов)" if session.spy_count else "1 шпион"
        cat_name_text = get_category_name(session.categories)
    game_type_map = {
        GameType.CLASSIC: "📝 Классика",
        GameType.QUESTIONS: "❓ Вопросы",
        GameType.BLIND_SPY: "🎭 Слепой шпион",
    }
    game_type_text = game_type_map.get(session.game_type, "📝 Классика")
    provocateur_text = "есть" if session.provocateur_enabled else "нет"
    host_text = ""
    if session.host_mode:
        host_obj = session.get_player(session.host_id)
        host_name = html.escape(host_obj.full_name) if host_obj else "???"
        host_text = f"\n👤 Ведущий: {host_name}"
    settings_block = f"🕵️ <b>Шпионы:</b> {mode_text}\n📂 {cat_name_text}  •  🎯 {game_type_text}  •  🤡 Провокатор: {provocateur_text}{host_text}"
    
    return f"""
🎭 <b>ШПИОН</b> — лобби

👥 Игроки ({len(session.players)}):
{players_list}

{settings_block}
""".strip()


def _settings_text(session) -> str:
    """Текст меню настроек."""
    mode_text = "1 шпион" if session.mode == GameMode.ONE_SPY else f"{session.spy_count or 'авто'} шпион(ов)"
    cat_name_text = get_category_name(session.categories)
    game_type_map = {
        GameType.CLASSIC: "📝 Классика",
        GameType.QUESTIONS: "❓ Вопросы",
        GameType.BLIND_SPY: "🎭 Слепой шпион",
    }
    game_type_text = game_type_map.get(session.game_type, "📝 Классика")
    provocateur_text = "да" if session.provocateur_enabled else "нет"
    host_text = ""
    if session.host_mode:
        host_obj = session.get_player(session.host_id)
        host_name = html.escape(host_obj.full_name) if host_obj else "???"
        host_text = f"\n👤 Ведущий: {host_name}"
    return f"⚙️ <b>Настройки:</b>\n🕵️ <b>Шпионы:</b> {mode_text}\n📂 {cat_name_text}  •  🎯 {game_type_text}  •  🤡 Провокатор: {provocateur_text}{host_text}"


@router.message(Command("spy"))
async def cmd_spy(message: Message):
    """Создание нового лобби."""
    if not check_rate_limit(message.from_user.id, cooldown=3.0):
        await message.answer("⏳ Слишком часто. Подожди.")
        return
    chat_id = message.chat.id
    existing = lobby_service.get_session(chat_id)
    if existing and existing.state != GameState.FINISHED:
        await message.answer("⚠️ Уже есть активная игра. Дождитесь конца или напишите /stop.")
        return

    session = lobby_service.create_session(
        chat_id=chat_id,
        creator_id=message.from_user.id,
        creator_username=message.from_user.username or "",
        creator_full_name=message.from_user.full_name,
    )
    
    await message.answer(
        f"🎉 <b>{html.escape(message.from_user.full_name)}</b> создал игру!\n\n"
        f"{_lobby_text(session)}",
        reply_markup=lobby_keyboard(session),
    )


@router.callback_query(F.data == "join")
async def cb_join(callback: CallbackQuery):
    """Присоединение к игре."""
    if not check_rate_limit(callback.from_user.id, cooldown=2.0):
        await callback.answer("⏳ Слишком часто. Подожди.", show_alert=True)
        return
    chat_id = callback.message.chat.id
    session = lobby_service.get_session(chat_id)
    if not session:
        await callback.answer("⏳ Этой игры больше нет.", show_alert=True)
        return
    if session.state != GameState.LOBBY:
        await callback.answer("⏳ Игра уже началась.", show_alert=True)
        return

    user = callback.from_user
    ok = lobby_service.add_player(session, user.id, user.username or "", user.full_name)
    if not ok:
        await callback.answer("⚠️ Уже в игре или нет мест.", show_alert=True)
        return

    await callback.answer(f"✅ {user.full_name} присоединился!")
    update_session_activity(session)
    await callback.message.edit_text(
        _lobby_text(session),
        reply_markup=lobby_keyboard(session),
    )


@router.callback_query(F.data == "leave")
async def cb_leave(callback: CallbackQuery):
    """Выход из лобби."""
    chat_id = callback.message.chat.id
    session = lobby_service.get_session(chat_id)
    if not session:
        await callback.answer("⏳ Этой игры больше нет.", show_alert=True)
        return
    if session.state != GameState.LOBBY:
        await callback.answer("🚫 Нельзя выйти во время игры.", show_alert=True)
        return

    user = callback.from_user
    if user.id == session.creator_id:
        await callback.answer("👑 Создатель так не может. Жми ❌ Отменить.", show_alert=True)
        return

    ok = lobby_service.remove_player(session, user.id)
    if not ok:
        await callback.answer("⚠️ Тебя нет в игре.", show_alert=True)
        return

    await callback.answer(f"🚪 {user.full_name} вышел из игры.")
    await callback.message.edit_text(
        _lobby_text(session),
        reply_markup=lobby_keyboard(session),
    )


@router.callback_query(F.data == "play_again")
async def cb_play_again(callback: CallbackQuery):
    """Быстрое создание новой игры."""
    chat_id = callback.message.chat.id
    user = callback.from_user

    existing = lobby_service.get_session(chat_id)
    if existing and existing.state != GameState.FINISHED:
        await callback.answer("⚠️ Уже есть игра.", show_alert=True)
        return

    session = lobby_service.create_session(
        chat_id=chat_id,
        creator_id=user.id,
        creator_username=user.username or "",
        creator_full_name=user.full_name,
    )
    await callback.answer("🎉 Погнали!")
    await callback.message.answer(
        f"🎭 <b>{html.escape(user.full_name)}</b> создал новую игру!\n\n{_lobby_text(session)}",
        reply_markup=lobby_keyboard(session),
    )


@router.callback_query(F.data == "rules")
async def cb_rules(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(RULES_TEXT)


@router.callback_query(F.data == "howto")
async def cb_howto(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(HOWTO_TEXT)


@router.callback_query(F.data == "toggle_settings_mode")
async def cb_toggle_settings_mode(callback: CallbackQuery):
    """Переключение между ручным и рандомным режимом."""
    chat_id = callback.message.chat.id
    session = lobby_service.get_session(chat_id)
    if not session:
        await callback.answer("⏳ Этой игры больше нет.", show_alert=True)
        return
    if not _can_control(session, callback.from_user.id, callback.from_user.username):
        await callback.answer("🔒 Только создатель или админ может это делать.", show_alert=True)
        return
    
    # Переключаем режим
    if session.settings_mode == SettingsMode.MANUAL:
        session.settings_mode = SettingsMode.RANDOM
        await callback.answer("🎲 Рандом — настройки выберутся при старте!")
    else:
        session.settings_mode = SettingsMode.MANUAL
        await callback.answer("🔧 Ручной режим — настраивай сам!")
    
    await callback.message.edit_text(
        _lobby_text(session),
        reply_markup=lobby_keyboard(session),
    )


# ═══════════════════════════════════════════════════════════════
# ⚙️ НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "settings_menu")
async def cb_settings_menu(callback: CallbackQuery):
    """Открыть меню настроек."""
    chat_id = callback.message.chat.id
    session = lobby_service.get_session(chat_id)
    if not session:
        await callback.answer("⏳ Этой игры больше нет.", show_alert=True)
        return
    if not _can_control(session, callback.from_user.id, callback.from_user.username):
        await callback.answer("🔒 Только создатель или админ может менять настройки.", show_alert=True)
        return
    
    await callback.answer()
    await callback.message.edit_text(
        _settings_text(session),
        reply_markup=settings_keyboard(session),
    )


@router.callback_query(F.data == "back_lobby")
async def cb_back_lobby(callback: CallbackQuery):
    """Вернуться в лобби."""
    chat_id = callback.message.chat.id
    session = lobby_service.get_session(chat_id)
    if not session:
        await callback.answer("⏳ Этой игры больше нет.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        _lobby_text(session),
        reply_markup=lobby_keyboard(session),
    )


@router.callback_query(F.data == "back_settings")
async def cb_back_settings(callback: CallbackQuery):
    """Вернуться в настройки."""
    chat_id = callback.message.chat.id
    session = lobby_service.get_session(chat_id)
    if not session:
        await callback.answer("⏳ Этой игры больше нет.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        _settings_text(session),
        reply_markup=settings_keyboard(session),
    )


@router.callback_query(F.data == "settings_spies")
async def cb_settings_spies(callback: CallbackQuery):
    """Меню выбора количества шпионов."""
    chat_id = callback.message.chat.id
    session = lobby_service.get_session(chat_id)
    if not session or not _can_control(session, callback.from_user.id, callback.from_user.username):
        await callback.answer("🔒 Только создатель или админ может менять настройки.", show_alert=True)
        return
    
    await callback.answer()
    await callback.message.edit_text(
        "🕵️ <b>Сколько шпионов?</b>\n\n"
        "💡 4-5 игроков → 1 | 6-8 → 2 | 9+ → 3+",
        reply_markup=spy_count_keyboard(),
    )


@router.callback_query(F.data.startswith("set_spies_"))
async def cb_set_spies(callback: CallbackQuery):
    """Установить количество шпионов."""
    chat_id = callback.message.chat.id
    session = lobby_service.get_session(chat_id)
    if not session or not _can_control(session, callback.from_user.id, callback.from_user.username):
        await callback.answer("🔒 Только создатель или админ может менять настройки.", show_alert=True)
        return
    
    try:
        count = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        await callback.answer("❌ Ошибка данных.", show_alert=True)
        return
    if count == 1:
        session.mode = GameMode.ONE_SPY
        session.spy_count = 1
    else:
        session.mode = GameMode.MULTI_SPY
        session.spy_count = count
    
    await callback.answer(f"✅ Установлено: {count} шпион(ов)")
    await callback.message.edit_text(
        _settings_text(session),
        reply_markup=settings_keyboard(session),
    )


@router.callback_query(F.data == "settings_category")
async def cb_settings_category(callback: CallbackQuery):
    """Меню выбора категории."""
    chat_id = callback.message.chat.id
    session = lobby_service.get_session(chat_id)
    if not session or not _can_control(session, callback.from_user.id, callback.from_user.username):
        await callback.answer("🔒 Только создатель или админ может менять настройки.", show_alert=True)
        return
    
    await callback.answer()
    await callback.message.edit_text(
        "📂 <b>Категории персонажей</b>\n\nЖми на категории чтобы выбрать. Можно несколько.",
        reply_markup=category_keyboard(session),
    )


@router.callback_query(F.data.startswith("toggle_cat_"))
async def cb_toggle_category(callback: CallbackQuery):
    """Переключить категорию."""
    chat_id = callback.message.chat.id
    session = lobby_service.get_session(chat_id)
    if not session or not _can_control(session, callback.from_user.id, callback.from_user.username):
        await callback.answer("🔒 Только создатель или админ может менять настройки.", show_alert=True)
        return
    
    cat_id = callback.data.replace("toggle_cat_", "")
    cats = get_categories()
    
    if cat_id == "*":
        session.categories = ["*"]
    else:
        if "*" in session.categories:
            session.categories = [cat_id]
        else:
            if cat_id in session.categories:
                session.categories = [c for c in session.categories if c != cat_id]
                if not session.categories:
                    session.categories = ["*"]
            else:
                session.categories.append(cat_id)
    
    await callback.answer()
    await callback.message.edit_text(
        "📂 <b>Категории персонажей</b>\n\nЖми на категории чтобы выбрать. Можно несколько.",
        reply_markup=category_keyboard(session),
    )


@router.callback_query(F.data == "settings_game_type")
async def cb_settings_game_type(callback: CallbackQuery):
    """Меню выбора типа игры."""
    chat_id = callback.message.chat.id
    session = lobby_service.get_session(chat_id)
    if not session or not _can_control(session, callback.from_user.id, callback.from_user.username):
        await callback.answer("🔒 Только создатель или админ может менять настройки.", show_alert=True)
        return
    
    await callback.answer()
    await callback.message.edit_text(
        "🎯 <b>Режим игры</b>\n\n"
        "📝 Классика — каждый говорит 1 признак вслух\n"
        "❓ Вопросы — задаёте да/нет вопросы друг другу",
        reply_markup=game_type_keyboard(),
    )


@router.callback_query(F.data.startswith("set_game_type_"))
async def cb_set_game_type(callback: CallbackQuery):
    """Установить тип игры."""
    chat_id = callback.message.chat.id
    session = lobby_service.get_session(chat_id)
    if not session or not _can_control(session, callback.from_user.id, callback.from_user.username):
        await callback.answer("🔒 Только создатель или админ может менять настройки.", show_alert=True)
        return

    game_type = callback.data.replace("set_game_type_", "")
    if game_type == "classic":
        session.game_type = GameType.CLASSIC
        type_name = "Классика"
    elif game_type == "questions":
        session.game_type = GameType.QUESTIONS
        type_name = "Вопросы"
    elif game_type == "blind_spy":
        session.game_type = GameType.BLIND_SPY
        type_name = "Слепой шпион"
    else:
        session.game_type = GameType.CLASSIC
        type_name = "Классика"

    await callback.answer(f"✅ Режим: {type_name}")
    await callback.message.edit_text(
        _settings_text(session),
        reply_markup=settings_keyboard(session),
    )


@router.callback_query(F.data == "toggle_provocateur")
async def cb_toggle_provocateur(callback: CallbackQuery):
    """Переключить провокатора."""
    chat_id = callback.message.chat.id
    session = lobby_service.get_session(chat_id)
    if not session or not _can_control(session, callback.from_user.id, callback.from_user.username):
        await callback.answer("🔒 Только создатель или админ может менять настройки.", show_alert=True)
        return
    
    session.provocateur_enabled = not session.provocateur_enabled
    status = "вкл" if session.provocateur_enabled else "выкл"
    await callback.answer(f"🤡 Провокатор: {status}")
    await callback.message.edit_text(
        _settings_text(session),
        reply_markup=settings_keyboard(session),
    )


@router.callback_query(F.data == "toggle_host_mode")
async def cb_toggle_host_mode(callback: CallbackQuery):
    """Переключить режим ведущего."""
    chat_id = callback.message.chat.id
    session = lobby_service.get_session(chat_id)
    if not session or not _can_control(session, callback.from_user.id, callback.from_user.username):
        await callback.answer("🔒 Только создатель или админ может менять настройки.", show_alert=True)
        return
    
    session.host_mode = not session.host_mode
    session.host_id = callback.from_user.id if session.host_mode else None
    status = "вкл" if session.host_mode else "выкл"
    await callback.answer(f"👤 Ведущий: {status}")
    await callback.message.edit_text(
        _settings_text(session),
        reply_markup=settings_keyboard(session),
    )


@router.callback_query(F.data == "settings_pick_host")
async def cb_settings_pick_host(callback: CallbackQuery):
    """Открыть список для выбора ведущего."""
    chat_id = callback.message.chat.id
    session = lobby_service.get_session(chat_id)
    if not session or not _can_control(session, callback.from_user.id, callback.from_user.username):
        await callback.answer("🔒 Только создатель или админ.", show_alert=True)
        return
    
    # Включаем режим ведущего если ещё не включён
    if not session.host_mode:
        session.host_mode = True
        session.host_id = callback.from_user.id  # по умолчанию создатель
    
    await callback.answer()
    await callback.message.edit_text(
        f"👤 <b>Выбери ведущего</b>\n\nКто будет загадывать персонажа и не играть?\n\nТекущий: {html.escape(session.get_player(session.host_id).full_name) if session.get_player(session.host_id) else 'не выбран'}",
        reply_markup=host_pick_keyboard(chat_id, session.players, session.host_id),
    )


@router.callback_query(F.data.startswith("set_host_"))
async def cb_set_host(callback: CallbackQuery):
    """Установить ведущего."""
    parts = callback.data.split("_")
    try:
        chat_id = int(parts[2])
        target_id = int(parts[3])
    except (IndexError, ValueError):
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    session = lobby_service.get_session(chat_id)
    if not session or not _can_control(session, callback.from_user.id, callback.from_user.username):
        await callback.answer("🔒 Только создатель или админ.", show_alert=True)
        return
    session.host_id = target_id
    host_name = session.get_player(target_id).full_name if session.get_player(target_id) else "???"
    await callback.answer(f"👤 Ведущий: {host_name}")
    await callback.message.edit_text(
        _settings_text(session),
        reply_markup=settings_keyboard(session),
    )


# ═══════════════════════════════════════════════════════════════
# 👤 ВЕДУЩИЙ
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("host_accept_"))
async def cb_host_accept(callback: CallbackQuery, bot: Bot):
    """Ведущий подтвердил персонажа."""
    try:
        chat_id = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    session = lobby_service.get_session(chat_id)
    if not session or callback.from_user.id != session.host_id:
        await callback.answer("⏳ Ты не ведущий.", show_alert=True)
        return

    await callback.answer("✅ Погнали!")
    await callback.message.edit_text("✅ Персонаж утверждён! Игра начинается.")

    # Раздаём роли и запускаем
    try:
        await lobby_service.start_game(session)
    except ValueError as e:
        await bot.send_message(chat_id, f"❌ {e}")
        return

    if session.game_type in (GameType.CLASSIC, GameType.NO_TRAITORS, GameType.ALL_TRAITORS, GameType.BLIND_SPY):
        session.state = GameState.DESCRIBING
    elif session.game_type == GameType.QUESTIONS:
        session.state = GameState.QUESTIONING
        session.questions_round = 1

    update_session_activity(session)
    await lobby_service.persist_session(session)

    game_type_map = {
        GameType.CLASSIC: "📝 Классика",
        GameType.QUESTIONS: "❓ Вопросы",
        GameType.NO_TRAITORS: "👤 Все мирные (🎲 рандом!)",
        GameType.ALL_TRAITORS: "🕵️ Все шпионы (🎲 рандом!)",
        GameType.BLIND_SPY: "🎭 Слепой шпион",
    }
    game_type_text = game_type_map.get(session.game_type, "📝 Классика")
    spy_text = f"{session.spy_count} шпион(ов)"
    provocateur_text = "да" if session.provocateur_enabled else "нет"

    await bot.send_message(chat_id, f"""
🚀 <b>ИГРА НАЧАЛАСЬ!</b>

👤 Ведущий: {html.escape(callback.from_user.full_name)}
🕵️ Шпионов: {spy_text}
📂 {get_category_name(session.categories)}  •  🎯 {game_type_text}  •  🤡 Провокатор: {provocateur_text}

📩 Роли ушли в личку. Не пришло? Напиши /start боту в ЛС.
""".strip())

    # Раздача ролей в ЛС
    failed = []
    civ_counter = 0
    for p in session.players:
        try:
            if p.role == Role.CIVILIAN:
                char = session.character
                if session.split_character:
                    if civ_counter % 2 == 0:
                        char = session.character
                    else:
                        char = session.split_character
                    civ_counter += 1
                text = f"🎭 <b>МИРНЫЙ</b>\n\nТвой персонаж: <code>{html.escape(char)}</code>\n\nГовори 1 признак вслух. Имя не называй."
            elif p.role == Role.CONFUSED:
                text = f"🎭 <b>ПУТАНИК</b>\n\nТвой персонаж: <code>{html.escape(p.alt_character)}</code>\n⚠️ Это НЕ настоящий персонаж!"
            elif p.role == Role.PROVOCATEUR:
                text = f"🎭 <b>ПРОВОКАТОР</b>\n\nТвой персонаж: <code>{html.escape(p.fake_character)}</code>\nЭто другой персонаж из той же категории."
            elif session.game_type == GameType.BLIND_SPY:
                text = f"🎭 <b>МИРНЫЙ</b>\n\nТвой персонаж: <code>{html.escape(p.fake_character)}</code>\n\nГовори 1 признак вслух. Имя не называй."
            else:
                text = "🎭 <b>ШПИОН</b>\n\nТы не знаешь персонажа. Слушай других.\n/hint — подсказка (1 раз)\n/guess Имя — угадать!"
            await bot.send_message(p.user_id, text)
        except Exception as e:
            logger.warning("Не удалось отправить роль %d: %s", p.user_id, e)
            failed.append(html.escape(p.full_name))

    if failed:
        await bot.send_message(chat_id,
            f"⚠️ Не смог отправить роли: {', '.join(failed)}\nПусть напишут /start боту в ЛС!"
        )

    first_round_msg = await bot.send_message(chat_id, "🎯 Первый раунд!")
    if session.game_type == GameType.QUESTIONS:
        await _start_questioning_phase(first_round_msg, session)
    else:
        await _start_describing_phase(first_round_msg, session, bot)


@router.callback_query(F.data.startswith("host_reroll_"))
async def cb_host_reroll(callback: CallbackQuery, bot: Bot):
    """Ведущий просит другого персонажа."""
    import random as _random
    try:
        chat_id = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    session = lobby_service.get_session(chat_id)
    if not session or callback.from_user.id != session.host_id:
        await callback.answer("⏳ Ты не ведущий.", show_alert=True)
        return

    from bot.config import get_characters_by_category
    chars = get_characters_by_category(session.categories)
    if chars:
        session.character = _random.choice(chars)

    await callback.answer("🔄 Новый персонаж!")
    await callback.message.edit_text(
        f"🎭 <b>Новый персонаж:</b> <code>{html.escape(session.character)}</code>\n\n"
        f"✅ Оставить — игра начнётся\n"
        f"🔄 Другой — ещё один случайный\n"
        f"<code>/setchar Имя</code> — свой вариант",
        reply_markup=host_confirm_keyboard(chat_id)
    )
    await lobby_service.persist_session(session)


# ═══════════════════════════════════════════════════════════════
# 🚀 СТАРТ ИГРЫ
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "start_game")
async def cb_start(callback: CallbackQuery, bot: Bot):
    """Запуск игры."""
    chat_id = callback.message.chat.id
    session = lobby_service.get_session(chat_id)
    if not session:
        await callback.answer("⏳ Этой игры больше нет.", show_alert=True)
        return
    if not _can_control(session, callback.from_user.id, callback.from_user.username):
        await callback.answer("🔒 Только создатель или админ может запустить игру.", show_alert=True)
        return
    if not session.can_start():
        await callback.answer("👥 Нужно минимум 2 игрока!", show_alert=True)
        return

    import random as _random

    # Если рандомный режим — рандомизируем настройки
    if session.settings_mode == SettingsMode.RANDOM:
        randomize_settings(session)

    # 10% шанс — случайный спецрежим (только в классике)
    if _random.random() < 0.05:
        session.game_type = _random.choice([GameType.NO_TRAITORS, GameType.ALL_TRAITORS])

    # Проверяем, есть ли персонажи в выбранных категориях
    from bot.config import get_characters_by_category
    characters = get_characters_by_category(session.categories)
    if not characters:
        await callback.answer(
            "❌ В выбранных категориях нет персонажей! Выберите другие.",
            show_alert=True
        )
        return

    if not session.host_mode and session.state != GameState.LOBBY:
        await callback.answer("⏳ Игра уже началась.", show_alert=True)
        return

    from bot.handlers.private import is_user_started, get_unstarted
    unstarted = get_unstarted(session.players)
    if unstarted:
        await callback.answer(
            f"⚠️ Эти игроки не написали /start боту в ЛС:\n{', '.join(html.escape(u) for u in unstarted)}\n\nПусть напишут /start и потом запускайте.",
            show_alert=True,
        )
        return

    # Режим ведущего: только выбираем персонажа, ждём подтверждения
    if session.host_mode and session.host_id:
        session.character = _random.choice(characters)
        session.players = [p for p in session.players if p.user_id != session.host_id]
        if not session.players:
            await callback.answer("❌ Нет игроков кроме ведущего.", show_alert=True)
            return
        session.state = GameState.LOBBY
        await callback.answer()
        await callback.message.edit_text(
            "👤 <b>Ожидание ведущего...</b>\n\n"
            "Персонаж отправлен ведущему в ЛС. Как подтвердит — игра начнётся."
        )
        try:
            await bot.send_message(
                session.host_id,
                f"🎭 <b>Ты ведущий!</b>\n\n"
                f"Случайный персонаж: <code>{html.escape(session.character)}</code>\n\n"
                f"✅ Оставить — игра начнётся\n"
                f"🔄 Другой — новый случайный\n"
                f"<code>/setchar Имя</code> — свой вариант\n\n"
                f"Персонаж придёт в ЛС всем игрокам после твоего подтверждения.",
                reply_markup=host_confirm_keyboard(session.chat_id)
            )
        except Exception as e:
            logger.warning("Не удалось отправить персонаж ведущему: %s", e)
        await lobby_service.persist_session(session)
        return

    # Обычный режим: запускаем игру
    try:
        await lobby_service.start_game(session)
    except ValueError as e:
        await callback.answer(f"❌ {str(e)}", show_alert=True)
        return
    
    # Устанавливаем состояние в зависимости от типа игры
    if session.game_type in (GameType.CLASSIC, GameType.NO_TRAITORS, GameType.ALL_TRAITORS, GameType.BLIND_SPY):
        session.state = GameState.DESCRIBING
    elif session.game_type == GameType.QUESTIONS:
        session.state = GameState.QUESTIONING
        session.questions_round = 1

    await callback.answer("🚀 Поехали!")
    update_session_activity(session)
    await lobby_service.persist_session(session)

    game_type_map = {
        GameType.CLASSIC: "📝 Классика",
        GameType.QUESTIONS: "❓ Вопросы",
        GameType.NO_TRAITORS: "👤 Все мирные (🎲 рандом!)",
        GameType.ALL_TRAITORS: "🕵️ Все шпионы (🎲 рандом!)",
        GameType.BLIND_SPY: "🎭 Слепой шпион",
    }
    game_type_text = game_type_map.get(session.game_type, "📝 Классика")
    provocateur_text = "да" if session.provocateur_enabled else "нет"
    spy_text = f"{session.spy_count} шпион(ов)"

    await callback.message.edit_text(f"""
🚀 <b>ИГРА НАЧАЛАСЬ!</b>

🕵️ Шпионов: {spy_text}
📂 {get_category_name(session.categories)}  •  🎯 {game_type_text}  •  🤡 Провокатор: {provocateur_text}

📩 Роли ушли в личку. Не пришло? Напиши /start боту в ЛС.
""".strip())

    # Раздача ролей в ЛС
    failed = []
    civ_counter = 0
    for p in session.players:
        try:
            if p.role == Role.CIVILIAN:
                char = session.character
                if session.split_character:
                    if civ_counter % 2 == 0:
                        char = session.character
                    else:
                        char = session.split_character
                    civ_counter += 1
                text = f"""
🎭 <b>МИРНЫЙ</b>

Твой персонаж: <code>{html.escape(char)}</code>

Говори 1 признак вслух. Имя не называй.
Обсуждение голосом, в чат не пиши!

💌 /send @username Текст — письмо (1 раз)
""".strip()
            elif p.role == Role.CONFUSED:
                text = f"""
🎭 <b>ПУТАНИК</b>

Твой персонаж: <code>{html.escape(p.alt_character)}</code>
⚠️ Это НЕ настоящий персонаж! Опиши его — запутай шпионов.

Говори 1 признак вслух. Имя не называй.
""".strip()
            elif p.role == Role.PROVOCATEUR:
                text = f"""
🎭 <b>ПРОВОКАТОР</b>

Твой персонаж: <code>{html.escape(p.fake_character)}</code>
Это другой персонаж из той же категории. Описывай его — путай мирных. Побеждаешь со шпионами!
""".strip()
            else:  # SPY
                if session.game_type == GameType.ALL_TRAITORS:
                    text = """
🎭 <b>ШПИОН</b>

Ты не знаешь персонажа. Слушай других.
Говори 1 признак вслух — придумай что-то правдоподобное.

⚠️ Подсказки отключены.
/guess Имя — угадать и победить!
""".strip()
                elif session.game_type == GameType.BLIND_SPY:
                    text = f"""
🎭 <b>МИРНЫЙ</b>

Твой персонаж: <code>{html.escape(p.fake_character)}</code>

Говори 1 признак вслух. Имя не называй.
""".strip()
                else:
                    text = """
🎭 <b>ШПИОН</b>

Ты не знаешь персонажа. Слушай других.
Говори 1 признак вслух — придумай что-то правдоподобное.

/hint — подсказка (1 раз)
/guess Имя — угадать и победить!
""".strip()
            await bot.send_message(p.user_id, text)
        except Exception as e:
            logger.warning("Не удалось отправить роль %s (id=%d): %s", p.full_name, p.user_id, e)
            failed.append(html.escape(p.full_name))

    if failed:
        await callback.message.answer(
            f"⚠️ Не смог отправить роли: {', '.join(failed)}\n"
            f"Пусть напишут /start боту в ЛС!"
        )

    # Начинаем игру
    if session.game_type == GameType.CLASSIC:
        await _start_describing_phase(callback.message, session, bot)
    elif session.game_type == GameType.QUESTIONS:
        await _start_questioning_phase(callback.message, session)
    elif session.game_type == GameType.NO_TRAITORS:
        await _start_describing_phase(callback.message, session, bot)
    elif session.game_type == GameType.ALL_TRAITORS:
        await _start_describing_phase(callback.message, session, bot)
    else:
        await _start_describing_phase(callback.message, session, bot)


async def _start_describing_phase(message: Message, session, bot: Bot):
    """Начать фазу описаний (IRL — голосовые описания)."""
    from bot.keyboards.inline import i_said_keyboard

    # Создаём очередь ходов (шпионы с 15% шансом в начале)
    turn_order = create_turn_order(session)

    # Перезаписываем порядок игроков
    session.players = turn_order
    session.current_turn_index = 0
    session.description_round = 1

    await send_auto_hints(session, bot, session.description_round)

    first_player = get_next_player(session)
    if not first_player:
        return

    round_hint = "⚠️ Первый раунд — говори максимально обобщённо!"

    msg = await message.answer(f"""
📝 <b>РАУНД 1</b> — описания

{round_hint}

🗣️ <b>{html.escape(first_player.full_name)}</b>, твоя очередь!
   Назови 1 признак вслух. Имя не называй!
""".strip(), reply_markup=i_said_keyboard(session.chat_id))

    # Уведомление в ЛС (без кнопки)
    try:
        await bot.send_message(
            first_player.user_id,
            f"🎯 <b>Твоя очередь!</b>\n\n"
            f"{round_hint}{_get_role_hint(first_player)}\n\n"
            f"Скажи признак ВСЛУХ, затем нажми кнопку в группе."
        )
    except Exception as e:
        logger.warning("Не удалось уведомить игрока (id=%d): %s", first_player.user_id, e)

    await lobby_service.persist_session(session)


async def _start_questioning_phase(message: Message, session):
    """Начать фазу вопросов."""
    import random
    random.shuffle(session.players)
    first_player = session.players[0] if session.players else None
    if first_player:
        session.current_turn_index = 0
        await message.answer(
            f"""
❓ <b>ВОПРОСЫ</b> — раунд {session.questions_round}

👤 <b>{html.escape(first_player.full_name)}</b>, выбери кому задать вопрос.
Вопрос — да/нет.
""".strip(),
            reply_markup=question_target_keyboard(
                session.chat_id, session.players, first_player.user_id
            ),
        )


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery):
    """Отмена игры."""
    chat_id = callback.message.chat.id
    session = lobby_service.get_session(chat_id)
    if not session or not _can_control(session, callback.from_user.id, callback.from_user.username):
        await callback.answer("🔒 Только создатель или админ может отменить игру.", show_alert=True)
        return
    await _cancel_turn_timer(chat_id)
    _reroll_votes.pop(chat_id, None)
    _cancel_votes.pop(chat_id, None)
    session.state = GameState.FINISHED
    await lobby_service.end_session(chat_id)
    await callback.answer("🗑️ Отменено.")
    await callback.message.edit_text("🗑️ <b>Игра отменена.</b>\n\nНовая игра: /spy", reply_markup=play_again_keyboard())


@router.message(Command("stop"))
async def cmd_stop(message: Message):
    """Остановка игры."""
    chat_id = message.chat.id
    session = lobby_service.get_session(chat_id)
    if not session:
        await message.answer("❌ Нет активной игры.")
        return
    if not _can_control(session, message.from_user.id, message.from_user.username):
        await message.answer("🔒 Только создатель или админ может остановить.")
        return
    await _cancel_turn_timer(chat_id)
    _reroll_votes.pop(chat_id, None)
    _cancel_votes.pop(chat_id, None)
    session.state = GameState.FINISHED
    await lobby_service.end_session(chat_id)
    await message.answer("🛑 <b>Игра остановлена.</b>", reply_markup=play_again_keyboard())


@router.message(Command("status"))
async def cmd_status(message: Message):
    """Статус текущей игры."""
    chat_id = message.chat.id
    session = lobby_service.get_session(chat_id)
    
    if not session:
        await message.answer(
            f"📋 <b>Статус:</b> нет активной игры\nСоздайте: /spy"
        )
        return
    
    # Определяем фазу
    state_names = {
        GameState.LOBBY: "🎮 Лобби (набор игроков)",
        GameState.ROLE_DISTRIBUTION: "📩 Раздача ролей",
        GameState.DESCRIBING: "📝 Фаза описаний",
        GameState.QUESTIONING: "❓ Фаза вопросов",
        GameState.DISCUSSION: "🗣️ Обсуждение",
        GameState.VOTING: "🗳️ Голосование",
        GameState.FINISHED: "🏁 Игра завершена",
    }
    state_text = state_names.get(session.state, str(session.state))
    
    # Создатель
    creator = session.get_player(session.creator_id)
    creator_name = creator.full_name if creator else "???"
    
    # Настройки
    game_type_map = {
        GameType.CLASSIC: "📝 Классика",
        GameType.QUESTIONS: "❓ Вопросы",
        GameType.NO_TRAITORS: "👤 Все мирные",
        GameType.ALL_TRAITORS: "🕵️ Все шпионы",
        GameType.BLIND_SPY: "🎭 Слепой шпион",
    }
    game_type_text = game_type_map.get(session.game_type, "📝 Классика")
    cat_name_text = get_category_name(session.categories)
    
    await message.answer(f"""
📋 <b>СТАТУС</b>

🎯 {state_text}
👑 {creator_name}
👥 Игроков: {len(session.players)}
🕵️ Шпионов: {session.spy_count}
📂 {cat_name_text}  •  🎯 {game_type_text}  •  🤡 Провокатор: {"да" if session.provocateur_enabled else "нет"}
""".strip())


@router.message(Command("players"))
async def cmd_players(message: Message):
    """Список игроков."""
    chat_id = message.chat.id
    session = lobby_service.get_session(chat_id)
    
    if not session:
        await message.answer("❌ Нет активной игры.")
        return
    
    if not session.players:
        await message.answer("👥 Пока нет игроков.")
        return
    
    players_list = []
    for i, p in enumerate(session.players, 1):
        role_emoji = ""
        if session.state != GameState.LOBBY and p.role:
            # Не показываем роли во время игры!
            role_emoji = " 👑" if p.is_creator else ""
        else:
            role_emoji = " 👑" if p.is_creator else ""
        players_list.append(f"   {i}. {html.escape(p.full_name)}{role_emoji}")
    
    await message.answer(f"""
👥 <b>ИГРОКИ</b> ({len(session.players)})

{chr(10).join(players_list)}

👑 — создатель
""".strip())


@router.message(Command("join"))
async def cmd_join(message: Message):
    """Присоединиться к игре через команду."""
    if not check_rate_limit(message.from_user.id, cooldown=2.0):
        await message.answer("⏳ Слишком часто. Подожди.")
        return
    chat_id = message.chat.id
    session = lobby_service.get_session(chat_id)
    
    if not session:
        await message.answer(
            "❌ Нет активной игры.\nСоздайте: /spy"
        )
        return
    
    if session.state != GameState.LOBBY:
        await message.answer("⏳ Игра уже началась, присоединиться нельзя.")
        return
    
    user = message.from_user
    ok = lobby_service.add_player(session, user.id, user.username or "", user.full_name)
    
    if not ok:
        await message.answer("⚠️ Вы уже в игре или лобби заполнено.")
        return
    
    await message.answer(f"✅ <b>{html.escape(user.full_name)}</b> присоединился к игре!")


@router.message(Command("kick"))
async def cmd_kick(message: Message):
    """Исключить игрока из игры."""
    chat_id = message.chat.id
    session = lobby_service.get_session(chat_id)
    
    if not session:
        await message.answer("❌ Нет активной игры.")
        return
    
    if not _can_control(session, message.from_user.id, message.from_user.username):
        await message.answer("🔒 Только создатель или админ может исключать игроков.")
        return
    
    # Проверяем, есть ли реплай на сообщение
    if not message.reply_to_message:
        await message.answer(
            "👢 <b>Как исключить игрока:</b>\n\n"
            "Ответьте на сообщение игрока командой /kick"
        )
        return
    
    target_id = message.reply_to_message.from_user.id
    target_name = message.reply_to_message.from_user.full_name
    
    if target_id == session.creator_id:
        await message.answer("❌ Нельзя исключить создателя игры.")
        return
    
    player = session.get_player(target_id)
    if not player:
        await message.answer("❌ Этот пользователь не в игре.")
        return
    
    # Удаляем игрока
    was_in_game = session.state != GameState.LOBBY
    session.players = [p for p in session.players if p.user_id != target_id]
    if target_id == session.creator_id and session.players:
        session.players[0].is_creator = True
        session.creator_id = session.players[0].user_id
    # Чистим голоса за кикнутого и голоса кикнутого
    for p in session.players:
        if p.vote_for == target_id:
            p.vote_for = None
    _cancel_votes.pop(chat_id, None)
    await message.answer(f"👢 <b>{html.escape(target_name)}</b> исключён из игры.")
    if was_in_game:
        await message.answer(f"🚪 <b>{html.escape(target_name)}</b> выбывает из игры.")


@router.message(Command("addchar"))
async def cmd_addchar(message: Message):
    """Добавить кастомного персонажа (только для админа)."""
    if not is_admin(message.from_user.username):
        await message.answer(f"🔒 Только админ @{ADMIN_USERNAME} может управлять персонажами.")
        return
    
    args = message.text.split(maxsplit=1)
    
    if len(args) < 2:
        await message.answer(
            "✨ <b>Добавление персонажа</b>\n\n"
            "Использование:\n"
            "<code>/addchar Имя Персонажа</code>\n\n"
            "Пример:\n"
            "<code>/addchar Саша из соседнего подъезда</code>"
        )
        return
    
    character = args[1].strip()
    if len(character) < 2:
        await message.answer("❌ Имя персонажа слишком короткое.")
        return
    
    if len(character) > 50:
        await message.answer("❌ Имя персонажа слишком длинное (макс. 50 символов).")
        return
    
    if add_custom_character(character):
        count = len(get_custom_characters())
        await message.answer(
            f"✅ Персонаж <b>{html.escape(character)}</b> добавлен!\n\n"
            f"✨ Всего кастомных персонажей: {count}\n\n"
            f"💡 Они появятся в категории «Кастомные» и в «Все категории»."
        )
    else:
        await message.answer(f"⚠️ Персонаж <b>{html.escape(character)}</b> уже существует!")


@router.message(Command("delchar"))
async def cmd_delchar(message: Message):
    """Удалить кастомного персонажа (только для админа)."""
    if not is_admin(message.from_user.username):
        await message.answer(f"🔒 Только админ @{ADMIN_USERNAME} может управлять персонажами.")
        return
    
    args = message.text.split(maxsplit=1)
    
    if len(args) < 2:
        chars = get_custom_characters()
        if not chars:
            await message.answer(
                "✨ <b>Удаление персонажа</b>\n\n"
                "Нет кастомных персонажей для удаления.\n"
                "Добавьте их командой /addchar"
            )
            return
        
        chars_list = "\n".join([f"   • {c}" for c in chars[:20]])
        if len(chars) > 20:
            chars_list += f"\n   ... и ещё {len(chars) - 20}"
        
        await message.answer(
            f"✨ <b>Удаление персонажа</b>\n\n"
            f"Использование:\n"
            f"<code>/delchar Имя Персонажа</code>\n\n"
            f"Текущие персонажи:\n{chars_list}"
        )
        return
    
    character = args[1].strip()
    
    if remove_custom_character(character):
        count = len(get_custom_characters())
        await message.answer(
            f"🗑️ Персонаж <b>{html.escape(character)}</b> удалён!\n\n"
            f"✨ Осталось кастомных персонажей: {count}"
        )
    else:
        await message.answer(f"❌ Персонаж <b>{html.escape(character)}</b> не найден в кастомных.")


@router.message(Command("listchars"))
async def cmd_listchars(message: Message):
    """Показать список кастомных персонажей."""
    chars = get_custom_characters()
    
    if not chars:
        await message.answer(
            "✨ <b>Кастомные персонажи</b>\n\n"
            "Список пуст.\n\n"
            "Добавьте персонажей командой:\n"
            "<code>/addchar Имя Персонажа</code>"
        )
        return
    
    chars_list = "\n".join([f"   {i}. {c}" for i, c in enumerate(chars, 1)])
    
    await message.answer(f"""
✨ <b>КАСТОМНЫЕ ПЕРСОНАЖИ</b> ({len(chars)})

{chars_list}

💡 /addchar Имя | /delchar Имя | /clearchars
""".strip())


@router.message(Command("clearchars"))
async def cmd_clearchars(message: Message):
    """Очистить все кастомные персонажи (только для админа)."""
    if not is_admin(message.from_user.username):
        await message.answer(f"🔒 Только админ @{ADMIN_USERNAME} может управлять персонажами.")
        return
    
    chars = get_custom_characters()
    
    if not chars:
        await message.answer("✨ Список кастомных персонажей уже пуст.")
        return
    
    count = len(chars)
    clear_custom_characters()
    await message.answer(f"🗑️ Удалено <b>{count}</b> кастомных персонажей.")


# ═══════════════════════════════════════════════════════════════
# 🔄 ПЕРЕВЫБОР ПЕРСОНАЖА
# ═══════════════════════════════════════════════════════════════

_reroll_votes: dict[int, set[int]] = {}  # chat_id -> set of user_ids who voted yes
_cancel_votes: dict[int, set[int]] = {}  # chat_id -> set of user_ids who voted to cancel
_skip_pause: dict[int, set[int]] = {}  # chat_id -> set of user_ids who voted to skip pause

# Таймеры авто-пропуска хода
_turn_timers: dict[int, asyncio.Task] = {}  # chat_id -> timer task


async def _cancel_turn_timer(chat_id: int):
    """Отменяет таймер авто-пропуска для чата."""
    task = _turn_timers.pop(chat_id, None)
    if task and not task.done():
        task.cancel()


async def _start_turn_timer(chat_id: int, session, bot: Bot, message, timeout: int = 20):
    """Запускает таймер авто-пропуска хода. Если игрок не нажал «Я сказал» — пропускаем."""
    await _cancel_turn_timer(chat_id)

    async def _auto_skip():
        try:
            await asyncio.sleep(timeout)
            s = lobby_service.get_session(chat_id)
            if not s or s.state != GameState.DESCRIBING:
                return
            current = get_next_player(s)
            if current and not current.has_described:
                await bot.send_message(chat_id,
                    f"⏰ <b>{html.escape(current.full_name)}</b> не ответил — пропускаем ход."
                )
                # Эмулируем нажатие «Я сказал»
                await _do_i_said(chat_id, current.user_id, bot, message)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("Ошибка в таймере хода чата %d: %s", chat_id, e)
        finally:
            _turn_timers.pop(chat_id, None)

    _turn_timers[chat_id] = asyncio.create_task(_auto_skip())


async def _do_i_said(chat_id: int, user_id: int, bot: Bot, message):
    """Обрабатывает завершение хода игрока (нажал или авто-пропуск)."""
    from bot.keyboards.inline import i_said_keyboard

    session = lobby_service.get_session(chat_id)
    if not session or session.state != GameState.DESCRIBING:
        return

    player = session.get_player(user_id)
    if not player:
        return

    current = get_next_player(session)
    if not current or current.user_id != user_id:
        return

    if current.has_described:
        return

    current.has_described = True
    session.current_turn_index += 1
    update_session_activity(session)

    await bot.send_message(chat_id, f"✅ <b>{html.escape(current.full_name)}</b> сказал!")

    if check_all_described(session):
        await _cancel_turn_timer(chat_id)
        session.state = GameState.DISCUSSION
        await lobby_service.persist_session(session)

        total = len(session.players)
        skip_needed = int(total * 0.75) + 1
        _skip_pause[chat_id] = set()
        from bot.keyboards.inline import skip_pause_keyboard
        pause_msg = await bot.send_message(chat_id,
            f"🎉 <b>Раунд завершён!</b> Пауза 2 минуты.\n\n⏩ Пропустить: 0/{skip_needed}",
            reply_markup=skip_pause_keyboard(chat_id),
        )
        for _ in range(120):
            await asyncio.sleep(1)
            votes = _skip_pause.get(chat_id, set())
            if len(votes) >= skip_needed:
                break
        _skip_pause.pop(chat_id, None)
        try:
            await pause_msg.edit_text("🎉 <b>Раунд завершён!</b>")
        except Exception:
            pass

        session = lobby_service.get_session(chat_id)
        if not session or session.state != GameState.DISCUSSION:
            return

        await bot.send_message(chat_id, """
⏰ <b>Что дальше?</b>

🗳️ Голосовать — выбрать шпиона
▶️ Следующий раунд — ещё описания
""".strip(), reply_markup=round_end_keyboard(chat_id))
        return

    next_player = get_next_player(session)
    if next_player:
        round_hint = "⚠️ Говори максимально обобщённо!" if session.description_round <= 2 else ""
        msg = await bot.send_message(chat_id,
            f"🗣️ <b>{html.escape(next_player.full_name)}</b>, говори! 1 признак вслух."
            + (f"\n{round_hint}" if round_hint else ""),
            reply_markup=i_said_keyboard(chat_id),
        )
        try:
            await bot.send_message(next_player.user_id,
                f"🎯 <b>Твоя очередь!</b>"
                + (f"\n\n{round_hint}" if round_hint else "")
                + _get_role_hint(next_player)
                + "\n\nСкажи вслух и жми кнопку в группе."
            )
        except Exception as e:
            logger.warning("Не удалось уведомить игрока (id=%d): %s", next_player.user_id, e)

    await lobby_service.persist_session(session)


@router.message(Command("reroll"))
async def cmd_reroll(message: Message, bot: Bot):
    """Начать голосование за смену персонажа."""
    chat_id = message.chat.id
    session = lobby_service.get_session(chat_id)
    if not session or session.state in (GameState.LOBBY, GameState.FINISHED):
        await message.answer("❌ Игра не активна.")
        return
    if not session.get_player(message.from_user.id):
        await message.answer("❌ Ты выбыл из игры.")
        return
    if session.host_mode:
        await message.answer("👤 Режим ведущего: ведущий может сменить персонажа в ЛС.")
        return

    # Начинаем голосование
    _reroll_votes[chat_id] = {message.from_user.id}
    total = len(session.players)
    await message.answer(
        f"🔄 <b>Сменить персонажа?</b>\n\n"
        f"Текущий: <code>{html.escape(session.character)}</code>\n\n"
        f"{html.escape(message.from_user.full_name)} предлагает сменить персонажа.\n"
        f"Нужно больше половины голосов ({total // 2 + 1}).\n\n"
        f"Нажми ✅ За, чтобы проголосовать.",
        reply_markup=reroll_keyboard(chat_id)
    )


async def _reroll_character(session, bot: Bot, chat_id: int):
    """Меняет персонажа на нового из тех же категорий."""
    import random as _random
    from bot.config import get_characters_by_category
    chars = get_characters_by_category(session.categories)
    if not chars:
        await bot.send_message(chat_id, "❌ Нет персонажей в категории. Смена невозможна.")
        return

    old = session.character
    new = _random.choice([c for c in chars if c != old]) if len(chars) > 1 else chars[0]
    session.character = new

    # Обновляем роли с новым персонажем и шлём ЛС
    for p in session.players:
        if p.role == Role.CIVILIAN:
            try:
                await bot.send_message(
                    p.user_id,
                    f"🔄 <b>Персонаж сменён!</b>\n\nНовый: <code>{html.escape(session.character)}</code>"
                )
            except Exception as e:
                logger.warning("Не удалось уведомить CIVILIAN %d: %s", p.user_id, e)
        elif p.role == Role.CONFUSED:
            other_chars = [c for c in chars if c != new]
            p.alt_character = _random.choice(other_chars) if other_chars else new
            try:
                await bot.send_message(
                    p.user_id,
                    f"🔄 <b>Персонаж сменён!</b>\n\nНовый: <code>{html.escape(p.alt_character)}</code>"
                )
            except Exception as e:
                logger.warning("Не удалось уведомить CONFUSED %d: %s", p.user_id, e)
        elif p.role == Role.PROVOCATEUR:
            other_chars = [c for c in chars if c != new]
            p.fake_character = _random.choice(other_chars) if other_chars else "???"
            try:
                await bot.send_message(
                    p.user_id,
                    f"🔄 <b>Персонаж сменён!</b>\n\nНовый: <code>{html.escape(p.fake_character)}</code>"
                )
            except Exception as e:
                logger.warning("Не удалось уведомить PROVOCATEUR %d: %s", p.user_id, e)
        elif p.role == Role.SPY:
            try:
                await bot.send_message(
                    p.user_id,
                    "🔄 <b>Персонаж сменён!</b>\n\nСлушай новые описания."
                )
            except Exception as e:
                logger.warning("Не удалось уведомить SPY %d: %s", p.user_id, e)

    await bot.send_message(chat_id,
        f"🔄 <b>Персонаж сменён!</b>\n\n"
        f"Был: <code>{html.escape(old)}</code>\n"
        f"Стал: <code>{html.escape(new)}</code>\n\n"
        f"Роли обновлены. Проверьте ЛС!"
    )

    _reroll_votes.pop(chat_id, None)
    update_session_activity(session)
    await lobby_service.persist_session(session)


@router.callback_query(F.data.startswith("reroll_yes_"))
async def cb_reroll_vote(callback: CallbackQuery, bot: Bot):
    """Голос за смену персонажа."""
    try:
        chat_id = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        await callback.answer("❌ Ошибка данных.", show_alert=True)
        return
    session = lobby_service.get_session(chat_id)
    if not session:
        await callback.answer("⏳ Игры нет.", show_alert=True)
        return

    if not session.get_player(callback.from_user.id):
        await callback.answer("❌ Ты не в игре", show_alert=True)
        return

    votes = _reroll_votes.get(chat_id, set())
    votes.add(callback.from_user.id)
    _reroll_votes[chat_id] = votes

    total = len(session.players)
    needed = total // 2 + 1

    await callback.answer(f"✅ Голос принят ({len(votes)}/{needed})")

    if len(votes) >= needed:
        await callback.message.edit_text(
            f"🔄 <b>Персонаж меняется!</b>\n\nГолосов: {len(votes)}/{needed}"
        )
        await _reroll_character(session, bot, chat_id)
    else:
        await callback.message.edit_text(
            f"🔄 <b>Сменить персонажа?</b>\n\nТекущий: <code>{html.escape(session.character)}</code>\n\n"
            f"Голосов: {len(votes)}/{needed}\n\nНажми ✅ За.",
            reply_markup=reroll_keyboard(chat_id)
        )


@router.message(Command("help"))
async def cmd_help_group(message: Message):
    """Помощь в группе."""
    await message.answer(f"""
❓ <b>КОМАНДЫ</b>

🎮 <b>Игра:</b>
/spy — создать | /join — войти | /stop — остановить
/status — статус | /players — список | /kick — кикнуть (реплай)

🗳️ <b>В игре:</b>
/vote — голосование | /reroll — сменить персонажа

✨ <b>Персонажи (админ):</b>
/addchar Имя | /delchar Имя | /listchars | /clearchars

🕵️ <b>Шпион в ЛС:</b>
/guess Имя — угадать | /hint — подсказка
""".strip())


# ═══════════════════════════════════════════════════════════════
# 📝 ФАЗА ОПИСАНИЙ (IRL — бот координирует голосовые описания)
# ═══════════════════════════════════════════════════════════════

def _get_role_hint(player) -> str:
    """Подсказка по роли для ЛС."""
    if player.role == Role.SPY:
        return "\n\n🕵️ Ты шпион — придумай что-то правдоподобное!"
    elif player.role == Role.PROVOCATEUR:
        return f"\n\n🤡 Твой персонаж: {html.escape(player.fake_character)}"
    elif player.role == Role.CONFUSED:
        return f"\n\n👤 Твой персонаж: {html.escape(player.alt_character)}"
    return ""


@router.callback_query(F.data.startswith("next_round_"))
async def cb_next_round(callback: CallbackQuery, bot: Bot):
    """Начать следующий раунд описаний."""
    try:
        chat_id = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        await callback.answer("❌ Ошибка данных.", show_alert=True)
        return
    session = lobby_service.get_session(chat_id)
    if not session:
        await callback.answer("⏳ Этой игры больше нет.", show_alert=True)
        return

    if session.state != GameState.DISCUSSION:
        await callback.answer("❌ Не сейчас", show_alert=True)
        return

    # Сбрасываем описания для нового раунда
    for p in session.players:
        p.has_described = False
    session.current_turn_index = 0
    session.description_round += 1
    session.state = GameState.DESCRIBING

    await callback.answer("▶️ Следующий раунд!")

    round_hint = "⚠️ Говори максимально обобщённо!" if session.description_round <= 2 else "💡 Можно конкретнее!"

    first_player = get_next_player(session)
    if not first_player:
        return

    from bot.keyboards.inline import i_said_keyboard
    msg = await bot.send_message(chat_id, f"""
📝 <b>РАУНД {session.description_round}</b>

{round_hint}

🗣️ <b>{html.escape(first_player.full_name)}</b>, говори! Назови 1 признак вслух.
""".strip(), reply_markup=i_said_keyboard(chat_id))

    # Уведомление в ЛС
    try:
        await bot.send_message(
            first_player.user_id,
            f"🎯 <b>Раунд {session.description_round} — твоя очередь!</b>\n\n"
            f"{round_hint}{_get_role_hint(first_player)}\n\n"
            f"Скажи признак ВСЛУХ, затем нажми кнопку в группе."
        )
    except Exception as e:
        logger.warning("Не удалось уведомить игрока (id=%d): %s", first_player.user_id, e)

    await send_auto_hints(session, bot, session.description_round)
    await lobby_service.persist_session(session)


@router.callback_query(F.data.startswith("i_said_"))
async def cb_i_said_group(callback: CallbackQuery, bot: Bot):
    """Игрок нажал «Я сказал» в группе."""
    if not check_rate_limit(callback.from_user.id, cooldown=1.0):
        await callback.answer("⏳ Слишком быстро.", show_alert=True)
        return
    try:
        chat_id = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        await callback.answer("❌ Ошибка данных.", show_alert=True)
        return
    session = lobby_service.get_session(chat_id)
    if not session or session.state != GameState.DESCRIBING:
        await callback.answer("❌ Сейчас не фаза описаний.", show_alert=True)
        return

    user_id = callback.from_user.id
    player = session.get_player(user_id)
    if not player:
        await callback.answer("❌ Ты не в этой игре.", show_alert=True)
        return

    if player.has_described:
        await callback.answer("✅ Уже принято.")
        return

    current = get_next_player(session)
    if not current or current.user_id != user_id:
        await callback.answer("⏳ Сейчас не твоя очередь.", show_alert=True)
        return

    if current.has_described:
        await callback.answer("✅ Ты уже сказал.", show_alert=True)
        return

    await _cancel_turn_timer(chat_id)
    await callback.answer("✅ Принято!")
    await _do_i_said(chat_id, user_id, bot, callback.message)


# ═══════════════════════════════════════════════════════════════
# ❓ ФАЗА ВОПРОСОВ
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ask_"))
async def cb_ask_question(callback: CallbackQuery, bot: Bot):
    """Выбор кому задать вопрос."""
    parts = callback.data.split("_")
    chat_id = int(parts[1])
    target_id = int(parts[2])
    
    session = lobby_service.get_session(chat_id)
    if not session or session.state != GameState.QUESTIONING:
        await callback.answer("❌ Сейчас не фаза вопросов.", show_alert=True)
        return
    
    asker = session.get_player(callback.from_user.id)
    target = session.get_player(target_id)
    if not asker or not target:
        await callback.answer("❌ Игрок не найден.", show_alert=True)
        return
    
    # Проверяем очередь
    if not session.players:
        return
    current_player = session.players[session.current_turn_index % len(session.players)]
    if current_player.user_id != callback.from_user.id:
        await callback.answer("⏳ Сейчас не твоя очередь!", show_alert=True)
        return
    
    session.current_question_target = target_id
    
    await callback.answer()
    await callback.message.edit_text(
        f"❓ <b>{html.escape(asker.full_name)}</b> задаёт вопрос игроку <b>{html.escape(target.full_name)}</b>\n\n"
        f"💬 <b>{html.escape(asker.full_name)}</b>, напиши свой вопрос в чат!\n"
        f"(вопрос должен быть на да/нет)"
    )
    
    try:
        await bot.send_message(
            target.user_id,
            f"❓ <b>{html.escape(asker.full_name)}</b> спрашивает тебя...",
            reply_markup=yes_no_keyboard(chat_id)
        )
    except Exception as e:
        logger.warning("Не удалось отправить клавиатуру да/нет (id=%d): %s", target.user_id, e)


@router.callback_query(F.data.startswith("answer_"))
async def cb_answer_question(callback: CallbackQuery):
    """Ответ на вопрос."""
    parts = callback.data.split("_")
    chat_id = int(parts[1])
    answer = parts[2]
    
    session = lobby_service.get_session(chat_id)
    if not session or session.state != GameState.QUESTIONING:
        await callback.answer("❌ Сейчас не фаза вопросов.", show_alert=True)
        return
    
    if session.current_question_target != callback.from_user.id:
        await callback.answer("❌ Вопрос задан не тебе!", show_alert=True)
        return
    
    responder = session.get_player(callback.from_user.id)
    
    answer_text = {"yes": "✅ ДА", "no": "❌ НЕТ", "maybe": "🤷 Сложно сказать"}.get(answer, "❓ Неизвестно")
    
    await callback.answer()
    await callback.message.edit_text(
        f"💬 <b>{html.escape(responder.full_name)}</b> отвечает: {html.escape(answer_text)}"
    )
    
    # Следующий игрок
    session.current_turn_index += 1
    session.current_question_target = None
    
    # Проверяем, прошёл ли раунд
    if session.current_turn_index >= len(session.players):
        session.current_turn_index = 0
        session.questions_round += 1
        
        if session.questions_round > 2:  # 2 раунда вопросов
            session.state = GameState.DISCUSSION
            await callback.message.answer(f"""
❓ <b>Вопросы закончились!</b>

Обсуждайте голосом. Шпион: /guess Имя
Готовы голосовать? Жмите кнопку.
""".strip(),
                reply_markup=start_vote_keyboard(chat_id),
            )
            return
    
    # Следующий вопрос
    if not session.players:
        return
    next_player = session.players[session.current_turn_index % len(session.players)]
    await callback.message.answer(
        f"❓ <b>РАУНД {session.questions_round}</b>\n\n"
        f"👤 <b>{html.escape(next_player.full_name)}</b>, выбери кому задать вопрос:",
        reply_markup=question_target_keyboard(chat_id, session.players, next_player.user_id),
    )


# ═══════════════════════════════════════════════════════════════
# 🗳️ ГОЛОСОВАНИЕ
# ═══════════════════════════════════════════════════════════════

def _get_not_voted_names(session) -> str:
    """Возвращает строку с именами игроков, которые ещё не проголосовали."""
    not_voted = []
    for p in session.players:
        if p.vote_for is None:
            name = f"@{html.escape(p.username)}" if p.username else html.escape(p.full_name)
            not_voted.append(name)
    if not not_voted:
        return ""
    return "⏳ Ждём: " + ", ".join(not_voted)


@router.message(Command("vote"))
async def cmd_vote(message: Message, bot: Bot):
    if not check_rate_limit(message.from_user.id, cooldown=2.0):
        await message.answer("⏳ Слишком часто. Подожди.")
        return
    session = lobby_service.get_session(message.chat.id)
    if session and not session.get_player(message.from_user.id):
        await message.answer("❌ Ты выбыл из игры.")
        return
    await _start_vote(message.chat.id, bot, message)


@router.callback_query(F.data.startswith("start_vote_"))
async def cb_start_vote(callback: CallbackQuery, bot: Bot):
    try:
        chat_id = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        await callback.answer("❌ Ошибка данных.", show_alert=True)
        return
    await _start_vote(chat_id, bot, callback.message)
    await callback.answer("🗳️ Голосование начато!")


async def _start_vote(chat_id: int, bot: Bot, message):
    session = lobby_service.get_session(chat_id)
    if not session or session.state != GameState.DISCUSSION:
        await message.answer("🗳️ Голосование недоступно.")
        return

    _reroll_votes.pop(chat_id, None)
    session.state = GameState.VOTING
    _cancel_votes.pop(chat_id, None)
    update_session_activity(session)
    total = len(session.players)
    required = int(total * 0.75) + 1
    votes = count_votes(session)
    vote_lines = "\n".join([f"   🎯 {html.escape(p.full_name)}{' 👑' if p.is_creator else ''} — {votes.get(p.user_id, 0)}" for p in session.players])
    waiting = _get_not_voted_names(session)
    await message.answer(
        f"🗳️ <b>ГОЛОСОВАНИЕ</b>\n\n{vote_lines}\n\nНужно >75% голосов ({required}/{total}) для раскрытия.\n{waiting}\n\nКто шпион? Жми на имя:",
        reply_markup=vote_keyboard(chat_id, session.players, votes),
    )


async def _reset_votes(session):
    """Сбрасывает голоса и переводит в обсуждение."""
    for p in session.players:
        p.vote_for = None
    session.state = GameState.DISCUSSION
    _cancel_votes.pop(session.chat_id, None)
    update_session_activity(session)
    await lobby_service.persist_session(session    )


@router.callback_query(F.data.startswith("skip_pause_"))
async def cb_skip_pause(callback: CallbackQuery):
    try:
        chat_id = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        await callback.answer("❌ Ошибка данных.", show_alert=True)
        return
    votes = _skip_pause.get(chat_id)
    if votes is None:
        await callback.answer("⏳ Пауза уже закончилась.", show_alert=True)
        return
    votes.add(callback.from_user.id)
    total = len(lobby_service.get_session(chat_id).players) if lobby_service.get_session(chat_id) else 1
    skip_needed = int(total * 0.75) + 1
    await callback.answer(f"⏩ Принято ({len(votes)}/{skip_needed})")


@router.callback_query(F.data.startswith("cancel_vote_"))
async def cb_cancel_vote(callback: CallbackQuery, bot: Bot):
    try:
        chat_id = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        await callback.answer("❌ Ошибка данных.", show_alert=True)
        return
    session = lobby_service.get_session(chat_id)
    if not session or session.state != GameState.VOTING:
        await callback.answer("🗳️ Голосование неактивно.", show_alert=True)
        return

    user_id = callback.from_user.id
    if not session.get_player(user_id):
        await callback.answer("❌ Ты не в игре.", show_alert=True)
        return

    cancels = _cancel_votes.get(chat_id, set())
    cancels.add(user_id)
    _cancel_votes[chat_id] = cancels

    total = len(session.players)
    needed = total // 2 + 1

    await callback.answer(f"❌ Голос за отмену ({len(cancels)}/{needed})")

    if len(cancels) >= needed:
        _cancel_votes.pop(chat_id, None)
        await _reset_votes(session)
        await callback.message.edit_text("🗳️ <b>Голосование отменено.</b> Голоса сброшены.")
    else:
        votes = count_votes(session)
        vote_lines = "\n".join([f"   🎯 {html.escape(p.full_name)}{' 👑' if p.is_creator else ''} — {votes.get(p.user_id, 0)}" for p in session.players])
        waiting = _get_not_voted_names(session)
        await callback.message.edit_text(
            f"🗳️ <b>Голосование</b>\n\n{vote_lines}\n\n"
            f"❌ За отмену: {len(cancels)}/{needed}\n{waiting}",
            reply_markup=vote_keyboard(chat_id, session.players, votes),
        )


@router.callback_query(F.data.startswith("vote_"))
async def cb_vote(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split("_")
    if len(parts) != 3:
        await callback.answer("❌ Ошибка данных.")
        return
    chat_id = int(parts[1])
    target_id = int(parts[2])

    session = lobby_service.get_session(chat_id)
    if not session or session.state != GameState.VOTING:
        await callback.answer("🗳️ Голосование неактивно.", show_alert=True)
        return

    voter = session.get_player(callback.from_user.id)
    target = session.get_player(target_id)
    if not voter or not target:
        await callback.answer("⚠️ Вы или цель не в игре.", show_alert=True)
        return
    if voter.user_id == target_id:
        await callback.answer("❌ Нельзя голосовать за себя!", show_alert=True)
        return

    # Разрешаем переголосовать
    changed = voter.vote_for is not None and voter.vote_for != target_id
    voter.vote_for = target_id
    if changed:
        await callback.answer(f"🔄 Переголосовал за {html.escape(target.full_name)}")
    else:
        await callback.answer(f"🗳️ Вы проголосовали за {html.escape(target.full_name)}")

    result = process_vote_result(session)

    if result is None:
        total = len(session.players)
        voted = sum(1 for p in session.players if p.vote_for is not None)
        required = int(total * 0.75) + 1  # >75%
        votes = count_votes(session)
        vote_lines = "\n".join([f"   🎯 {html.escape(p.full_name)}{' 👑' if p.is_creator else ''} — {votes.get(p.user_id, 0)}" for p in session.players])
        waiting = _get_not_voted_names(session)
        if voted < total:
            await callback.message.edit_text(
                f"🗳️ <b>Голосование</b> ({voted}/{total}) — нужно >75% ({required})\n\n{vote_lines}\n{waiting}",
                reply_markup=vote_keyboard(chat_id, session.players, votes),
            )
        else:
            await callback.message.edit_text(
                f"🗳️ <b>Голосование</b> ({voted}/{total}) — все проголосовали, консенсуса нет."
            )
            await _reset_votes(session)
        return

    outcome = result["outcome"]
    target_name = result["target"].full_name

    if session.game_type == GameType.ALL_TRAITORS:
        import random as _rand
        target_player = result["target"]
        session.players = [p for p in session.players if p.user_id != target_player.user_id]
        if target_player.user_id == session.creator_id and session.players:
            session.players[0].is_creator = True
            session.creator_id = session.players[0].user_id
        remaining = len(session.players)
        if _rand.random() < 0.5:
            await bot.send_message(chat_id,
                f"👤 <b>МИМО!</b>\n\n"
                f"Большинство проголосовало за <b>{html.escape(target_name)}</b> — он мирный.\n"
                f"🚪 <b>{html.escape(target_name)}</b> выбывает из игры.\nГолоса сброшены. Думайте дальше."
            )
        else:
            await bot.send_message(chat_id,
                f"🕵️ <b>ШПИОН ПОЙМАН!</b>\n\n"
                f"<b>{html.escape(target_name)}</b> — шпион. "
                f"Но остал{'ся' if remaining == 1 else 'ось'} ещё {remaining}!\n"
                f"Голоса сброшены. Продолжайте."
            )
        if len(session.players) <= 1:
            await bot.send_message(chat_id,
                f"🏁 Игра окончена. Персонаж: <code>{html.escape(session.character)}</code>",
                reply_markup=play_again_keyboard()
            )
            await record_stats(session, civilians_won=False)
            session.state = GameState.FINISHED
            await lobby_service.end_session(chat_id)
            return
        await _reset_votes(session)
        return

    if outcome == "civilian_caught":
        target_player = result["target"]
        session.players = [p for p in session.players if p.user_id != target_player.user_id]
        if target_player.user_id == session.creator_id and session.players:
            session.players[0].is_creator = True
            session.creator_id = session.players[0].user_id
        await bot.send_message(chat_id,
            f"👤 <b>МИМО!</b>\n\nБольшинство проголосовало за <b>{html.escape(target_name)}</b> — он мирный.\n"
            f"🚪 <b>{html.escape(target_name)}</b> выбывает из игры.\nГолоса сброшены. Думайте дальше."
        )
        await _reset_votes(session)
        spies_team = sum(1 for p in session.players if p.role in (Role.SPY, Role.PROVOCATEUR))
        civs_team = sum(1 for p in session.players if p.role in (Role.CIVILIAN, Role.CONFUSED))
        actual_spies = sum(1 for p in session.players if p.role == Role.SPY)
        if spies_team >= civs_team and actual_spies > 0:
            if session.game_type == GameType.NO_TRAITORS:
                await bot.send_message(chat_id, "👤 Игра окончена. Шпионов не было.", reply_markup=play_again_keyboard())
            else:
                await bot.send_message(chat_id, "🕵️ <b>ШПИОНЫ ПОБЕДИЛИ!</b> Большинство за шпионами.", reply_markup=play_again_keyboard())
                await record_stats(session, civilians_won=False)
            session.state = GameState.FINISHED
            await lobby_service.end_session(chat_id)
            return

    elif outcome == "provocateur_caught":
        target_player = result["target"]
        session.players = [p for p in session.players if p.user_id != target_player.user_id]
        if target_player.user_id == session.creator_id and session.players:
            session.players[0].is_creator = True
            session.creator_id = session.players[0].user_id
        await bot.send_message(chat_id,
            f"🤡 <b>ПРОВОКАТОР!</b>\n\nБольшинство за <b>{html.escape(target_name)}</b> — это провокатор.\n"
            f"🚪 <b>{html.escape(target_name)}</b> выбывает из игры.\nГолоса сброшены."
        )
        await _reset_votes(session)
        spies_team = sum(1 for p in session.players if p.role in (Role.SPY, Role.PROVOCATEUR))
        civs_team = sum(1 for p in session.players if p.role in (Role.CIVILIAN, Role.CONFUSED))
        actual_spies = sum(1 for p in session.players if p.role == Role.SPY)
        if spies_team >= civs_team and actual_spies > 0:
            if session.game_type == GameType.NO_TRAITORS:
                await bot.send_message(chat_id, "👤 Игра окончена. Шпионов не было.", reply_markup=play_again_keyboard())
            else:
                await bot.send_message(chat_id, "🕵️ <b>ШПИОНЫ ПОБЕДИЛИ!</b> Большинство за шпионами.", reply_markup=play_again_keyboard())
                await record_stats(session, civilians_won=False)
            session.state = GameState.FINISHED
            await lobby_service.end_session(chat_id)
            return

        import random as _rnd
        spies = [p for p in session.players if p.role == Role.SPY]
        for spy in spies:
            hint_type = _rnd.choice(HINT_TYPES)
            hint_text = get_hint_for_spy(session, hint_type)
            try:
                await bot.send_message(spy.user_id,
                    f"💡 <b>Бонусная подсказка</b> — провокатор раскрыт!\n\n{hint_text}"
                )
            except Exception:
                pass
        civs = [p for p in session.players if p.role != Role.SPY]
        for p in civs:
            try:
                await bot.send_message(p.user_id, "🔔 Шпионы получили подсказку.")
            except Exception:
                pass

    elif outcome == "spy_caught_continue":
        caught = result["target"]
        remaining = result["remaining_spies"]
        session.players = [p for p in session.players if p.user_id != caught.user_id]
        if caught.user_id == session.creator_id and session.players:
            session.players[0].is_creator = True
            session.creator_id = session.players[0].user_id
        await bot.send_message(chat_id,
            f"🕵️ <b>ШПИОН ПОЙМАН!</b>\n\n<b>{html.escape(target_name)}</b> — шпион. Но остал{'ся' if remaining == 1 else 'ось'} ещё {remaining}!\nГолоса сброшены. Продолжайте."
        )
        await _reset_votes(session)

    elif outcome == "civilians":
        await _cancel_turn_timer(chat_id)
        await bot.send_message(chat_id,
            f"🎉 <b>МИРНЫЕ ПОБЕДИЛИ!</b>\n\n<b>{html.escape(target_name)}</b> — шпион. Персонаж: <code>{html.escape(session.character)}</code>",
            reply_markup=play_again_keyboard()
        )
        await record_stats(session, civilians_won=True)
        session.state = GameState.FINISHED
        await lobby_service.end_session(chat_id)

    elif outcome == "no_majority":
        await bot.send_message(chat_id,
            "🗳️ Все проголосовали, но шпион не раскрыт. Голоса сброшены."
        )
        await _reset_votes(session)


@router.message(Command("version"))
async def cmd_version_group(message: Message):
    await message.answer("🎭 <b>Шпион</b> v1.3\n\n<a href=\"https://github.com/Moonishe/shpion\">github.com/Moonishe/shpion</a>")
