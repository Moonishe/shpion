import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в .env")

# Админ бота (может управлять персонажами)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "dutysissy")


def is_admin(username: str | None) -> bool:
    """Проверяет, является ли пользователь админом."""
    if not username:
        return False
    return username.lower() == ADMIN_USERNAME.lower()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "bot.db"
CHARACTERS_PATH = DATA_DIR / "characters.json"


def load_characters_data() -> dict:
    """Загружает полные данные персонажей с категориями."""
    if not CHARACTERS_PATH.exists():
        return {"categories": {}}
    with open(CHARACTERS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_categories() -> dict[str, dict]:
    """Возвращает словарь категорий с названиями и эмодзи."""
    data = load_characters_data()
    return data.get("categories", {})


def get_characters_by_category(categories_list: list[str] | None = None) -> list[str]:
    """Возвращает список персонажей по списку категорий или всех."""
    data = load_characters_data()
    all_cats = data.get("categories", {})
    
    if not categories_list or "all" in categories_list:
        all_chars = []
        for cat_data in all_cats.values():
            all_chars.extend(cat_data.get("characters", []))
        return all_chars
    
    result = []
    for cat_id in categories_list:
        if cat_id in all_cats:
            result.extend(all_cats[cat_id].get("characters", []))
    return result


def save_characters_data(data: dict) -> None:
    """Сохраняет данные персонажей в файл."""
    with open(CHARACTERS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_custom_character(character: str) -> bool:
    """Добавляет кастомного персонажа. Возвращает True если успешно."""
    data = load_characters_data()
    categories = data.get("categories", {})
    
    # Создаём категорию custom если её нет
    if "custom" not in categories:
        categories["custom"] = {
            "name": "Кастомные",
            "emoji": "✨",
            "characters": []
        }
    
    custom_chars = categories["custom"].get("characters", [])
    
    # Проверяем, нет ли уже такого персонажа
    if character in custom_chars:
        return False
    
    custom_chars.append(character)
    categories["custom"]["characters"] = custom_chars
    data["categories"] = categories
    save_characters_data(data)
    return True


def remove_custom_character(character: str) -> bool:
    """Удаляет кастомного персонажа. Возвращает True если успешно."""
    data = load_characters_data()
    categories = data.get("categories", {})
    
    if "custom" not in categories:
        return False
    
    custom_chars = categories["custom"].get("characters", [])
    
    if character not in custom_chars:
        return False
    
    custom_chars.remove(character)
    categories["custom"]["characters"] = custom_chars
    data["categories"] = categories
    save_characters_data(data)
    return True


def get_custom_characters() -> list[str]:
    """Возвращает список кастомных персонажей."""
    data = load_characters_data()
    categories = data.get("categories", {})
    if "custom" in categories:
        return categories["custom"].get("characters", [])
    return []


def clear_custom_characters() -> None:
    """Очищает список кастомных персонажей."""
    data = load_characters_data()
    categories = data.get("categories", {})
    if "custom" in categories:
        categories["custom"]["characters"] = []
        data["categories"] = categories
        save_characters_data(data)


def get_category_name(categories_list: list[str] | None = None) -> str:
    """Возвращает названия категорий через запятую."""
    if not categories_list or "all" in categories_list:
        return "🎲 Все категории"
    cats = get_categories()
    names = []
    for c in categories_list:
        if c in cats:
            cat = cats[c]
            names.append(f"{cat.get('emoji', '')} {cat.get('name', c)}")
        else:
            names.append(c)
    return ", ".join(names) if names else "🎲 Все категории"

