import time
import re
import logging
import random

from bot.config import get_characters_by_category, get_categories
from bot.models.game import GameSession, GameState, GameType, GameMode, Player, Role

logger = logging.getLogger(__name__)

# Маппинг чисел: русские слова, английские, транслит → цифры
_NUM_MAP = {
    'ноль': '0', 'один': '1', 'два': '2', 'три': '3', 'четыре': '4',
    'пять': '5', 'шесть': '6', 'семь': '7', 'восемь': '8', 'девять': '9',
    'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4',
    'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9',
    'сикс': '6', 'севен': '7', 'найн': '9', 'ту': '2', 'фри': '3',
    'фор': '4', 'файв': '5', 'эйт': '8',
}

# Транслит → кириллица
_TRANS_MAP = {
    'sh': 'ш', 'ch': 'ч', 'sch': 'щ', 'zh': 'ж', 'ts': 'ц',
    'yu': 'ю', 'ya': 'я', 'yo': 'ё', 'kh': 'х', 'th': 'т',
    'ph': 'ф', 'ee': 'и', 'oo': 'у', 'ai': 'ай', 'ei': 'ей',
    'a': 'а', 'b': 'б', 'v': 'в', 'g': 'г', 'd': 'д',
    'e': 'е', 'z': 'з', 'i': 'и', 'j': 'й', 'k': 'к',
    'l': 'л', 'm': 'м', 'n': 'н', 'o': 'о', 'p': 'п',
    'r': 'р', 's': 'с', 't': 'т', 'u': 'у', 'f': 'ф',
    'h': 'х', 'c': 'к', 'y': 'ы', 'x': 'кс', 'w': 'в',
    'q': 'к',
}


def normalize_for_comparison(s: str) -> str:
    """Нормализует строку для сравнения: цифры↔слова, транслит, регистр, е/ё."""
    s = s.lower().strip()
    # е ↔ ё
    s = s.replace('ё', 'е')
    # Убираем пробелы и пунктуацию
    s = re.sub(r'[^\wа-яёa-z0-9]', '', s)
    # Транслит → кириллица (двухбуквенные сначала)
    for t, c in sorted(_TRANS_MAP.items(), key=lambda x: -len(x[0])):
        s = s.replace(t, c)
    # Числа словами → цифры
    for word, digit in sorted(_NUM_MAP.items(), key=lambda x: -len(x[0])):
        s = s.replace(word, digit)
    return s


def _levenshtein(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            insert = prev[j + 1] + 1
            delete = curr[j] + 1
            sub = prev[j] + (0 if c1 == c2 else 1)
            curr.append(min(insert, delete, sub))
        prev = curr
    return prev[-1]


def guess_matches(guess: str, character: str) -> bool:
    """Проверяет, совпадает ли догадка с персонажем (fuzzy matching 45%)."""
    g = normalize_for_comparison(guess)
    c = normalize_for_comparison(character)
    dist = _levenshtein(g, c)
    threshold = max(1, int(len(c) * 0.45))
    return dist <= threshold

# Рейт-лимит: {user_id: last_command_time}
_rate_limit: dict[int, float] = {}


def check_rate_limit(user_id: int, cooldown: float = 1.0) -> bool:
    """Проверяет рейт-лимит. Возвращает True если можно, False если рано."""
    now = time.time()
    last = _rate_limit.get(user_id, 0.0)
    if now - last < cooldown:
        return False
    _rate_limit[user_id] = now
    return True


def clear_rate_limit(user_id: int):
    """Сбрасывает рейт-лимит для пользователя."""
    _rate_limit.pop(user_id, None)


async def record_stats(session, civilians_won: bool = True, spy_guess: bool = False):
    """Записывает статистику для всех игроков после окончания игры."""
    from bot.models.database import update_stats
    for p in session.players:
        if p.role == Role.SPY or p.role == Role.PROVOCATEUR:
            won = spy_guess
        else:
            won = civilians_won
        try:
            await update_stats(
                user_id=p.user_id,
                won=won,
                hint_used=p.hint_used,
                letter_sent=p.letter_sent,
            )
        except Exception as e:
            logger.warning("Не удалось сохранить статистику для %d: %s", p.user_id, e)


def randomize_settings(session: GameSession) -> None:
    """Рандомизирует настройки игры."""
    # Рандомные категории
    all_cats = list(get_categories().keys())
    session.categories = random.sample(all_cats, k=random.randint(1, min(3, len(all_cats))))

    # Рандомный тип игры
    session.game_type = random.choice([GameType.CLASSIC, GameType.QUESTIONS])

    # Рандомное количество шпионов (зависит от числа игроков)
    num_players = len(session.players)
    if num_players <= 4:
        session.spy_count = 1
        session.mode = GameMode.ONE_SPY
    elif num_players <= 6:
        session.spy_count = random.choice([1, 2])
        session.mode = GameMode.ONE_SPY if session.spy_count == 1 else GameMode.MULTI_SPY
    elif num_players <= 9:
        session.spy_count = random.choice([1, 2, 3])
        session.mode = GameMode.ONE_SPY if session.spy_count == 1 else GameMode.MULTI_SPY
    else:
        session.spy_count = random.choice([2, 3, 4])
        session.mode = GameMode.MULTI_SPY

    # Рандомный провокатор (только если 4+ игроков и не в специальных режимах)
    if num_players >= 4 and session.game_type not in (GameType.NO_TRAITORS, GameType.ALL_TRAITORS):
        session.provocateur_enabled = random.choice([True, False])
    else:
        session.provocateur_enabled = False


def assign_roles(session: GameSession, pick_character: bool = True) -> None:
    """Распределяет роли и выбирает персонажа."""
    characters = get_characters_by_category(session.categories)
    if not characters:
        raise ValueError("Нет персонажей в выбранных категориях!")

    if pick_character and not session.character:
        session.character = random.choice(characters)
    spy_count = session.get_spy_count()

    # Специальные режимы
    if session.game_type == GameType.NO_TRAITORS:
        for p in session.players:
            p.role = Role.CIVILIAN
        session.state = GameState.ROLE_DISTRIBUTION
        return

    if session.game_type == GameType.ALL_TRAITORS:
        for p in session.players:
            p.role = Role.SPY
        session.state = GameState.ROLE_DISTRIBUTION
        return

    if session.game_type == GameType.BLIND_SPY:
        for p in session.players:
            p.role = Role.CIVILIAN
        others = [c for c in characters if c != session.character]
        fake_char = random.choice(others) if others else "Загадочный незнакомец"
        spy_target = random.choice(session.players)
        spy_target.role = Role.SPY
        spy_target.fake_character = fake_char
        session.state = GameState.ROLE_DISTRIBUTION
        return

    # Перемешиваем игроков для случайного распределения
    ordered = session.players[:]
    random.shuffle(ordered)

    total = len(ordered)
    civilian_pool = ordered[spy_count:]

    # Провокатор (из civilians)
    prov_idx = -1
    if session.provocateur_enabled and total >= 4 and len(civilian_pool) >= 1:
        prov_idx = spy_count + random.choice(range(len(civilian_pool)))

    # Путаник (из civilians, не провокатор)
    conf_idx = -1
    alt_char = None
    conf_available = [i for i in range(spy_count, total) if i != prov_idx]
    if total >= 7 and conf_available and len(characters) >= 2:
        chance = 0.25 if total <= 9 else (0.5 if total == 10 else 0.75)
        if random.random() < chance:
            session.confused_enabled = True
            conf_idx = random.choice(conf_available)
            other_chars = [c for c in characters if c != session.character]
            alt_char = random.choice(other_chars) if other_chars else None

    # Раздаём роли
    for i, p in enumerate(ordered):
        if i < spy_count:
            p.role = Role.SPY
        elif i == prov_idx:
            p.role = Role.PROVOCATEUR
            others = [c for c in characters if c != session.character]
            p.fake_character = random.choice(others) if others else "Загадочный незнакомец"
        elif i == conf_idx and alt_char:
            p.role = Role.CONFUSED
            p.alt_character = alt_char
        else:
            p.role = Role.CIVILIAN

    session.state = GameState.ROLE_DISTRIBUTION


def get_hint_for_spy(session: GameSession, hint_type: str) -> str:
    """Возвращает подсказку для шпиона."""
    character = session.character

    if hint_type == "random_letter":
        letter_positions = [i for i, c in enumerate(character) if c.isalpha()]
        if letter_positions:
            pos = random.choice(letter_positions)
            letter = character[pos].upper()
            return f"🎲 Буква на позиции {pos + 1}: <b>{letter}</b>"
        else:
            return f"🎲 Буква на позиции 1: <b>{character[0].upper()}</b>"
    elif hint_type == "first_letter":
        first = character[0].upper() if character else "?"
        return f"🔤 Первая буква: <b>{first}</b>"
    elif hint_type == "last_letter":
        last = character[-1].upper() if character else "?"
        return f"🔤 Последняя буква: <b>{last}</b>"
    elif hint_type == "length":
        return f"📏 Длина имени: <b>{len(character)}</b> символов"
    elif hint_type == "word_count":
        words = character.split()
        word_str = "слово" if len(words) == 1 else ("слова" if 2 <= len(words) <= 4 else "слов")
        return f"📝 Количество слов: <b>{len(words)}</b> {word_str}"
    elif hint_type == "category":
        from bot.config import get_category_name, get_characters_by_category
        cats = session.categories
        cat_name = get_category_name(cats)
        return f"📂 Категория: <b>{cat_name}</b>"

    return "❌ Неизвестный тип подсказки"


def check_all_described(session: GameSession) -> bool:
    """Проверяет, все ли описали (включая шпионов, если они в очереди)."""
    for p in session.players:
        if not p.has_described:
            return False
    return True


def update_session_activity(session: GameSession):
    """Обновляет время последней активности сессии."""
    session.last_activity = time.time()


def process_vote_result(session: GameSession) -> dict | None:
    """
    Обрабатывает результат голосования.
    Возвращает словарь с результатом или None если недостаточно голосов.
    Требуется >75% участия для раскрытия результата.
    """
    most_voted, count = get_most_voted(session)
    if most_voted is None:
        return None

    total = len(session.players)
    voted = sum(1 for p in session.players if p.vote_for is not None)
    target = session.get_player(most_voted)

    if not target:
        return None

    majority = total // 2 + 1
    required_votes = int(total * 0.75) + 1  # >75% must participate

    # Нужно >75% участия, иначе результат не раскрывается
    if voted < required_votes:
        return None

    # Если ещё не набрали большинство и не все проголосовали — не обрабатываем
    if count < majority and voted < total:
        return None

    result = {
        "target_id": most_voted,
        "target": target,
        "count": count,
        "total": total,
        "all_voted": voted == total,
    }

    if target.role in (Role.CIVILIAN, Role.CONFUSED) and (count >= majority or voted == total):
        result["outcome"] = "civilian_caught"
    elif target.role == Role.PROVOCATEUR and (count >= majority or voted == total):
        result["outcome"] = "provocateur_caught"
    elif target.role == Role.SPY and (count >= majority or voted == total):
        remaining = sum(1 for p in session.players if p.role == Role.SPY and p.user_id != most_voted)
        if remaining > 0:
            result["outcome"] = "spy_caught_continue"
            result["remaining_spies"] = remaining
        else:
            result["outcome"] = "civilians"
    elif voted == total:
        result["outcome"] = "no_majority"
    else:
        return None

    return result


def create_turn_order(session: GameSession) -> list[Player]:
    """
    Создаёт очередь ходов.
    Шпионы имеют шанс 15% попасть в первые позиции, иначе идут в конец.
    """
    civilians = [p for p in session.players if p.role in (Role.CIVILIAN, Role.PROVOCATEUR, Role.CONFUSED)]
    spies = [p for p in session.players if p.role == Role.SPY]
    
    random.shuffle(civilians)
    random.shuffle(spies)
    
    order = []
    spy_positions = []
    
    # Для каждого шпиона определяем, попадёт ли он в начало (15% шанс)
    for spy in spies:
        if random.random() < 0.15:  # 15% шанс начать раньше
            # Вставляем в случайную позицию среди первой половины
            max_pos = max(1, len(civilians) // 2)
            pos = random.randint(0, max_pos)
            spy_positions.append((spy, pos))
        else:
            spy_positions.append((spy, None))  # В конец
    
    # Собираем очередь
    order = civilians[:]
    
    # Вставляем шпионов с ранними позициями
    for spy, pos in spy_positions:
        if pos is not None:
            order.insert(pos, spy)
    
    # Добавляем остальных шпионов в конец
    for spy, pos in spy_positions:
        if pos is None:
            order.append(spy)
    
    return order


def get_next_player(session: GameSession) -> Player | None:
    """Возвращает следующего игрока для описания."""
    for p in session.players:
        if not p.has_described:
            return p
    return None


def count_votes(session: GameSession) -> dict[int, int]:
    votes: dict[int, int] = {}
    for p in session.players:
        if p.vote_for is not None:
            votes[p.vote_for] = votes.get(p.vote_for, 0) + 1
    return votes


def get_most_voted(session: GameSession) -> tuple[int | None, int]:
    votes = count_votes(session)
    if not votes:
        return None, 0
    max_votes = max(votes.values())
    candidates = [uid for uid, cnt in votes.items() if cnt == max_votes]
    if len(candidates) == 1:
        return candidates[0], max_votes
    return None, max_votes


def check_victory(session: GameSession) -> str | None:
    # В режиме NO_TRAITORS нет шпионов - проверка победы не работает как обычно
    if session.game_type == GameType.NO_TRAITORS:
        # Шпионы не могут победить, так как их нет
        # Мирные могут голосовать, но никто не победит
        return None

    # Шпион угадал персонажа (гибкое сравнение: цифры↔слова, транслит)
    if session.spy_guess and guess_matches(session.spy_guess, session.character):
        # В режиме ALL_TRAITORS шпион победил
        if session.game_type == GameType.ALL_TRAITORS:
            return "all_traitors_win"
        return "spy_guess"

    # Голосование мирных
    most_voted, count = get_most_voted(session)
    if most_voted is not None:
        total_players = len(session.players)
        # Большинство (больше половины) или все проголосовали
        voted = sum(1 for p in session.players if p.vote_for is not None)
        target = session.get_player(most_voted)

        if not target:
            return None

        # Если проголосовали за мирного — ошибка!
        if target.role in (Role.CIVILIAN, Role.CONFUSED) and voted >= total_players // 2 + 1:
            return "civilian_caught"

        # Если проголосовали за провокатора — спровоцированы!
        if target.role == Role.PROVOCATEUR and voted >= total_players // 2 + 1:
            return "provocateur_caught"

        # Если проголосовали за шпиона
        if target.role == Role.SPY and voted >= total_players // 2 + 1:
            # Проверяем, остались ли ещё шпионы
            remaining_spies = sum(1 for p in session.players if p.role == Role.SPY and p.user_id != target.user_id)
            if remaining_spies > 0:
                return "spy_caught_continue"
            return "civilians"

        # Если проголосовали все — и ничья, объявляем ничью/продолжение
        if voted == total_players:
            # Если за шпиона проголосовало меньше половины
            if target.role == Role.SPY and count < total_players // 2 + 1:
                return None
    return None
