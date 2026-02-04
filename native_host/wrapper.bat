@echo off

REM 默认 INFO；如果外部已经设置了 RSS_NATIVE_LOG_LEVEL，则不覆盖
if "%RSS_NATIVE_LOG_LEVEL%"=="" set "RSS_NATIVE_LOG_LEVEL=INFO"

REM 日志目录保持现状（feedly_native_host.py 默认写到 native_host\logs）
REM if "%RSS_NATIVE_LOG_DIR%"=="" set "RSS_NATIVE_LOG_DIR=%~dp0logs"

"C:\Users\coolx\scoop\apps\python\current\python.exe" -u "%~dp0feedly_native_host.py" %*