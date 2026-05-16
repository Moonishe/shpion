@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ===========================================
echo   🤖 Бот "Шпион" - запуск...
echo ===========================================
echo.

if not exist .venv\Scripts\python.exe (
    echo ❌ Виртуальное окружение не найдено!
    echo 📝 Запустите: uv venv
    echo    затем: uv pip install -r requirements.txt
    pause
    exit /b 1
)

if not exist .env (
    echo ❌ Файл .env не найден!
    echo 📝 Создайте файл .env с содержимым:
    echo    BOT_TOKEN=ваш_токен_от_BotFather
    pause
    exit /b 1
)

echo ✅ Запуск бота...
echo 📱 Нажмите Ctrl+C для остановки
echo.

.venv\Scripts\python -u -m bot

if %errorlevel% neq 0 (
    echo.
    echo ❌ Бот завершился с ошибкой.
    pause
)
