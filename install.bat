@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ╔══════════════════════════════════╗
echo ║      YT Downloader 安裝程式      ║
echo ╚══════════════════════════════════╝
echo.
echo 【法律聲明與免責聲明】
echo 本軟體僅供個人合法使用。
echo 本軟體不得用於商業用途或大量下載。
echo 繼續安裝即表示您同意上述聲明。
echo ══════════════════════════════════════
pause

echo.
echo [1/4] 停止舊版 server...
taskkill /f /im YTDownloaderServer.exe >nul 2>&1
timeout /t 1 >nul

echo [2/4] 安裝背景服務...
schtasks /delete /tn "YTDownloaderServer" /f >nul 2>&1
schtasks /create /tn "YTDownloaderServer" /tr "\"%~dp0YTDownloaderServer.exe\"" /sc ONLOGON /ru "%USERNAME%" /f >nul

echo [3/4] 啟動服務...
start "" "%~dp0YTDownloaderServer.exe"
timeout /t 3 >nul

echo [4/4] 輸入序號...
echo ────────────────────────────────────

:input_license
set /p LICENSE_KEY=請輸入序號：
if "%LICENSE_KEY%"=="" (
    echo 序號不能空白，請重新輸入。
    goto input_license
)

curl -s -X POST http://127.0.0.1:8765/license/activate ^
  -H "Content-Type: application/json" ^
  -d "{\"license\":\"%LICENSE_KEY%\"}" > tmp_result.txt 2>nul

findstr /C:"\"valid\": true" tmp_result.txt >nul
if %errorlevel%==0 (
    echo ✓ 序號啟用成功！
    del tmp_result.txt
    goto done
) else (
    echo ✗ 啟用失敗，請確認序號正確
    del tmp_result.txt 2>nul
    set /p RETRY=重試？(y/n)：
    if /i "%RETRY%"=="y" goto input_license
)

:done
echo.
echo ════════════════════════════════════
echo   ✓ 安裝完成！
echo ════════════════════════════════════
echo   請到 chrome://extensions/ 載入
echo   extension 資料夾。
echo ════════════════════════════════════
pause
