from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class GameMode(Enum):
    ONE_SPY = "one_spy"
    MULTI_SPY = "multi_spy"


class GameType(Enum):
    CLASSIC = "classic"  # Классический режим с описаниями
    QUESTIONS = "questions"  # Режим вопросов да/нет
    NO_TRAITORS = "no_traitors"  # Игра без предателей (никто не знает)
    ALL_TRAITORS = "all_traitors"  # Все предатели (никто не знает)
    BLIND_SPY = "blind_spy"  # Слепой шпион — получает фейкового персонажа


class SettingsMode(Enum):
    MANUAL = "manual"  # Ручной выбор настроек
    RANDOM = "random"  # Рандомные настройки


class GameState(Enum):
    LOBBY = "lobby"
    ROLE_DISTRIBUTION = "role_distribution"
    DESCRIBING = "describing"
    QUESTIONING = "questioning"  # Для режима вопросов
    DISCUSSION = "discussion"
    VOTING = "voting"
    FINISHED = "finished"


class Role(Enum):
    CIVILIAN = "civilian"
    SPY = "spy"
    PROVOCATEUR = "provocateur"  # Мирный с фейковым персонажем, побеждает со шпионами
    CONFUSED = "confused"  # Мирный с ДРУГИМ персонажем из той же категории


@dataclass
class Player:
    user_id: int
    username: str
    full_name: str
    role: Optional[Role] = None
    is_creator: bool = False
    has_described: bool = False
    vote_for: Optional[int] = None
    fake_character: str = ""  # Для провокатора
    alt_character: str = ""  # Для путаника (другой персонаж из категории)
    split_character: str = ""  # Для split-режима — свой персонаж
    hint_used: bool = False  # Использовал ли шпион подсказку
    letter_sent: bool = False  # Отправил ли письмо
    received_letters: dict[int, str] = field(default_factory=dict)


@dataclass
class GameSession:
    chat_id: int
    creator_id: int
    mode: GameMode = GameMode.ONE_SPY
    game_type: GameType = GameType.CLASSIC
    settings_mode: SettingsMode = SettingsMode.MANUAL  # Ручной или рандом
    state: GameState = GameState.LOBBY
    players: list[Player] = field(default_factory=list)
    character: str = ""
    categories: list[str] = field(default_factory=lambda: ["*"])
    current_turn_index: int = 0
    spy_guess: Optional[str] = None
    winner: Optional[str] = None
    spy_count: int = 1  # По умолчанию 1 шпион
    provocateur_enabled: bool = False  # Включён ли провокатор
    confused_enabled: bool = False  # Включён ли путаник (авто при 7+ игроках)
    current_question_target: Optional[int] = (
        None  # Кому задают вопрос (для режима вопросов)
    )
    questions_round: int = 0  # Раунд вопросов
    description_round: int = 0  # Раунд описаний (1-2 = обобщённые)
    host_mode: bool = False  # Режим ведущего
    host_id: Optional[int] = None  # ID ведущего
    split_character: str = ""  # Второй персонаж для split-режима (5% шанс)
    split_words: list[str] = field(
        default_factory=list
    )  # Все розданные слова в split-режиме

    lobby_msg_id: int = 0  # ID сообщения-лобби (для проверки устаревших)
    created_at: float = 0.0  # timestamp создания
    last_activity: float = 0.0  # timestamp последней активности

    def get_player(self, user_id: int) -> Optional[Player]:
        for p in self.players:
            if p.user_id == user_id:
                return p
        return None

    def get_spy_count(self) -> int:
        if self.mode == GameMode.ONE_SPY:
            self.spy_count = 1
            return 1
        if self.spy_count > 0:
            # Не больше, чем игроков - 1
            return min(self.spy_count, max(1, len(self.players) - 1))
        total = len(self.players)
        if total <= 6:
            spy_count = 2
        elif total <= 9:
            spy_count = 3
        else:
            spy_count = max(4, total // 3)
        return max(1, min(spy_count, total - 1))

    def is_full(self) -> bool:
        return len(self.players) >= 20

    def can_start(self) -> bool:
        return len(self.players) >= 2
