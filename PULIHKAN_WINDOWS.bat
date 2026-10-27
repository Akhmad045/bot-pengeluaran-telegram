@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Hentikan bot terlebih dahulu. File cadangan harus berupa database .db.
where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 cadangan.py restore
) else (
    python cadangan.py restore
)
pause
