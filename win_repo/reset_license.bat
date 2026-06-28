@echo off
chcp 65001 >nul
echo 正在重置授權...
set APP_DIR=%~dp0
del /f /q "%APP_DIR%license.key" >nul 2>&1
del /f /q "%APP_DIR%activated_licenses.json" >nul 2>&1
echo ✓ 授權已重置，請重新輸入序號
pause
