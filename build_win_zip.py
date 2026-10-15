#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_win_zip.py - 打包 Windows 发布用 zip
===========================================
把「可运行所需文件」打包成 desktop_fish_pet-win-<版本>.zip，
排除 git 仓库、Python 缓存、凭据与开发辅助脚本等无关文件。
版本号取自 version.txt（单行，如 1.0.0）；双击运行即用。

包含在包内的（用户运行所需）：
    主程序        desktop_fish_pet.py
    启动脚本      启动小鱼.bat
    依赖清单      requirements.txt
    默认配置      fish_pet_config.json
    使用说明      README.md
    鱼素材目录    鱼/
明确排除的（与用户运行无关）：
    .git / __pycache__ / .env / .env.example / .gitignore
    version.txt / CHANGELOG.md
    pull.py / push.py / release.py / _gh_release.py / build_win_zip.py
    以及任何 .zip 产物
"""
import io
import os
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))

# 需要排除的目录
EXCLUDE_DIRS = {".git", "__pycache__", "fpk", "build", "dist"}

# 需要排除的文件（凭据 / 版本源 / 开发辅助脚本 / 打包脚本自身）
EXCLUDE_FILES = {
    ".env", ".env.example", ".gitignore",
    "version.txt", "CHANGELOG.md",
    "pull.py", "push.py", "release.py", "_gh_release.py",
    "build_win_zip.py",
}


def get_version():
    p = os.path.join(ROOT, "version.txt")
    if not os.path.exists(p):
        return "0.0.0"
    with io.open(p, encoding="utf-8") as f:
        text = f.read().strip()
    return text.split()[0] if text else "0.0.0"


def build(ver):
    out = os.path.join(ROOT, "desktop_fish_pet-win-%s.zip" % ver)
    if os.path.exists(out):
        os.remove(out)
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            rel = os.path.relpath(dirpath, ROOT)
            parts = rel.split(os.sep)
            if any(p in EXCLUDE_DIRS for p in parts):
                continue
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for fn in filenames:
                if fn in EXCLUDE_FILES or fn.lower().endswith(".zip"):
                    continue
                full = os.path.join(dirpath, fn)
                if os.path.abspath(full) == os.path.abspath(out):
                    continue
                z.write(full, os.path.join(rel, fn))
                count += 1
    size = os.path.getsize(out)
    print("[完成] 已生成：%s" % os.path.basename(out))
    print("        路径：%s" % out)
    print("        文件数：%d    大小：%d 字节" % (count, size))
    return out


def countdown_close(seconds=5):
    """完成后显示说明并倒数 5 4 3 2 1，然后退出。"""
    sys.stdout.write("\n窗口将在 %d 秒后自动关闭：" % seconds)
    sys.stdout.flush()
    for i in range(seconds, 0, -1):
        sys.stdout.write(" %d" % i)
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write("\n")


def main():
    os.chdir(ROOT)
    ver = get_version()
    print("[信息] 打包 Windows 发布包，版本：%s" % ver)
    build(ver)
    return 0


if __name__ == "__main__":
    rc = 1
    try:
        rc = main()
    except KeyboardInterrupt:
        rc = 0
    except Exception:
        import traceback
        rc = 1
        print("")
        print("[异常] 打包出错，详情如下：")
        traceback.print_exc()
    countdown_close()
    sys.exit(rc)
