@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run: creating the project environment...
  py -m venv .venv
  if errorlevel 1 goto fail
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 goto fail
)
echo Open http://127.0.0.1:8765 in your browser.
echo Keep this window open. Press Ctrl+C to stop the dashboard.
.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8765
goto end
:fail
echo Setup failed. Check your Python installation and internet connection.
pause
:end
