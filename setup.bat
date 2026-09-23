@echo off
title Agaram Finance – Setup
color 0B
echo ================================================
echo   Agaram Finance – First-Time Setup  (SQLite)
echo ================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install from https://python.org
    pause & exit /b 1
)

echo [1/3] Installing Python dependencies...
pip install -r requirements.txt
echo.

echo [2/3] Creating folders...
if not exist "backups" mkdir backups
if not exist "reports" mkdir reports
if not exist "logs"    mkdir logs
echo Done.
echo.

echo [3/3] Initialising SQLite database...
python -c "from app import create_app; create_app(); print('Database OK')"
echo.

set /p SEED="Load sample data for testing? (y/n): "
if /i "%SEED%"=="y" python seed_data.py

echo.
echo ================================================
echo  Setup complete!  Run start.bat to launch.
echo  Browser : http://localhost:5000
echo  Login   : admin / admin123
echo ================================================
pause
