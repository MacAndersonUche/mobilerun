@echo off
REM Windows startup script for Mobilerun self-hosted backend

echo Starting Mobilerun Self-Hosted Backend...

REM Check Python
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo Error: Python is not installed or not in PATH
    echo Please install Python 3.11 or later from python.org
    pause
    exit /b 1
)

python --version

REM Check backend directory
if not exist "backend" (
    echo Error: backend directory not found
    echo Please run this script from the repository root
    pause
    exit /b 1
)

cd backend

REM Create virtual environment
if not exist "venv" (
    echo Creating Python virtual environment...
    python -m venv venv
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
python -m pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

REM Check for .env
if not exist ".env" (
    echo No .env file found. Creating template...
    (
        echo # Mobilerun Backend Configuration
        echo ALLOW_UNAUTHENTICATED=true
        echo JWT_SECRET=dev-secret-change-in-production
        echo.
        echo # LLM Provider API Keys ^(add at least one^)
        echo GOOGLE_API_KEY=
        echo OPENAI_API_KEY=
        echo ANTHROPIC_API_KEY=
        echo.
        echo # Backend URL ^(for QR codes^)
        echo BACKEND_URL=http://localhost:8000
    ) > .env
    echo Created .env file. Please add your API keys.
)

echo.
echo ================================================
echo   Mobilerun Control Center
echo ================================================
echo.
echo   Backend:  http://localhost:8000
echo   Docs:     http://localhost:8000/docs
echo.
echo   Press Ctrl+C to stop
echo.
echo ================================================
echo.

python main.py

pause
