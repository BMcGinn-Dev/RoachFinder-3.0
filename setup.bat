@echo off
echo Setting up RoachFinder 3.0...
echo.

python -m venv venv
if errorlevel 1 (
    echo ERROR: Python not found. Make sure Python is installed and added to PATH.
    pause
    exit /b 1
)

echo Activating virtual environment...
call venv\Scripts\activate

echo Installing dependencies...
pip install -r requirements.txt

echo.
echo Setup complete!
echo.
echo To run RoachFinder each week:
echo   1. venv\Scripts\activate
echo   2. python run_week.py
echo.
pause
