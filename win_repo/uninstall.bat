@echo off
chcp 65001 >nul
echo 正在移除 YT Downloader...
schtasks /end /tn "YTDownloaderServer" >nul 2>&1
schtasks /delete /tn "YTDownloaderServer" /f >nul 2>&1
taskkill /f /im YTDownloaderServer.exe >nul 2>&1
echo ✓ 已移除背景服務
pause
