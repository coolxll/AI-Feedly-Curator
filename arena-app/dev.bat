@echo off
setlocal
set PROJECT_NAME=Scoring Arena
color 0e

echo ======================================================
echo   %PROJECT_NAME% - Development Mode
echo ======================================================

echo [1/2] Checking dependencies...
if not exist "node_modules\" (
    echo node_modules folder not found. Running npm install...
    call npm install
)

echo [2/2] Starting Tauri dev server...
call npm run tauri dev

endlocal
