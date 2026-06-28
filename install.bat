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
echo [1/5] 檢查 yt-dlp...
if not exist "bin\yt-dlp.exe" (
    echo 下載 yt-dlp...
    curl -L "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe" -o "bin\yt-dlp.exe"
)

echo [2/5] 檢查 ffmpeg...
if not exist "bin\ffmpeg.exe" (
    echo 下載 ffmpeg...
    curl -L "https://github.com/yt-dlp/yt-dlp/releases/latest/download/ffmpeg.exe" -o "bin\ffmpeg.exe" 2>nul || (
        echo 請手動下載 ffmpeg 放入 bin\ 資料夾
    )
)

echo [3/5] 安裝背景服務...
schtasks /delete /tn "YTDownloaderServer" /f >nul 2>&1
schtasks /create /tn "YTDownloaderServer" /tr "\"%~dp0YTDownloaderServer.exe\"" /sc ONLOGON /ru "%USERNAME%" /f >nul

echo [4/5] 啟動服務...
schtasks /run /tn "YTDownloaderServer" >nul
timeout /t 3 >nul

echo [5/5] 輸入序號...
echo ────────────────────────────────────
:input_license
set /p LICENSE_KEY=請輸入序號：
if "%LICENSE_KEY%"=="" (
    echo 序號不能空白，請重新輸入。
    goto input_license
)

for /f "delims=" %%i in ('curl -s -X POST http://127.0.0.1:8765/license/activate -H "Content-Type: application/json" -d "{\"license\":\"%LICENSE_KEY%\"}"') do set RESULT=%%i

echo %RESULT% | findstr "\"valid\": true" >nul
if %errorlevel%==0 (
    echo ✓ 序號啟用成功！
) else (
    echo ✗ 啟用失敗，請確認序號正確
    set /p RETRY=重試？(y/n)：
    if /i "%RETRY%"=="y" goto input_license
)

echo.
echo ════════════════════════════════════
echo   ✓ 安裝完成！
echo ════════════════════════════════════
echo   請到 chrome://extensions/ 載入
echo   extension 資料夾。
echo ════════════════════════════════════
pause
