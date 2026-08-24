@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM OpenNotebookLM production Compose launcher.

echo ========================================
echo    OpenNotebookLM Docker Quick Start
echo ========================================

if not exist .env (
    echo Creating .env file from .env.example...
    copy /y .env.example .env >nul
    if errorlevel 1 (
        echo ERROR: Could not create .env.
        exit /b 1
    )
    echo .env file created.
)

findstr /B /C:"JWT_SECRET_KEY=" ".env" >nul 2>nul
if errorlevel 1 goto missing_jwt_secret
findstr /R /C:"^JWT_SECRET_KEY= *$" ".env" >nul 2>nul
if not errorlevel 1 goto missing_jwt_secret
goto jwt_secret_present

:missing_jwt_secret
    echo ERROR: JWT_SECRET_KEY is blank in .env.
    echo Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"
    echo Set that value in .env, then run this launcher again.
    exit /b 1

:jwt_secret_present

where docker >nul 2>nul
if errorlevel 1 (
    echo ERROR: Docker is not installed. Please install Docker Desktop first.
    exit /b 1
)

call docker compose version >nul 2>nul
if errorlevel 1 (
    echo ERROR: Docker Compose v2 is not available. Install the Docker Compose plugin.
    exit /b 1
)

set "REQUESTED_PROFILE=%~1"
set "PROFILE_ARGS="
if "!REQUESTED_PROFILE!"=="with-ollama" (
    echo Starting with Ollama for local LLM support...
    set "PROFILE_ARGS=--profile with-ollama"
) else if "!REQUESTED_PROFILE!"=="with-cache" (
    echo Starting with Redis cache...
    set "PROFILE_ARGS=--profile with-cache"
) else if "!REQUESTED_PROFILE!"=="full" (
    echo Starting with all optional services...
    set "PROFILE_ARGS=--profile with-ollama --profile with-cache"
) else if not "!REQUESTED_PROFILE!"=="" (
    echo ERROR: Unknown profile. Use with-ollama, with-cache, or full.
    exit /b 2
)

echo Validating production configuration...
call docker compose !PROFILE_ARGS! config --quiet
if errorlevel 1 (
    set "COMPOSE_STATUS=!ERRORLEVEL!"
    echo ERROR: Compose failed to validate configuration ^(exit !COMPOSE_STATUS!^).
    exit /b !COMPOSE_STATUS!
)

echo Starting services...
call docker compose !PROFILE_ARGS! up -d --build --wait --wait-timeout 900
if errorlevel 1 (
    set "COMPOSE_STATUS=!ERRORLEVEL!"
    echo ERROR: Compose failed to start services ^(exit !COMPOSE_STATUS!^).
    exit /b !COMPOSE_STATUS!
)

echo.
echo ========================================
echo    OpenNotebookLM is starting up!
echo ========================================
echo.
echo Services:
echo   - Backend API: http://localhost:8000
echo   - API Docs: http://localhost:8000/docs
echo   - Frontend: http://localhost:3000

if not "!PROFILE_ARGS!"=="" (
    echo !PROFILE_ARGS! | findstr /C:"ollama" >nul
    if not errorlevel 1 echo   - Ollama: http://ollama:11434 inside Compose ^(no host port^)
    echo !PROFILE_ARGS! | findstr /C:"cache" >nul
    if not errorlevel 1 echo   - Redis: redis:6379 inside Compose ^(no host port^)
)

echo.
echo To stop all services, run: docker compose down
echo To view logs, run: docker compose logs -f
exit /b 0
