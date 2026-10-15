@echo off
setlocal
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw "desktop_fish_pet.py"
) else (
  start "" python "desktop_fish_pet.py"
)
endlocal
