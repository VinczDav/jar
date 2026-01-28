@echo off
echo Starting RefLife Scheduler...
echo Press Ctrl+C to stop.
echo.

REM Activate virtual environment if it exists
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

REM Run the scheduler
python manage.py run_scheduler

pause
