# 更新日志

本项目所有重要变更都记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

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
