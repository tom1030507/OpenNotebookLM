@echo off
REM OpenNotebookLM Docker Stop Script for Windows

echo ========================================
echo      Stopping OpenNotebookLM Services   
echo ========================================

REM Stop all containers
echo Stopping all containers...
docker-compose down

REM Optional: Remove volumes (uncomment if needed)
REM echo Removing volumes...
REM docker-compose down -v

echo.
echo √ All services have been stopped.
echo.
echo To restart services, run: start.bat
echo To remove all data and volumes, run: docker-compose down -v
echo.
pause
