# 更新日志

本项目所有重要变更都记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.1] - 未发布

### 新增
- 独立打包脚本 `build_win_zip.py`：双击即可生成干净的 Windows 发布包 `desktop_fish_pet-win-<版本>.zip`，只含运行所需文件，排除 git 仓库、凭据与开发辅助脚本。
- 仓库结构整理：程序本体移入 `app/` 目录（主程序 / 启动脚本 / 依赖清单 / 配置 / `鱼/` 素材），Git 辅助脚本与版本、说明文件留在根目录，职责更清晰。
- 根目录新增开发用 `启动小鱼.bat`（带控制台输出，便于调试），与 `app/` 内面向用户的无控制台启动脚本区分。

### 变更
- `release.py` 改为调用 `build_win_zip.py` 出包；`_gh_release.py` 上传目标同步改为 `desktop_fish_pet-win-<版本>.zip`。
- 发布包不再包含 `fish_pet_config.json`（运行时个人数据），用户首次运行由程序自动生成默认存档。
- 血条改为：鱼受击后显示，最后一次受击 3 秒后自动隐藏（原为受击后永久显示）。
- 炮台重绘：金属梯形炮管 + 发光底座，并加长炮管让比例更自然。

### 修复
- 修复 `push.py` 中 `get_version()` 重复调用 `f.read()` 导致的 `IndexError`（无参数双击运行时崩溃）。
- `pull.py` / `push.py` / `release.py` 增加全局异常捕获（出错不再一闪关闭，会打印堆栈并等待按键），收尾改为倒数 `5 4 3 2 1` 自动关闭。
- 增加未安装 / 未加入 PATH 时 `git` 缺失的明确提示。

## [1.0.0] - 2026-10-15

首个发布版本。

### 新增
- 桌面小鱼宠物主程序 `desktop_fish_pet.py`：基于 Win32 `UpdateLayeredWindow` 的逐像素透明窗口，边缘无毛边，透明区域鼠标点击自动穿透，不挡桌面操作。
- 自然游动：小鱼在屏幕工作区内自由游动，随机转向 / 停留 / 猛冲，贴边反弹。
- 鼠标交互：左键拖动放置小鱼；轻点一下小鱼受惊猛窜。
- 系统托盘 / 右键菜单：更换品种、调整大小、添加 / 移除小鱼、退出。
- 多鱼共存：可同时饲养多条鱼，运行时配置保存在 `fish_pet_config.json`。
- 一键启动脚本 `启动小鱼.bat`：优先用 `pythonw` 无控制台方式启动，无则回退 `python`。
- Git 辅助脚本：`pull.py`（拉取变基）/ `push.py`（提交并推送）/ `release.py`（打包发布）/ `_gh_release.py`（GitHub Release 上传），均支持 `.env` 的 `GITHUB_TOKEN` 凭据认证。
- 版本来源文件 `version.txt` 与 `.env.example` 凭据样例。

### 说明
- 仅依赖 `Pillow` 与 `pystray`（见 `requirements.txt`），Python 3.8+ 自带 `tkinter`。
- 需要把 `鱼/` 素材目录与可执行文件放在同一目录运行。
