@echo off
setlocal
cd /d "%~dp0"

echo 正在检查并安装依赖（requirements.txt）...
python -m pip install -q -r requirements.txt
if %errorlevel% neq 0 (
  echo [警告] 静默安装失败，尝试普通方式安装...
  pip install -r requirements.txt
)

where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw "desktop_fish_pet.py"
) else (
  start "" python "desktop_fish_pet.py"
)
endlocal
