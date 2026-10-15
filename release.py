#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""release.py [版本号]
===================
构建源码压缩包 -> 打版本标签 -> 推送标签 -> 创建 GitHub Release 并上传压缩包。
版本号：默认读取 version.txt；也可显式传入（release.py 1.2.0）。
凭据：优先用 .env 中的 GITHUB_TOKEN（无需装 gh）；其次用 gh（需已登录）。
仓库: 读取 .env 的 GITHUB_REPO_URL；缺省回退到桌面小鱼宠物仓库。
"""
import base64
import io
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO_DEFAULT = "RONGLINC93/desktop_fish_pet"

# 不纳入发布压缩包的条目
EXCLUDE_DIRS = {".git", "__pycache__", "fpk", "build", "dist"}
EXCLUDE_FILES = {".env", "version.txt.bak"}


def load_env(path):
    data = {}
    if not os.path.exists(path):
        return data
    with io.open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                data[k.strip()] = v.strip().strip("'").strip('"')
    return data


def get_version():
    p = os.path.join(ROOT, "version.txt")
    if not os.path.exists(p):
        return ""
    with io.open(p, encoding="utf-8") as f:
        t = f.read().strip()
    return t.split()[0] if t else ""


def git_auth_args():
    env = load_env(os.path.join(ROOT, ".env"))
    tok = env.get("GITHUB_TOKEN", "")
    if tok:
        b64 = base64.b64encode(("x-access-token:" + tok).encode("utf-8")).decode("ascii")
        return ["-c", "http.https://github.com/.extraheader=AUTHORIZATION: basic " + b64], True
    return [], False


def run(cmd):
    print("> " + " ".join(cmd))
    return subprocess.run(cmd).returncode


def repo_slug():
    cfg = load_env(os.path.join(ROOT, ".env"))
    url = cfg.get("GITHUB_REPO_URL") or ""
    if url:
        tail = url.rstrip("/").split("/")[-2:]
        if len(tail) == 2 and tail[0] and tail[1]:
            return tail[0] + "/" + tail[1].replace(".git", "")
    return REPO_DEFAULT


def bump_version(ver):
    """发布成功后把 version.txt 的补丁号 +1（进入下一开发版）。"""
    m = re.match(r"^([0-9]+)\.([0-9]+)\.([0-9]+)", ver)
    if not m:
        print("[警告] 无法解析版本号 %s，跳过自动递增" % ver)
        return
    ma, mi, pa = m.groups()
    nxt = "%s.%s.%d" % (ma, mi, int(pa) + 1)
    with io.open(os.path.join(ROOT, "version.txt"), "w", encoding="utf-8") as f:
        f.write(nxt + "\n")
    print("[完成] version.txt 已自动递增：%s -> %s（下一开发版）" % (ver, nxt))


# [Unreleased] 占位提示行中的标记，落成发布版本时需剔除
HINT_MARK = "开发中，变更将记录于此"


def finalize_changelog(ver):
    """发布成功后：把 CHANGELOG 顶部 [Unreleased] 小节落成 [ver] - 当天日期
    （其下累积的变更随之成为本次发布记录），并在顶部新建空的 [Unreleased] 占位。"""
    p = os.path.join(ROOT, "CHANGELOG.md")
    if not os.path.exists(p):
        return
    today = time.strftime("%Y-%m-%d")
    with io.open(p, encoding="utf-8") as f:
        text = f.read()

    m = re.search(r"^##\s*\[Unreleased\]\s*$", text, re.MULTILINE)
    if not m:
        print("[提示] CHANGELOG 中未发现 [Unreleased] 小节，跳过日志落成")
        return
    head_start, head_end = m.start(), m.end()

    # [Unreleased] 内容结束于下一个二级标题（或文件末尾）
    nxt = re.search(r"\n##\s+\[", text[head_end:])
    body_end = head_end + nxt.start() if nxt else len(text)
    body = text[head_end:body_end]

    # 剔除仅属于 [Unreleased] 的占位提示行，保留真实变更
    kept = [ln for ln in body.splitlines() if HINT_MARK not in ln]
    body = "\n".join(kept).strip("\n")
    new_block = ("## [%s] - %s\n\n%s\n" % (ver, today, body)) if body \
        else ("## [%s] - %s\n\n" % (ver, today))

    text = text[:head_start] + new_block + text[body_end:]

    # 顶部插入新的空 [Unreleased] 占位（发布时本行替换为发布日期）
    placeholder = ("## [Unreleased]\n\n"
                   "_开发中，变更将记录于此；发布时本行替换为发布日期。_\n")
    ins = text.find("\n## [")
    if ins != -1:
        text = text[:ins + 1] + "\n" + placeholder + text[ins + 1:]
    else:
        text = text.rstrip() + "\n\n" + placeholder

    with io.open(p, "w", encoding="utf-8") as f:
        f.write(text)
    print("[完成] CHANGELOG：[Unreleased] 已落成 v%s (%s)，并在顶部新建 [Unreleased] 占位"
          % (ver, today))


def push_version_bump(ver):
    """把发布后 version.txt 的版本号自增与 CHANGELOG 更新提交并推送到 origin。"""
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True).stdout.strip()
    if not branch or branch == "HEAD":
        print("[警告] 无法获取当前分支，跳过版本号自增推送")
        return
    st = subprocess.run(["git", "status", "--porcelain", "version.txt", "CHANGELOG.md"],
                        stdout=subprocess.PIPE, text=True).stdout.strip()
    if not st:
        return
    print("[信息] 提交并推送版本号自增与更新日志")
    run(["git", "add", "version.txt", "CHANGELOG.md"])
    run(["git", "commit", "-m", "chore: 发布 v%s 后更新版本号与更新日志" % ver])
    auth, _ = git_auth_args()
    run(["git"] + auth + ["push", "origin", branch])


def main():
    os.chdir(ROOT)
    try:
        subprocess.run(["git", "--version"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("[错误] 未找到 git，请先安装 Git for Windows 并确认已加入 PATH。")
        return 1
    ver = sys.argv[1] if len(sys.argv) > 1 else ""
    if not ver:
        ver = get_version()
    if not ver:
        print("[错误] 无法从 version.txt 读取版本号，请显式指定：release.py 1.2.0")
        return 1
    print("[信息] 发布版本：%s" % ver)
    print("[信息] 目标仓库：%s" % repo_slug())

    # 版本号格式校验
    if not re.match(r"^\d+\.\d+\.\d+$", ver):
        print("[错误] 版本号格式应为 x.y.z，例如 1.2.0")
        return 1

    # 工作区检查（建议先 push）
    r = subprocess.run(["git", "status", "--porcelain"],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.stdout.strip():
        print("[提示] 存在未提交改动，建议先运行「push.py」再发布")

    # ---- 1/3 构建 Windows 发布包 ----
    print("")
    print("=== 1/3 构建 Windows 发布包 ===")
    dist = os.path.join(ROOT, "desktop_fish_pet-win-%s.zip" % ver)
    if run([sys.executable, os.path.join(ROOT, "build_win_zip.py")]) != 0:
        print("[错误] 构建失败")
        return 1
    if not os.path.exists(dist):
        print("[错误] 未找到构建产物 %s" % dist)
        return 1

    # ---- 2/3 打标签并推送 ----
    print("")
    print("=== 2/3 创建并推送版本标签 v%s ===" % ver)
    run(["git", "tag", "-a", "v%s" % ver, "-m", "v%s" % ver])
    auth, _ = git_auth_args()
    rc = run(["git"] + auth + ["push", "origin", "v%s" % ver])
    if rc != 0:
        print("[警告] 标签推送失败（若远程已存在该标签可忽略）")
    else:
        print("[完成] 标签 v%s 已在远程" % ver)

    # ---- 3/3 创建 Release 并上传资产 ----
    print("")
    print("=== 3/3 创建 GitHub Release 并上传压缩包 ===")
    cfg = load_env(os.path.join(ROOT, ".env"))
    tok = cfg.get("GITHUB_TOKEN", "")
    rel_rc = 1
    if tok:
        print("[凭据] 使用 .env 中的 GITHUB_TOKEN")
        rel_rc = run([sys.executable, os.path.join(ROOT, "_gh_release.py"), ver])
    else:
        if subprocess.run(["where", "gh"], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0:
            print("[凭据] 使用 gh")
            if subprocess.run(["gh", "auth", "status"],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0:
                if subprocess.run(["gh", "release", "view", "v%s" % ver, "--repo", repo_slug()],
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL).returncode != 0:
                    run(["gh", "release", "create", "v%s" % ver, dist,
                         "--repo", repo_slug(), "--title", "v%s" % ver,
                         "--notes", "桌面小鱼宠物 v%s" % ver])
                else:
                    run(["gh", "release", "upload", "v%s" % ver, dist,
                         "--clobber", "--repo", repo_slug()])
                rel_rc = 0
            else:
                print("[提示] gh 已安装但未登录")
        else:
            print("[提示] 未安装 gh 命令行工具")

    if rel_rc != 0:
        print("[跳过] 无可用凭据（.env 无 GITHUB_TOKEN，且 gh 未安装/未登录）")
        print("        办法一：在 .env 中配置 GITHUB_TOKEN=xxx（需 repo 权限）")
        print("        办法二：winget install GitHub.cli 然后 gh auth login")
        print("        办法三：手动创建 https://github.com/%s/releases/new" % repo_slug())
        print("        需选择标签 v%s 并上传：%s" % (ver, os.path.basename(dist)))

    # ---- 结果汇总 ----
    print("")
    print("============== 发布结果 ==============")
    if rel_rc == 0:
        print("[成功] v%s 发布完成：标签 + Release + 压缩包均已就绪" % ver)
        bump_version(ver)
        finalize_changelog(ver)
        push_version_bump(ver)
    else:
        print("[未完成] 仅完成本地构建与打标签")
        print("        Release 未创建，见上方说明")
    print("=======================================")
    return 0


def pause_close(prompt):
    """让窗口停留以便查看结果：优先等待任意键，失败则休眠 5 秒。"""
    try:
        import msvcrt
        sys.stdout.write("\n" + prompt)
        sys.stdout.flush()
        msvcrt.getch()
    except Exception:
        try:
            input(prompt)
        except Exception:
            time.sleep(5)


def countdown_close(seconds=5):
    """完成后显示说明并倒数 5 4 3 2 1，然后退出。"""
    sys.stdout.write("\n窗口将在 %d 秒后自动关闭：" % seconds)
    sys.stdout.flush()
    for i in range(seconds, 0, -1):
        sys.stdout.write(" %d" % i)
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write("\n")


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
        print("[异常] release.py 运行出错，详情如下：")
        traceback.print_exc()
        pause_close("按任意键关闭窗口...")
        sys.exit(rc)
    countdown_close()
    sys.exit(rc)
