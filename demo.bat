@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM  CoffeeCounter demo launcher
REM  Builds an isolated demo container (separate name/port/data
REM  from any real deployment), seeds it with demo users and
REM  ~2.5 years of test events, and opens it in your browser.
REM
REM  Usage:
REM    demo.bat            start (build on first run) and seed if empty
REM    demo.bat reset       wipe the demo container + data, start fresh
REM    demo.bat stop        stop and remove the demo container
REM ============================================================

set CONTAINER_NAME=coffeecounter-demo
set IMAGE_NAME=coffeecounter:demo
set HOST_PORT=3900
set APPDATA_DIR=%~dp0demo-data

where docker >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Docker was not found on PATH. Install Docker Desktop first:
    echo         https://www.docker.com/products/docker-desktop/
    pause
    exit /b 1
)

if /I "%1"=="stop" goto :stop
if /I "%1"=="reset" goto :reset
goto :start

:stop
echo Stopping and removing %CONTAINER_NAME% ...
docker rm -f %CONTAINER_NAME% >nul 2>nul
echo Done. Demo data on disk was kept at "%APPDATA_DIR%".
goto :eof

:reset
echo Removing existing demo container and data for a clean run ...
docker rm -f %CONTAINER_NAME% >nul 2>nul
if exist "%APPDATA_DIR%" rmdir /s /q "%APPDATA_DIR%"
goto :start

:start
if not exist "%APPDATA_DIR%" mkdir "%APPDATA_DIR%"

echo Building the demo image (first run only takes a bit longer) ...
docker build -t %IMAGE_NAME% "%~dp0."
if errorlevel 1 (
    echo [ERROR] Docker build failed. Scroll up for details.
    pause
    exit /b 1
)

docker inspect %CONTAINER_NAME% >nul 2>nul
if not errorlevel 1 (
    echo Found an existing demo container, starting it ...
    docker start %CONTAINER_NAME% >nul
) else (
    echo Starting a fresh demo container on http://localhost:%HOST_PORT%/ ...
    docker run -d ^
        --name %CONTAINER_NAME% ^
        -p %HOST_PORT%:3000 ^
        -e TZ=Europe/Berlin ^
        -e BASE_URL=http://localhost:%HOST_PORT%/ ^
        -e APP_DATA_PATH=/app/config ^
        -e DB_PATH=/app/config/coffeecounter.sqlite ^
        -e COFFEECOUNTER_AUTH_MODE=both ^
        -e COFFEECOUNTER_PIN_LENGTH=4 ^
        -e TRUST_PROXY=false ^
        -v "%APPDATA_DIR%:/app/config" ^
        %IMAGE_NAME% >nul
    if errorlevel 1 (
        echo [ERROR] Could not start the container. Is port %HOST_PORT% already in use?
        pause
        exit /b 1
    )
)

echo Waiting for the app to come up ...
set READY=0
for /L %%i in (1,1,20) do (
    curl -s -o nul -w "%%{http_code}" http://localhost:%HOST_PORT%/api/health > "%TEMP%\cc_health.txt" 2>nul
    set /p HEALTH=<"%TEMP%\cc_health.txt"
    if "!HEALTH!"=="200" (
        set READY=1
        goto :ready
    )
    timeout /t 1 /nobreak >nul
)
:ready
if "!READY!"=="0" (
    echo [WARN] App did not respond in time — check "docker logs %CONTAINER_NAME%".
) else (
    echo App is up.
)

echo Seeding demo data (skipped automatically if it's already there) ...
docker exec %CONTAINER_NAME% python scripts/seed_demo.py

echo.
echo ================================================
echo  CoffeeCounter demo is running:
echo    http://localhost:%HOST_PORT%/
echo.
echo  Demo PINs (also printed above on first seed):
echo    Admin -^> 1111   (Demo Admin)
echo    User  -^> 2222   (Mira)
echo    User  -^> 3333   (Jonas)
echo.
echo  Run "demo.bat reset" for a completely fresh demo,
echo  or "demo.bat stop" to shut it down.
echo ================================================
echo.

start "" http://localhost:%HOST_PORT%/

pause
