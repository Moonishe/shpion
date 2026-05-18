import time

import aiosqlite

from bot.config import DB_PATH

INIT_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    chat_id INTEGER PRIMARY KEY,
    creator_id INTEGER NOT NULL,
    mode TEXT NOT NULL DEFAULT 'one_spy',
    game_type TEXT NOT NULL DEFAULT 'classic',
    settings_mode TEXT NOT NULL DEFAULT 'manual',
    state TEXT NOT NULL DEFAULT 'lobby',
    character TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'all',
    current_turn_index INTEGER NOT NULL DEFAULT 0,
    spy_guess TEXT,
    winner TEXT,
    spy_count INTEGER NOT NULL DEFAULT 1,
    provocateur_enabled INTEGER NOT NULL DEFAULT 0,
    confused_enabled INTEGER NOT NULL DEFAULT 0,
    current_question_target INTEGER,
    questions_round INTEGER NOT NULL DEFAULT 0,
    description_round INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS players (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT,
    full_name TEXT,
    role TEXT,
    is_creator INTEGER NOT NULL DEFAULT 0,
    has_described INTEGER NOT NULL DEFAULT 0,
    vote_for INTEGER,
    fake_character TEXT DEFAULT '',
    alt_character TEXT DEFAULT '',
    hint_used INTEGER NOT NULL DEFAULT 0,
    letter_sent INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS stats (
    user_id INTEGER PRIMARY KEY,
    games_played INTEGER NOT NULL DEFAULT 0,
    games_won INTEGER NOT NULL DEFAULT 0,
    games_lost INTEGER NOT NULL DEFAULT 0,
    hints_used INTEGER NOT NULL DEFAULT 0,
    letters_sent INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    from_user_id INTEGER NOT NULL,
    to_user_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_letters_chat_id ON letters(chat_id);
"""


async def init_db():
    """Инициализация базы данных."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(INIT_SQL)
        
        # Миграции для новых колонок
        migrations = [
            ("sessions", "spy_count", "INTEGER NOT NULL DEFAULT 1"),
            ("sessions", "game_type", "TEXT NOT NULL DEFAULT 'classic'"),
            ("sessions", "settings_mode", "TEXT NOT NULL DEFAULT 'manual'"),
            ("sessions", "category", "TEXT NOT NULL DEFAULT 'all'"),
            ("sessions", "provocateur_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("sessions", "current_question_target", "INTEGER"),
            ("sessions", "questions_round", "INTEGER NOT NULL DEFAULT 0"),
            ("sessions", "description_round", "INTEGER NOT NULL DEFAULT 0"),
            ("sessions", "confused_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("players", "fake_character", "TEXT DEFAULT ''"),
            ("players", "alt_character", "TEXT DEFAULT ''"),
            ("players", "hint_used", "INTEGER NOT NULL DEFAULT 0"),
            ("players", "letter_sent", "INTEGER NOT NULL DEFAULT 0"),
            ("sessions", "created_at", "REAL NOT NULL DEFAULT 0"),
            ("sessions", "last_activity", "REAL NOT NULL DEFAULT 0"),
            ("sessions", "host_mode", "INTEGER NOT NULL DEFAULT 0"),
            ("sessions", "host_id", "INTEGER"),
            ("stats", "spy_streak", "INTEGER NOT NULL DEFAULT 0"),
            ("stats", "provocateur_streak", "INTEGER NOT NULL DEFAULT 0"),
            ("sessions", "split_character", "TEXT DEFAULT ''"),
        ]
        
        for table, column, col_type in migrations:
            try:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                await db.commit()
            except Exception as e:
                if 'duplicate column' in str(e).lower() or 'already exists' in str(e).lower():
                    pass
                else:
                    raise


async def save_session(session):
    """Сохранение сессии в БД."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO sessions (
                chat_id, creator_id, mode, game_type, settings_mode, state, character, category,
                current_turn_index, spy_guess, winner, spy_count,
                provocateur_enabled, confused_enabled, current_question_target, questions_round,
                description_round, created_at, last_activity, host_mode, host_id, split_character
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                creator_id=excluded.creator_id,
                mode=excluded.mode,
                game_type=excluded.game_type,
                settings_mode=excluded.settings_mode,
                state=excluded.state,
                character=excluded.character,
                category=excluded.category,
                current_turn_index=excluded.current_turn_index,
                spy_guess=excluded.spy_guess,
                winner=excluded.winner,
                spy_count=excluded.spy_count,
                provocateur_enabled=excluded.provocateur_enabled,
                confused_enabled=excluded.confused_enabled,
                current_question_target=excluded.current_question_target,
                questions_round=excluded.questions_round,
                description_round=excluded.description_round,
                last_activity=excluded.last_activity,
                host_mode=excluded.host_mode,
                host_id=excluded.host_id,
                split_character=excluded.split_character
            """,
            (
                session.chat_id,
                session.creator_id,
                session.mode.value,
                session.game_type.value,
                session.settings_mode.value,
                session.state.value,
                session.character,
                ",".join(session.categories) if session.categories else "*",
                session.current_turn_index,
                session.spy_guess,
                session.winner,
                session.spy_count,
                int(session.provocateur_enabled),
                int(session.confused_enabled),
                session.current_question_target,
                session.questions_round,
                session.description_round,
                session.created_at,
                session.last_activity,
                int(session.host_mode),
                session.host_id,
                session.split_character,
            ),
        )
        await db.execute("DELETE FROM players WHERE chat_id = ?", (session.chat_id,))
        for p in session.players:
            await db.execute(
                """
                INSERT INTO players (
                    chat_id, user_id, username, full_name, role,
                    is_creator, has_described, vote_for, fake_character, alt_character, hint_used, letter_sent
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.chat_id,
                    p.user_id,
                    p.username,
                    p.full_name,
                    p.role.value if p.role else None,
                    int(p.is_creator),
                    int(p.has_described),
                    p.vote_for,
                    p.fake_character,
                    p.alt_character,
                    int(p.hint_used),
                    int(p.letter_sent),
                ),
            )
        await db.commit()


async def load_session(chat_id: int):
    """Загрузка сессии из БД."""
    from bot.models.game import GameSession, GameMode, GameType, SettingsMode, GameState, Player, Role

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM sessions WHERE chat_id = ?", (chat_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            
            # Безопасное получение значений с дефолтами
            game_type_val = row["game_type"] if "game_type" in row.keys() else "classic"
            settings_mode_val = row["settings_mode"] if "settings_mode" in row.keys() else "manual"
            raw_cat = row["category"] if "category" in row.keys() else "*"
            category_list = raw_cat.split(",") if raw_cat else ["*"]
            provocateur_val = row["provocateur_enabled"] if "provocateur_enabled" in row.keys() else 0
            confused_val = row["confused_enabled"] if "confused_enabled" in row.keys() else 0
            question_target = row["current_question_target"] if "current_question_target" in row.keys() else None
            questions_round = row["questions_round"] if "questions_round" in row.keys() else 0
            description_round = row["description_round"] if "description_round" in row.keys() else 0
            created_at = row["created_at"] if "created_at" in row.keys() else 0.0
            last_activity = row["last_activity"] if "last_activity" in row.keys() else 0.0
            host_mode = row["host_mode"] if "host_mode" in row.keys() else 0
            host_id = row["host_id"] if "host_id" in row.keys() else None
            split_character = row["split_character"] if "split_character" in row.keys() else ""

            
            session = GameSession(
                chat_id=row["chat_id"],
                creator_id=row["creator_id"],
                mode=GameMode(row["mode"]),
                game_type=GameType(game_type_val),
                settings_mode=SettingsMode(settings_mode_val),
                state=GameState(row["state"]),
                character=row["character"],
                categories=category_list,
                current_turn_index=row["current_turn_index"],
                spy_guess=row["spy_guess"],
                winner=row["winner"],
                spy_count=row["spy_count"] if "spy_count" in row.keys() else 1,
                provocateur_enabled=bool(provocateur_val),
                confused_enabled=bool(confused_val),
                current_question_target=question_target,
                questions_round=questions_round,
                description_round=description_round,
                created_at=created_at,
                last_activity=last_activity,
                host_mode=bool(host_mode),
                host_id=host_id,
                split_character=split_character,
            )
            
        async with db.execute(
            "SELECT * FROM players WHERE chat_id = ?", (chat_id,)
        ) as cursor:
            async for row in cursor:
                fake_char = row["fake_character"] if "fake_character" in row.keys() else ""
                alt_char = row["alt_character"] if "alt_character" in row.keys() else ""
                hint_used = row["hint_used"] if "hint_used" in row.keys() else 0
                letter_sent = row["letter_sent"] if "letter_sent" in row.keys() else 0

                player = Player(
                    user_id=row["user_id"],
                    username=row["username"],
                    full_name=row["full_name"],
                    role=Role(row["role"]) if row["role"] else None,
                    is_creator=bool(row["is_creator"]),
                    has_described=bool(row["has_described"]),
                    vote_for=row["vote_for"],
                    fake_character=fake_char or "",
                    alt_character=alt_char or "",
                    hint_used=bool(hint_used),
                    letter_sent=bool(letter_sent),
                )
                session.players.append(player)

        async with db.execute(
            "SELECT from_user_id, to_user_id, text FROM letters WHERE chat_id = ?", (chat_id,)
        ) as cursor:
            async for row in cursor:
                for player in session.players:
                    if player.user_id == row["to_user_id"]:
                        player.received_letters[row["from_user_id"]] = row["text"]

        return session


async def delete_session(chat_id: int):
    """Удаление сессии из БД."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM letters WHERE chat_id = ?", (chat_id,))
        await db.execute("DELETE FROM players WHERE chat_id = ?", (chat_id,))
        await db.execute("DELETE FROM sessions WHERE chat_id = ?", (chat_id,))
        await db.commit()


async def update_stats(user_id: int, won: bool, hint_used: bool = False, letter_sent: bool = False):
    """Обновляет статистику игрока."""
    won_val = 1 if won else 0
    lost_val = 0 if won else 1
    hint_val = 1 if hint_used else 0
    letter_val = 1 if letter_sent else 0
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO stats (user_id, games_played, games_won, games_lost, hints_used, letters_sent)
            VALUES (?, 1, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                games_played = games_played + 1,
                games_won = games_won + ?,
                games_lost = games_lost + ?,
                hints_used = hints_used + ?,
                letters_sent = letters_sent + ?
            """,
            (user_id, won_val, lost_val, hint_val, letter_val,
             won_val, lost_val, hint_val, letter_val),
        )
        await db.commit()


async def get_streaks(user_ids: list[int]) -> dict[int, dict]:
    """Возвращает spy_streak и provocateur_streak для списка игроков."""
    if not user_ids:
        return {}
    async with aiosqlite.connect(DB_PATH) as db:
        placeholders = ",".join("?" * len(user_ids))
        cursor = await db.execute(
            f"SELECT user_id, spy_streak, provocateur_streak FROM stats WHERE user_id IN ({placeholders})",
            tuple(user_ids),
        )
        rows = await cursor.fetchall()
    return {row[0]: {"spy": row[1] or 0, "prov": row[2] or 0} for row in rows}


async def update_streaks(spy_ids: list[int], prov_ids: list[int], all_ids: list[int]):
    """Обновляет стрики: шпионы/провокаторы +1, остальные −1 (мин 0)."""
    async with aiosqlite.connect(DB_PATH) as db:
        for uid in all_ids:
            await db.execute(
                "INSERT INTO stats (user_id, games_played, games_won, games_lost, hints_used, letters_sent, spy_streak, provocateur_streak) "
                "VALUES (?, 0, 0, 0, 0, 0, 0, 0) "
                "ON CONFLICT(user_id) DO NOTHING",
                (uid,),
            )
        for uid in spy_ids:
            await db.execute(
                "UPDATE stats SET spy_streak = spy_streak + 1, provocateur_streak = MAX(0, provocateur_streak - 1) WHERE user_id = ?",
                (uid,),
            )
        for uid in prov_ids:
            await db.execute(
                "UPDATE stats SET provocateur_streak = provocateur_streak + 1, spy_streak = MAX(0, spy_streak - 1) WHERE user_id = ?",
                (uid,),
            )
        other_ids = [uid for uid in all_ids if uid not in spy_ids and uid not in prov_ids]
        for uid in other_ids:
            await db.execute(
                "UPDATE stats SET spy_streak = MAX(0, spy_streak - 1), provocateur_streak = MAX(0, provocateur_streak - 1) WHERE user_id = ?",
                (uid,),
            )
        await db.commit()


async def get_stats(user_id: int) -> dict | None:
    """Возвращает статистику игрока."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM stats WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return dict(row)


async def save_letter(chat_id: int, from_user_id: int, to_user_id: int, text: str):
    """Сохраняет письмо в БД."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO letters (chat_id, from_user_id, to_user_id, text, created_at) VALUES (?, ?, ?, ?, ?)",
            (chat_id, from_user_id, to_user_id, text, time.time()),
        )
        await db.commit()


async def get_all_active_sessions() -> list[int]:
    """Возвращает список chat_id активных сессий."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT chat_id FROM sessions WHERE state != 'finished'"
        ) as cursor:
            return [row[0] async for row in cursor]


async def cleanup_stale_sessions(max_age: float = 7200):
    """Удаляет сессии старше max_age секунд (по умолчанию 2 часа).
    Сессии с last_activity=0 (старые, до миграции) не трогает."""
    cutoff = time.time() - max_age
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM players WHERE chat_id IN (SELECT chat_id FROM sessions WHERE last_activity > 0 AND last_activity < ?)",
            (cutoff,)
        )
        await db.execute(
            "DELETE FROM letters WHERE chat_id IN (SELECT chat_id FROM sessions WHERE last_activity > 0 AND last_activity < ?)",
            (cutoff,)
        )
        await db.execute(
            "DELETE FROM sessions WHERE last_activity > 0 AND last_activity < ?",
            (cutoff,)
        )
        await db.commit()
