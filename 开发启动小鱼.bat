@echo off
setlocal
cd /d "%~dp0"
echo [开发模式] 启动桌面小鱼（来自 app/，显示控制台输出便于调试）
echo 正在检查并安装依赖（app/support/requirements.txt）...
python -m pip install -q -r app/support/requirements.txt
if %errorlevel% neq 0 (
  echo [警告] 依赖安装失败，尝试普通方式...
  pip install -r app/support/requirements.txt
)
cd app
python desktop_fish_pet.py
endlocal
