@echo off
setlocal
set PROJECT_NAME=Scoring Arena
set SCRIPT_DIR=%~dp0
set RELEASE_DIR=%SCRIPT_DIR%src-tauri\target\release
color 0b

echo ======================================================
echo   %PROJECT_NAME% - Compiling Application
echo ======================================================

echo [1/3] Checking dependencies...
if not exist "%SCRIPT_DIR%node_modules\" (
    echo node_modules folder not found. Running npm install...
    call npm install
)

echo [2/3] Running Tauri build process...
call npm run tauri build
if %ERRORLEVEL% NEQ 0 goto :build_failed

echo [3/3] Copying release artifacts to %SCRIPT_DIR%
if exist "%RELEASE_DIR%\arena-app.exe" copy /Y "%RELEASE_DIR%\arena-app.exe" "%SCRIPT_DIR%arena.exe" >nul

echo.
echo ======================================================
echo   BUILD SUCCESSFUL!
echo ======================================================
echo.
echo Copied artifacts:
echo   %SCRIPT_DIR%arena.exe
echo.
set /p OPEN_DIR="Open the output directory? (y/n): "
if /i "%OPEN_DIR%"=="y" start "" "%SCRIPT_DIR%"
goto :eof

:build_failed
echo.
echo ======================================================
echo   BUILD FAILED! (Error code: %ERRORLEVEL%)
echo ======================================================
pause

endlocal
