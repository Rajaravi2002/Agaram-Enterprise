@echo off
title Agaram Finance Management System
color 0A
echo ================================================
echo   Agaram Finance Management System  (SQLite)
echo ================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not installed. Get it from https://python.org
    pause & exit /b 1
)

if not exist ".deps_installed" (
    echo Installing Python dependencies...
    pip install -r requirements.txt
    echo. > .deps_installed
)

echo Starting server at http://localhost:5000
echo Default login:  admin / admin123
echo Press Ctrl+C to stop.
echo.
start /b "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:5000"
python run.py
pause
