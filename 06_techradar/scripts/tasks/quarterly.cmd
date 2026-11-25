@echo off
chcp 65001 >nul
cd /d "D:\00_skiill_ku"

set "PLAYWRIGHT_BROWSERS_PATH=D:\00_skiill_ku\01_crawler\runtime\Playwright"
@"D:\00_skiill_ku\.venv\Scripts\python.exe" "D:\00_skiill_ku\06_techradar\scripts\lifecycle_run.py" --job quarterly >> "D:\00_skiill_ku\_logs\scheduler\quarterly.log" 2>&1
exit /b %ERRORLEVEL%
