@echo off
setlocal

rem pushd also maps UNC paths (network shares like \\NAS\...) to a drive letter -
rem "cd /d" would fail there.
pushd "%~dp0"

rem venv intentionally LOCAL: pip/Python on a network share is extremely slow.
set "VENV_DIR=%LOCALAPPDATA%\CoffeeCounter\venv"
set "PORT=3900"
set "DATA_DIR=%CD%\demo-data"
set "DB_PATH=%DATA_DIR%\coffeecounter.sqlite"

rem Optional first argument: "demo.bat reset" wipes the demo data first,
rem "demo.bat <port>" runs on another port (default 3900).
if /I "%1"=="reset" (
    echo Resetting demo data ("%DATA_DIR%") ...
    if exist "%DATA_DIR%" rmdir /s /q "%DATA_DIR%"
) else (
    if not "%1"=="" set "PORT=%1"
)

echo ==========================================================
echo    CoffeeCounter - demo server (local, no Docker needed)
echo.
echo    URL:   http://localhost:%PORT%
echo    PINs:  Admin =^> 1111   (Demo Admin)
echo           User  =^> 2222   (Mira)
echo           User  =^> 3333   (Jonas)
echo.
echo    Fresh demo:  demo.bat reset
echo    Stop:        Ctrl+C in this window (data stays on disk)
echo ==========================================================
echo.

REM --- Find Python (python or py -3) ---
set "PY=python"
where python >nul 2>nul
if errorlevel 1 set "PY=py -3"

REM --- Create / update the Python environment ---
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [1/3] Creating Python environment "%VENV_DIR%" ...
    %PY% -m venv "%VENV_DIR%" || goto :err
    echo [2/3] Installing dependencies ...
    "%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip >nul
    "%VENV_DIR%\Scripts\python.exe" -m pip install -r requirements.txt || goto :err
) else (
    echo [1/3] Python environment "%VENV_DIR%" present.
    echo [2/3] Checking dependencies ...
    "%VENV_DIR%\Scripts\python.exe" -c "import fastapi, webauthn, itsdangerous, uvicorn" 2>nul || (
        echo       - installing requirements.txt ...
        "%VENV_DIR%\Scripts\python.exe" -m pip install -r requirements.txt || goto :err
    )
)

if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"

REM --- Env for the demo instance (data lives in .\demo-data, separate
REM      from any real deployment, so nothing can collide) ---
set "APP_DATA_PATH=%DATA_DIR%"
set "DB_PATH=%DB_PATH%"
set "BASE_URL=http://localhost:%PORT%/"
set "COFFEECOUNTER_AUTH_MODE=both"
set "COFFEECOUNTER_PIN_LENGTH=4"
set "SESSION_TIMEOUT=28800"
set "TRUST_PROXY=false"
set "USE_CF_CONNECTING_IP=false"

echo [3/3] Seeding demo data (skipped automatically if already there) ...
"%VENV_DIR%\Scripts\python.exe" scripts\seed_demo.py || goto :err

echo.
echo Starting the demo server ... the browser opens in a few seconds.
rem ping = reliable delay without console input (timeout.exe would complain otherwise)
start "" /b cmd /c "ping -n 4 127.0.0.1 >nul & start http://localhost:%PORT%"

"%VENV_DIR%\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%
goto :eof

:err
echo.
echo  ERROR - check the message above.
pause
