@echo off
chcp 65001 > nul
setlocal

:: Переходим в директорию скрипта, чтобы запуск работал из любого места
cd /d "%~dp0"

echo [INFO] Проверка виртуального окружения...

if not exist venv (
    echo [SETUP] Виртуальное окружение не найдено. Создаем...
    python -m venv venv

    if errorlevel 1 (
        echo [ERROR] Python не найден или произошла ошибка при создании venv.
        echo Убедитесь, что Python установлен и добавлен в PATH.
        pause
        exit /b
    )

    echo [SETUP] Активация venv и установка библиотек...
    call venv\Scripts\activate

    echo [SETUP] Обновление pip...
    python -m pip install --upgrade pip

    echo [SETUP] Установка зависимостей из requirements.txt...
    pip install -r requirements.txt

    if errorlevel 1 (
        echo [ERROR] Ошибка при установке зависимостей.
        pause
        exit /b
    )

    echo [SETUP] Установка завершена!
) else (
    echo [INFO] Виртуальное окружение найдено. Запуск...
    call venv\Scripts\activate
)

echo.
echo [START] Запускаем приложение...
echo.

:: Запуск основного скрипта
python main.py

:: Если приложение упало, не закрываем окно сразу, чтобы видеть ошибку
if errorlevel 1 (
    echo.
    echo [ERROR] Приложение завершилось с ошибкой.
    pause
)

deactivate
endlocal