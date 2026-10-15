#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pull.py - 从 origin/main 拉取最新代码（rebase 方式）
凭据：若 .env 中有 GITHUB_TOKEN 则用它认证（不落盘、不写进 remote URL）；
      否则回退到系统凭据管理器。
"""
import base64
import io
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))


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


def main():
    os.chdir(ROOT)
    auth, has_tok = git_auth_args()
    if has_tok:
        print("[凭据] 使用 .env 中的 GITHUB_TOKEN")
    else:
        print("[凭据] .env 中无 GITHUB_TOKEN，使用系统凭据")

    if subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        print("[错误] 当前目录不是 git 仓库")
        return 1

    print("=== 从 origin/main 拉取并变基 ===")
    rc = run(["git"] + auth + ["pull", "--rebase", "origin", "main"])
    if rc != 0:
        print("")
        print("[错误] 拉取失败。若存在冲突，请手动处理：")
        print("        查看冲突：git status")
        print("        解决后：  git add -A && git rebase --continue")
        print("        放弃：    git rebase --abort")
        return 1

    print("")
    print("=== 当前状态 ===")
    subprocess.run(["git", "--no-pager", "log", "--oneline", "-5"])
    print("")
    print("[完成] 已同步到远程最新")
    return 0


if __name__ == "__main__":
    rc = 1
    try:
        rc = main()
    except KeyboardInterrupt:
        rc = 0
    print("")
    print("窗口将在 5 秒后自动关闭...")
    time.sleep(5)
    sys.exit(rc)
