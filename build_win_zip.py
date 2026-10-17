#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_win_zip.py - 打包 Windows 发布用 zip
===========================================
只把 app/ 目录（程序本体：主程序 + 启动脚本 + 依赖清单 + 配置 + 鱼素材）
打包成 desktop_fish_pet-win-<版本>.zip，并附带根目录的 README.md。
开发辅助脚本（pull.py / push.py / release.py / _gh_release.py 等）与
凭据、版本源文件都在仓库根目录，不在 app/ 内，因此不会被打进包里。
版本号取自 version.txt（单行，如 1.0.0）；双击运行即用。

包内结构（解压即可运行，保持 app/ 内相对目录）：
    desktop_fish_pet.py
    启动小鱼.bat
    data/                  # 运行期数据（首次运行自动生成）
    html/                  # settings.html / shop.html
    resource/              # 鱼/、炮台/、音效/ 等素材
    support/               # requirements.txt 等辅助文件
    README.md
"""
import io
import os
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(ROOT, "app")

# app 内需要排除的（缓存 / 运行时个人数据 / 压缩包产物等）
EXCLUDE_DIRS = {"__pycache__"}
EXCLUDE_FILES = {".gitignore", "fish_pet_config.json"}


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
        # 1) 打包 app/ 目录的全部内容（扁平化到 zip 根，直接可运行）
        for dirpath, dirnames, filenames in os.walk(APP_DIR):
            rel = os.path.relpath(dirpath, APP_DIR)
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
                arc = fn if rel == "." else os.path.join(rel, fn)
                z.write(full, arc)
                count += 1
        # 2) 附带根目录的 README.md（如有）
        readme = os.path.join(ROOT, "README.md")
        if os.path.exists(readme):
            z.write(readme, "README.md")
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
    if not os.path.isdir(APP_DIR):
        print("[错误] 未找到 app/ 目录，无法打包")
        return 1
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
