@echo off
REM OpenNotebookLM Quick Start Script for Windows

echo ========================================
echo    OpenNotebookLM Docker Quick Start    
echo ========================================

REM Check if .env exists, if not copy from example
if not exist .env (
    echo Creating .env file from .env.example...
    copy .env.example .env
    echo √ .env file created. Please update it with your settings.
)

REM Create necessary directories
echo Creating necessary directories...
if not exist data mkdir data
if not exist models mkdir models
if not exist uploads mkdir uploads
if not exist logs mkdir logs
echo √ Directories created

REM Check Docker
where docker >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo × Docker is not installed. Please install Docker Desktop first.
    echo Download from: https://www.docker.com/products/docker-desktop
    pause
    exit /b 1
)

where docker-compose >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo × Docker Compose is not installed. Please install Docker Desktop first.
    pause
    exit /b 1
)

echo √ Docker and Docker Compose are installed

REM Build and start services
echo.
echo Starting services...
echo This may take a few minutes on first run...
echo.

REM Parse arguments
set PROFILE=
if "%1"=="with-ollama" (
    echo Starting with Ollama for local LLM support...
    set PROFILE=--profile with-ollama
)
if "%1"=="with-cache" (
    echo Starting with Redis cache...
    set PROFILE=--profile with-cache
)
if "%1"=="full" (
    echo Starting with all optional services...
    set PROFILE=--profile with-ollama --profile with-cache
)

REM Start Docker Compose
docker-compose up -d %PROFILE%

REM Wait for services to be ready
echo.
echo Waiting for services to be ready...
timeout /t 10 /nobreak >nul

REM Check health
echo.
echo Checking service health...
curl -f http://localhost:8000/healthz >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo √ Backend is running at: http://localhost:8000
    echo √ API docs available at: http://localhost:8000/docs
) else (
    echo ! Backend is not responding yet. It may still be starting...
)

REM Check if frontend exists
if exist frontend (
    echo √ Frontend should be available at: http://localhost:3000
) else (
    echo ! Frontend directory not found. Frontend will not be available.
)

echo.
echo ========================================
echo    OpenNotebookLM is starting up!      
echo ========================================
echo.
echo Services:
echo   • Backend API: http://localhost:8000
echo   • API Docs: http://localhost:8000/docs
echo   • Frontend: http://localhost:3000

if not "%PROFILE%"=="" (
    echo %PROFILE% | findstr /C:"ollama" >nul
    if %ERRORLEVEL% EQU 0 (
        echo   • Ollama: http://localhost:11434
    )
    echo %PROFILE% | findstr /C:"cache" >nul
    if %ERRORLEVEL% EQU 0 (
        echo   • Redis: localhost:6379
    )
)

echo.
echo To stop all services, run: docker-compose down
echo To view logs, run: docker-compose logs -f
echo.
pause
