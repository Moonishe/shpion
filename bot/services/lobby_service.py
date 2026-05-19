import time
from typing import Optional

from bot.models.game import GameMode, GameSession, GameState, Player
from bot.models.database import save_session, load_session, delete_session


_sessions: dict[int, GameSession] = {}


def get_session(chat_id: int) -> Optional[GameSession]:
    return _sessions.get(chat_id)


def get_all_sessions():
    return list(_sessions.values())


def create_session(chat_id: int, creator_id: int, creator_username: str, creator_full_name: str) -> GameSession:
    now = time.time()
    session = GameSession(
        chat_id=chat_id,
        creator_id=creator_id,
        created_at=now,
        last_activity=now,
    )
    session.players.append(Player(
        user_id=creator_id,
        username=creator_username,
        full_name=creator_full_name,
        is_creator=True,
    ))
    _sessions[chat_id] = session
    return session


def add_player(session: GameSession, user_id: int, username: str, full_name: str) -> bool:
    if session.get_player(user_id):
        return False
    if session.is_full():
        return False
    session.players.append(Player(
        user_id=user_id,
        username=username,
        full_name=full_name,
    ))
    return True


def remove_player(session: GameSession, user_id: int) -> bool:
    player = session.get_player(user_id)
    if not player:
        return False
    session.players = [p for p in session.players if p.user_id != user_id]
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


async def persist_session(session: GameSession):
    await save_session(session)


async def restore_session(chat_id: int) -> Optional[GameSession]:
    session = await load_session(chat_id)
    if session:
        _sessions[chat_id] = session
    return session


async def end_session(chat_id: int):
    _sessions.pop(chat_id, None)
    await delete_session(chat_id)


async def cleanup_stale_lobbies(max_age: float = 180.0):
    """Удаляет лобби-сессии, неактивные дольше max_age секунд."""
    now = time.time()
    to_delete = []
    for chat_id, session in list(_sessions.items()):
        if session.state == GameState.LOBBY and now - session.last_activity > max_age:
            to_delete.append(chat_id)
    for chat_id in to_delete:
        await end_session(chat_id)
