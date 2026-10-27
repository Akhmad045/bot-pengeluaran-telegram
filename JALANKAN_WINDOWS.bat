@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
py -3 --version >nul 2>&1
if not errorlevel 1 goto launcher
python --version >nul 2>&1
if not errorlevel 1 goto python
echo Python belum terpasang. Baca README.html untuk langkah pemasangan.
goto done
:launcher
py -3 bot.py
goto done
:python
python bot.py
:done
echo.
pause
endlocal
