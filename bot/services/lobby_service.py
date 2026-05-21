import time
import asyncio
from typing import Optional

from bot.models.game import GameMode, GameSession, GameState, Player
from bot.models.database import save_session, load_session, delete_session


_sessions: dict[int, GameSession] = {}
_player_to_session: dict[int, int] = {}  # user_id → chat_id
_session_locks: dict[int, asyncio.Lock] = {}  # chat_id → lock for race protection


def get_lock(chat_id: int) -> asyncio.Lock:
    """Возвращает asyncio.Lock для чата — защита от race conditions на await."""
    if chat_id not in _session_locks:
        _session_locks[chat_id] = asyncio.Lock()
    return _session_locks[chat_id]


def get_session(chat_id: int) -> Optional[GameSession]:
    return _sessions.get(chat_id)


def get_all_sessions():
    return list(_sessions.values())


def get_session_by_player(user_id: int) -> Optional[GameSession]:
    """O(1) поиск сессии по ID игрока вместо прохода по всем."""
    chat_id = _player_to_session.get(user_id)
    return _sessions.get(chat_id) if chat_id else None


def create_session(
    chat_id: int, creator_id: int, creator_username: str, creator_full_name: str
) -> GameSession:
    now = time.time()
    session = GameSession(
        chat_id=chat_id,
        creator_id=creator_id,
        created_at=now,
        last_activity=now,
    )
    session.players.append(
        Player(
            user_id=creator_id,
            username=creator_username,
            full_name=creator_full_name,
            is_creator=True,
        )
    )
    _sessions[chat_id] = session
    _player_to_session[creator_id] = chat_id
    return session


def add_player(
    session: GameSession, user_id: int, username: str, full_name: str
) -> bool:
    if session.get_player(user_id):
        return False
    if session.is_full():
        return False
    session.players.append(
        Player(
            user_id=user_id,
            username=username,
            full_name=full_name,
        )
    )
    _player_to_session[user_id] = session.chat_id
    return True


def remove_player(session: GameSession, user_id: int) -> bool:
    player = session.get_player(user_id)
    if not player:
        return False
    session.players = [p for p in session.players if p.user_id != user_id]
    _player_to_session.pop(user_id, None)
    if not session.players:
        _sessions.pop(session.chat_id, None)
    return True


def set_mode(session: GameSession, mode: GameMode) -> None:
    session.mode = mode


async def start_game(session: GameSession) -> None:
    from bot.services.game_service import assign_roles

    await assign_roles(session)


def reset_sessions():
    _sessions.clear()
    _player_to_session.clear()
    _session_locks.clear()


async def persist_session(session: GameSession):
    await save_session(session)


async def restore_session(chat_id: int) -> Optional[GameSession]:
    if chat_id in _sessions:
        return _sessions[chat_id]
    session = await load_session(chat_id)
    if session:
        _sessions[chat_id] = session
    return session


async def end_session(chat_id: int):
    await delete_session(chat_id)
    session = _sessions.pop(chat_id, None)
    # Чистим индекс игроков
    if session:
        for p in session.players:
            _player_to_session.pop(p.user_id, None)
    _session_locks.pop(chat_id, None)  # чистим лок
    # Чистим глобальные словари из group.py
    from bot.handlers.group import (
        _mode_tracker,
        _reroll_votes,
        _cancel_votes,
        _skip_pause,
        _coin_choices,
    )

    _mode_tracker.pop(chat_id, None)
    _reroll_votes.pop(chat_id, None)
    _cancel_votes.pop(chat_id, None)
    _skip_pause.pop(chat_id, None)
    _coin_choices.pop(chat_id, None)


async def cleanup_stale_lobbies(max_age: float = 180.0):
    """Удаляет лобби-сессии, неактивные дольше max_age секунд."""
    now = time.time()
    to_delete = []
    for chat_id, session in list(_sessions.items()):
        if session.state == GameState.LOBBY and now - session.last_activity > max_age:
            to_delete.append(chat_id)
    for chat_id in to_delete:
        await end_session(chat_id)
