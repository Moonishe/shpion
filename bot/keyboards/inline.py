from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.config import get_categories


def lobby_keyboard(session=None) -> InlineKeyboardMarkup:
    """Главная клавиатура лобби."""
    from bot.models.game import SettingsMode
    
    buttons = [
        [
            InlineKeyboardButton(text="🎮 Присоединиться", callback_data="join"),
            InlineKeyboardButton(text="🚪 Выйти", callback_data="leave"),
        ],
    ]
    
    # Кнопка выбора ведущего
    if session and session.host_mode:
        host_obj = session.get_player(session.host_id)
        host_name = host_obj.full_name if host_obj else "???"
        buttons.append([
            InlineKeyboardButton(text=f"👤 Ведущий: {host_name}", callback_data="settings_pick_host"),
        ])
    else:
        buttons.append([
            InlineKeyboardButton(text="👤 Назначить ведущего", callback_data="settings_pick_host"),
        ])
    
    buttons.append([
        InlineKeyboardButton(text="⚙️ Режим", callback_data="toggle_settings_mode"),
    ])
    
    # Настройки только для ручного режима
    if session and session.settings_mode == SettingsMode.MANUAL:
        buttons.append([
            InlineKeyboardButton(text="🔧 Настроить игру", callback_data="settings_menu"),
        ])
    
    buttons.extend([
        [
            InlineKeyboardButton(text="📜 Правила", callback_data="rules"),
            InlineKeyboardButton(text="❓ Как играть", callback_data="howto"),
        ],
        [InlineKeyboardButton(text="🚀 Начать игру", callback_data="start_game")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel")],
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def settings_keyboard(session) -> InlineKeyboardMarkup:
    """Меню настроек игры."""
    from bot.config import get_category_name
    from bot.models.game import GameMode, GameType

    # Текущие настройки
    mode_text = "1 шпион" if session.mode == GameMode.ONE_SPY else f"{session.spy_count or 'авто'} шпион(ов)"
    cat_text = get_category_name(session.categories)

    game_type_map = {
        GameType.CLASSIC: "Классика",
        GameType.QUESTIONS: "Вопросы",
        GameType.BLIND_SPY: "Слепой шпион",
    }
    game_type_text = game_type_map.get(session.game_type, "Классика")

    provocateur_text = "ВКЛ" if session.provocateur_enabled else "ВЫКЛ"
    host_text = "👤 Ведущий: да" if session.host_mode else "👤 Без ведущего"
    
    buttons = [
        [InlineKeyboardButton(
            text=f"🕵️ Шпионы: {mode_text}",
            callback_data="settings_spies"
        )],
        [InlineKeyboardButton(
            text=f"📂 Категория: {cat_text}",
            callback_data="settings_category"
        )],
        [InlineKeyboardButton(
            text=f"🎯 Режим: {game_type_text}",
            callback_data="settings_game_type"
        )],
        [InlineKeyboardButton(
            text=f"🤡 Провокатор: {provocateur_text}",
            callback_data="toggle_provocateur"
        )],
        [InlineKeyboardButton(
            text=host_text,
            callback_data="toggle_host_mode"
        )],
    ]
    if session.host_mode:
        buttons.append([InlineKeyboardButton(
            text="🎯 Кто ведущий",
            callback_data="settings_pick_host"
        )])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_lobby")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def spy_count_keyboard() -> InlineKeyboardMarkup:
    """Выбор количества шпионов."""
    rows = [
        [InlineKeyboardButton(text="🕵️ 1 шпион", callback_data="set_spies_1")],
    ]
    
    # Кнопки 2-10 по 3 в ряд
    row = []
    for i in range(2, 11):
        row.append(InlineKeyboardButton(text=str(i), callback_data=f"set_spies_{i}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def category_keyboard(session) -> InlineKeyboardMarkup:
    """Выбор категорий персонажей (toggler)."""
    from bot.models.game import GameSession
    categories = get_categories()
    selected = session.categories if hasattr(session, 'categories') else ["*"]
    
    all_selected = "*" in selected
    all_btn = "☑️ Все категории" if all_selected else "⬜ Все категории"
    
    buttons = [
        [InlineKeyboardButton(text=all_btn, callback_data="toggle_cat_*")],
    ]
    
    for cat_id, cat_data in categories.items():
        if cat_id == "custom":
            continue
        emoji = cat_data.get("emoji", "")
        name = cat_data.get("name", cat_id)
        count = len(cat_data.get("characters", []))
        is_sel = cat_id in selected and not all_selected and "*" not in selected
        prefix = "☑️" if is_sel else "⬜"
        buttons.append([
            InlineKeyboardButton(
                text=f"{prefix} {emoji} {name} ({count})",
                callback_data=f"toggle_cat_{cat_id}"
            )
        ])
    
    buttons.append([InlineKeyboardButton(text="✅ Готово", callback_data="back_settings")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def game_type_keyboard() -> InlineKeyboardMarkup:
    """Выбор типа игры."""
    buttons = [
        [InlineKeyboardButton(
            text="📝 Классика (описания)",
            callback_data="set_game_type_classic"
        )],
        [InlineKeyboardButton(
            text="❓ Вопросы (да/нет)",
            callback_data="set_game_type_questions"
        )],
        [InlineKeyboardButton(
            text="🎭 Слепой шпион",
            callback_data="set_game_type_blind_spy"
        )],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_settings")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def start_vote_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """Кнопка начала голосования."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🗳️ Начать голосование",
                callback_data=f"start_vote_{chat_id}"
            )],
        ]
    )


def vote_keyboard(chat_id: int, players: list, votes: dict[int, int] = None) -> InlineKeyboardMarkup:
    """Клавиатура голосования за игроков с отменой."""
    if votes is None:
        votes = {}
    buttons = []
    for p in players:
        cnt = votes.get(p.user_id, 0)
        cnt_text = f" ({cnt})" if cnt > 0 else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"🎯 {p.full_name}{' 👑' if p.is_creator else ''}{cnt_text}",
                callback_data=f"vote_{chat_id}_{p.user_id}"
            )
        ])
    buttons.append([
        InlineKeyboardButton(
            text="❌ Отменить голосование",
            callback_data=f"cancel_vote_{chat_id}"
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def i_said_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """Кнопка 'Я сказал' в ЛС для текущего игрока."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Я сказал",
                callback_data=f"i_said_{chat_id}"
            )],
        ]
    )


def round_end_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """Кнопки после раунда: голосовать или продолжить."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🗳️ Голосовать",
                callback_data=f"start_vote_{chat_id}"
            )],
            [InlineKeyboardButton(
                text="▶️ Следующий раунд",
                callback_data=f"next_round_{chat_id}"
            )],
        ]
    )


def play_again_keyboard() -> InlineKeyboardMarkup:
    """Кнопка 'Играть снова' после завершения игры."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Играть снова", callback_data="play_again")],
        ]
    )


def question_target_keyboard(chat_id: int, players: list, asker_id: int) -> InlineKeyboardMarkup:
    """Выбор кому задать вопрос (режим вопросов)."""
    buttons = []
    for p in players:
        if p.user_id != asker_id:  # Нельзя спрашивать себя
            buttons.append([
                InlineKeyboardButton(
                    text=f"❓ Спросить {p.full_name}",
                    callback_data=f"ask_{chat_id}_{p.user_id}"
                )
            ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def host_pick_keyboard(chat_id: int, players: list, current_host_id: int | None) -> InlineKeyboardMarkup:
    """Выбор ведущего из списка игроков."""
    buttons = []
    for p in players:
        mark = "👤 " if p.user_id == current_host_id else "⬜ "
        buttons.append([InlineKeyboardButton(
            text=f"{mark}{p.full_name}",
            callback_data=f"set_host_{chat_id}_{p.user_id}"
        )])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_settings")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def host_confirm_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """Подтверждение персонажа ведущим."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Оставить", callback_data=f"host_accept_{chat_id}"),
                InlineKeyboardButton(text="🔄 Другой", callback_data=f"host_reroll_{chat_id}"),
            ],
        ]
    )


def reroll_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """Голосование за смену персонажа."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ За", callback_data=f"reroll_yes_{chat_id}")],
        ]
    )


def yes_no_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """Кнопки да/нет для ответа на вопрос."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data=f"answer_{chat_id}_yes"),
                InlineKeyboardButton(text="❌ Нет", callback_data=f"answer_{chat_id}_no"),
            ],
            [
                InlineKeyboardButton(text="🤷 Не уверен", callback_data=f"answer_{chat_id}_maybe"),
            ],
        ]
    )
