@echo off
setlocal
cd /d "%~dp0"

set PY=python
python --version >nul 2>&1
if errorlevel 1 set PY=py
%PY% --version >nul 2>&1
if errorlevel 1 (
  echo [X] Python not found. Install Python 3.10+ and open a new window.
  goto :fail
)
node --version >nul 2>&1
if errorlevel 1 (
  echo [X] Node.js not found. Install Node.js 20+ and open a new window.
  goto :fail
)

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo [!] Created .env - fill in YUANBAO_API_KEY and LLM_API_KEY, save, then run this file again.
  notepad ".env"
  goto :fail
)

echo [1/3] Installing Python packages...
%PY% -m pip install -q -r requirements.txt
if errorlevel 1 goto :error

echo [2/3] Building the web page...
pushd frontend
call npm install --no-audit --no-fund
if errorlevel 1 (popd & goto :error)
call npm run build
if errorlevel 1 (popd & goto :error)
popd

echo [3/3] Starting at http://localhost:8011  (close this window to stop)
start "" http://localhost:8011
%PY% -m uvicorn backend.main:app --port 8011
goto :fail

:error
echo [X] Something went wrong. Screenshot this window and send it to Claude.
:fail
pause
