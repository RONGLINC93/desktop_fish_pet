# -*- coding: utf-8 -*-
"""
Windows 桌面小鱼宠物
====================
用《捕鱼达人》风格的鱼素材做的桌面小宠物。

功能：
  - 逐像素透明的桌面小鱼（Win32 UpdateLayeredWindow，边缘无毛边）
  - 小鱼在屏幕工作区内自由游动，随机转向 / 停留 / 猛冲，贴边反弹
  - 左键拖动可以把鱼放到任意位置；轻点一下，鱼会受惊猛窜
  - 右键菜单：更换品种、调整大小、添加/移除小鱼、退出
  - 透明像素处鼠标点击自动穿透，不挡桌面操作

依赖：Python 3.8+（自带 tkinter）+ Pillow
运行：python desktop_fish_pet.py   或双击 启动小鱼.bat
"""

import ctypes
import io
import json
import math
import os
import random
import re
import struct
import sys
import threading
import time
import wave
from ctypes import wintypes

try:  # winsound 仅 Windows 自带；非 Windows 运行时优雅降级
    import winsound
except Exception:  # pragma: no cover
    winsound = None

try:  # winreg 用于「开机自启」（写 HKCU Run 项），仅 Windows 有
    import winreg
except Exception:  # pragma: no cover
    winreg = None

import tkinter as tk
from PIL import Image, ImageChops, ImageDraw, ImageFont
from pystray import Icon as TrayIcon, Menu as TrayMenu, MenuItem as TrayItem

try:  # 商城用 HTML 渲染（pywebview），缺失时优雅降级回 tkinter 提示
    import webview
except Exception:  # pragma: no cover
    webview = None

# ---------------------------------------------------------------- Win32 准备
try:  # 高 DPI 下保证坐标 1:1
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TRANSPARENT = 0x00000020  # 鼠标穿透：整窗点击穿透到桌面，不再接收鼠标
ULW_ALPHA = 2
SPI_GETWORKAREA = 0x0030
GA_ROOT = 2
# 虚拟桌面（跨所有显示器）度量
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
SM_CMONITORS = 80

# 血条在鱼最后一次受击后多少秒自动隐藏（秒）
HP_BAR_HIDE_AFTER = 3.0
# 鱼被击中后进入狂暴模式的持续时间（秒）与速度倍率
BERSERK_DURATION = 6.0
BERSERK_MUL = 2.2
# 鱼的成长：每级所需秒数、每级缩放增量、最大缩放倍率、最高等级
GROWTH_SECONDS_PER_LEVEL = 30.0
GROWTH_STEP = 0.12
GROWTH_MAX_FACTOR = 2.0
GROWTH_MAX_LEVEL = 10
# 繁殖：达到该等级视为成年「大鱼」，可生小鱼；每条两次生育的冷却与鱼池上限
MATURE_LEVEL = 6
BREED_COOLDOWN = 120.0
MAX_FISH = 15
# 鱼数量上限：可选预设与硬上限（防止误设过大影响性能）
MAX_FISH_CHOICES = [5, 10, 15, 20, 30, 50]
MAX_FISH_LIMIT = 100
# 开机自启：写入 HKCU 的 Run 项（用户级，无需管理员权限）
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "DesktopFishPet"
# 捕鱼经济：捕获奖励 = 鱼价值 × 炮台等级 × 该倍率（原为 ×1，低等级几乎不赚钱）
REWARD_MULT = 5
# 炮台发射冷却（秒）：限制按住空格的连发速率（系统自动连发约 30 次/秒），
# 否则一次长按会瞬间起播几十个开炮音，松手后声音仍会持续好几秒
FIRE_COOLDOWN = 0.15
# 商城经济
FISH_BUY_MULT = 2         # 买鱼价格 = 鱼价值 × 此倍数（下限见 fish_buy_price）；大幅下调让买鱼轻松
FISH_SELL_RATE = 1.8      # 卖鱼返还 = 鱼价值 × 等级 × 此比例（养大才能赚钱）
CANNON_UPGRADE_BASE = 200  # 炮台升到下一级花费 = 此基数 × 当前等级
CANNON_SELL_RATE = 0.6     # 炮台降级返还 = 上一级升级花费 × 此比例
CANNON_MAX_LEVEL = 99      # 炮台等级上限（与 load_config 的 min(CANNON_MAX_LEVEL, …) 一致）
CANNON_VISUAL_CAP = 10      # 炮台贴图视觉缩放封顶等级：高于此等级不再变大，避免炮台铺满屏幕

# 鱼的基础价值（捕获奖励基数）与捕获率；商城买卖价格也基于此计算
FISH_VALUE = {
    # 常见小鱼：低倍率、高捕获率
    "tianshiyu": (2, 0.55), "cheqiyu": (2, 0.55), "jinqiangyu": (3, 0.5),
    "haima": (3, 0.45),
    # 中等鱼
    "chuitousha": (5, 0.35), "dalanjing": (6, 0.32), "shirenyu": (5, 0.38),
    "huangjinsha": (6, 0.3), "dalansha": (5, 0.35), "hujing": (7, 0.28),
    "jianchijing": (5, 0.35), "zhonghuahou": (6, 0.3),
    # 大型 / 稀有鱼：高倍率、低捕获率
    "jinlong": (20, 0.12), "leiyinlong": (20, 0.12), "jinlongyu": (18, 0.14),
    "yaoqianshu": (30, 0.1), "zhangyu": (12, 0.2), "hanbingshuimu": (15, 0.18),
    "jinshashuimu": (15, 0.18),
}

      
class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class BLENDFUNCTION(ctypes.Structure):                          
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]

               
class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", ctypes.c_ushort),
                ("biBitCount", ctypes.c_ushort), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]


user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC,
                                       ctypes.POINTER(POINT), ctypes.POINTER(SIZE),
                                       wintypes.HDC, ctypes.POINTER(POINT),
                                       wintypes.COLORREF, ctypes.POINTER(BLENDFUNCTION),
                                       wintypes.DWORD]
if not hasattr(user32, "GetWindowLongPtrW"):  # 32 位 Python 回退
    user32.GetWindowLongPtrW = user32.GetWindowLongW
    user32.SetWindowLongPtrW = user32.SetWindowLongW
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_long
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongPtrW.restype = ctypes.c_long
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
SW_HIDE = 0
SW_SHOW = 5

# 全局低层鼠标钩子（捕鱼模式用）
kernel32 = ctypes.windll.kernel32
WH_MOUSE_LL = 14
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
VK_SPACE = 0x20
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, wintypes.HANDLE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HANDLE
user32.CallNextHookEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = wintypes.LPARAM
user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
user32.UnhookWindowsHookEx.restype = ctypes.c_bool
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HANDLE
HOOKPROC = ctypes.WINFUNCTYPE(wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", POINT), ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]

# ---------------------------------------------------------------- 素材
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESOURCE_DIR = os.path.join(BASE_DIR, "resource")   # 图片/音效等素材
DATA_DIR = os.path.join(BASE_DIR, "data")           # 运行时配置与日志
HTML_DIR = os.path.join(BASE_DIR, "html")           # 设置 / 商城网页
FISH_ROOT = os.path.join(RESOURCE_DIR, "鱼")
GROUPS = ["新版鱼", "中型鱼"]
CONFIG_PATH = os.path.join(DATA_DIR, "fish_pet_config.json")
CANNON_ROOT = os.path.join(RESOURCE_DIR, "炮台")
SOUND_DIR = os.path.join(RESOURCE_DIR, "音效")


def find_cannons():
    """扫描炮台素材目录，返回按文件名排序的炮台图片路径列表。"""
    if not os.path.isdir(CANNON_ROOT):
        return []
    out = []
    for fn in sorted(os.listdir(CANNON_ROOT)):
        if fn.lower().endswith(".png"):
            out.append(os.path.join(CANNON_ROOT, fn))
    return out

NAMES = {
    "cheqiyu": "扯旗鱼", "chuitousha": "锤头鲨", "dalanjing": "大蓝鲸",
    "haima": "海马", "huangjinsha": "黄金鲨", "jinlong": "金龙",
    "jinqiangyu": "金枪鱼", "leiyinlong": "银龙", "shirenyu": "食人鱼",
    "tianshiyu": "天使鱼", "yaoqianshu": "摇钱树", "zhonghuahou": "中华鲎",
    "dalansha": "蓝鲨", "hanbingshuimu": "寒冰水母", "hujing": "虎鲸",
    "jianchijing": "尖齿鲨", "jinlongyu": "金龙鱼", "jinshashuimu": "金沙水母",
    "zhangyu": "章鱼",
}

_frame_cache = {}


def find_species():
    """扫描素材目录，返回 [(显示名, 目录)]，跳过没有帧序列的目录。"""
    result = []
    seen = {}
    for group in GROUPS:
        gd = os.path.join(FISH_ROOT, group)
        if not os.path.isdir(gd):
            continue
        for name in sorted(os.listdir(gd)):
            res = os.path.join(gd, name, "Resources")
            if not os.path.isdir(res):
                continue
            has_frames = any(re.search(r"[_-]\d{2}\.png$", f, re.I) for f in os.listdir(res))
            if not has_frames:
                continue
            label = NAMES.get(name, name)
            if label in seen:  # 两个目录里同名，加后缀区分
                label = f"{label}·{group}"
            seen[label] = True
            result.append((label, os.path.join(gd, name)))
    return result


def _premultiply(img):
    """RGBA -> 预乘 alpha 的 BGRA 字节（UpdateLayeredWindow 需要）。"""
    r, g, b, a = img.split()
    pm = Image.merge("RGBA", (ImageChops.multiply(b, a), ImageChops.multiply(g, a),
                              ImageChops.multiply(r, a), a))
    return pm.tobytes(), img.size


def species_frames(path, scale):
    """加载某品种在指定缩放下的全部帧，返回 (朝右帧列表, 朝左帧列表)。带缓存。"""
    key = (path, round(scale, 3))
    if key in _frame_cache:
        return _frame_cache[key]
    res = os.path.join(path, "Resources")
    pairs = []
    for f in os.listdir(res):
        m = re.search(r"[_-](\d{2})\.png$", f, re.I)
        if m:
            pairs.append((int(m.group(1)), f))
    pairs.sort()
    right, left = [], []
    for _, fn in pairs:
        im = Image.open(os.path.join(res, fn)).convert("RGBA")
        if abs(scale - 1.0) > 1e-3:
            im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))),
                           Image.LANCZOS)
        right.append(_premultiply(im))
        left.append(_premultiply(im.transpose(Image.FLIP_LEFT_RIGHT)))
    _frame_cache[key] = (right, left)
    return right, left


def make_tray_icon():
    """用一条鱼的帧做托盘图标，缩放到 64x64 并居中到透明方块。"""
    path = os.path.join(FISH_ROOT, "新版鱼", "jinlong", "Resources", "jl_01.png")
    im = Image.open(path).convert("RGBA").resize((64, 47), Image.LANCZOS)
    canvas = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    canvas.paste(im, (0, (64 - im.height) // 2), im)
    return canvas


def load_cjk_font(size=14):
    """加载支持中文的 TrueType 字体（优先微软雅黑），找不到则回退默认字体。

    PIL 默认位图字体不含中文字形，直接用会把中文渲染成「方形带 X」的豆腐块，
    所以信息卡 / HUD / 浮字统一走这里取一个真正带中文的字体。
    """
    windir = os.environ.get("WINDIR", r"C:\Windows")
    candidates = [
        os.path.join(windir, "Fonts", "msyh.ttc"),      # 微软雅黑
        os.path.join(windir, "Fonts", "msyh.ttf"),
        os.path.join(windir, "Fonts", "simhei.ttf"),    # 黑体
        os.path.join(windir, "Fonts", "simsun.ttc"),    # 宋体
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
    ]
    for p in candidates:
        try:
            if os.path.isfile(p):
                return ImageFont.truetype(p, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def compute_roam_area(workarea):
    """鱼可游走的边界：多显示器时取整个虚拟桌面（跨屏），单显示器时沿用工作区。

    单显示器返回原 workarea，行为与以前完全一致；多显示器才扩展到虚拟桌面，
    让鱼可以游到别的屏幕上。任务栏区域鱼照常会被任务栏盖住，属正常。
    """
    try:
        if user32.GetSystemMetrics(SM_CMONITORS) <= 1:
            return workarea
        L = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        T = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        W = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        H = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        if W > 0 and H > 0:
            return (L, T, L + W, T + H)
    except Exception:
        pass
    return workarea


class MONITORINFOEX(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", ctypes.c_ulong),
                ("szDevice", ctypes.c_wchar * 32)]


# 枚举显示器用的回调类型与结果容器
_MONITOR_ENUMPROC = ctypes.WINFUNCTYPE(
    ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.POINTER(RECT), ctypes.c_void_p)
_MONITOR_RESULT = []


def _monitor_enum_proc(hmon, hdc, lprect, lparam):
    info = MONITORINFOEX()
    info.cbSize = ctypes.sizeof(MONITORINFOEX)
    user32.GetMonitorInfoW(hmon, ctypes.byref(info))
    _MONITOR_RESULT.append(info)
    return True


def get_monitors():
    """枚举所有显示器，返回已按「主屏优先」排序的列表。

    每项：{"index": int, "primary": bool, "name": str, "label": str,
           "res": "WxH", "rect": (L,T,R,B) 整屏, "work": (L,T,R,B) 工作区}
    坐标均为虚拟桌面坐标（多屏下可能为负），与鱼游走坐标同一套。
    index 从 0 起、主屏为 0，供 `App.screen` 引用。枚举失败则返回空列表。
    """
    out = []
    try:
        _MONITOR_RESULT.clear()
        user32.EnumDisplayMonitors(0, None, _MONITOR_ENUMPROC(_monitor_enum_proc), 0)
        infos = list(_MONITOR_RESULT)
        infos.sort(key=lambda i: 0 if (i.dwFlags & 1) else 1)  # 主屏排最前
        for idx, info in enumerate(infos):
            m = info.rcMonitor
            w = info.rcWork
            primary = bool(info.dwFlags & 1)
            res = "%dx%d" % (max(0, w.right - w.left), max(0, w.bottom - w.top))
            out.append({
                "index": idx,
                "primary": primary,
                "name": (info.szDevice or "").strip() or ("屏幕 %d" % (idx + 1)),
                "label": "主屏幕" if primary else ("屏幕 %d" % (idx + 1)),
                "res": res,
                "rect": (m.left, m.top, m.right, m.bottom),
                "work": (w.left, w.top, w.right, w.bottom),
            })
    except Exception:
        pass
    return out


def monitor_work_rect(index):
    """返回指定 index 显示器的工作区矩形（虚拟桌面坐标）；无效索引返回 None。"""
    if index is None or index < 0:
        return None
    for m in get_monitors():
        if m["index"] == index:
            return m["work"]
    return None


try:  # 显示器枚举（屏幕选择功能用）
    user32.EnumDisplayMonitors.argtypes = [ctypes.c_void_p, ctypes.POINTER(RECT),
                                           _MONITOR_ENUMPROC, ctypes.c_void_p]
    user32.EnumDisplayMonitors.restype = ctypes.c_bool
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.GetMonitorInfoW.restype = ctypes.c_bool
except Exception:
    pass


# ---------------------------------------------------------------- 音效
class SoundManager:
    """轻量音效管理器：内置合成音（无需素材文件），同时支持用 音效/ 目录下的
    WAV 覆盖（shoot.wav / hit.wav / catch.wav / poke.wav）。基于 Windows 自带
    的 winsound 播放，非 Windows 平台自动静音。"""

    # 内置合成参数：(时长秒, 起始频率, 结束频率, 音量, 波形)
    # 一段音效可由多段拼接而成（如“捕获”用两声上扬音）。
    _SYNTH = {
        "shoot": [(0.13, 900, 180, 0.55, "saw")],
        "hit":   [(0.07, 320, 110, 0.55, "square")],
        "catch": [(0.09, 520, 740, 0.55, "sine"), (0.12, 740, 1040, 0.55, "sine")],
        "poke":  [(0.10, 600, 720, 0.35, "sine")],
        "levelup": [(0.08, 520, 780, 0.5, "sine"), (0.10, 780, 1040, 0.5, "sine")],
        "birth": [(0.10, 660, 880, 0.5, "sine"), (0.12, 880, 1180, 0.45, "sine")],
    }
    _SAMPLE_RATE = 44100

    def __init__(self):
        self.enabled = True
        self._cache = {}  # kind -> 已合成/加载的 WAV 字节

    @staticmethod
    def _synth_segment(seg, sr=_SAMPLE_RATE):
        dur, f0, f1, vol, wave_kind = seg
        n = max(1, int(sr * dur))
        out = bytearray()
        for i in range(n):
            t = i / sr
            frac = i / n
            freq = f0 + (f1 - f0) * frac
            # 快速起音 + 衰减包络，听感更像“打击”而非持续音
            env = min(1.0, frac / 0.04) * (1.0 - frac)
            phase = 2 * math.pi * freq * t
            if wave_kind == "square":
                s = 1.0 if math.sin(phase) >= 0 else -1.0
            elif wave_kind == "saw":
                s = 2.0 * (freq * t - math.floor(freq * t + 0.5))
            else:  # sine
                s = math.sin(phase)
            sample = int(max(-1.0, min(1.0, env * vol * s)) * 32767)
            out += struct.pack("<h", sample)
        return bytes(out)

    def _render(self, kind):
        """生成某音效的完整 WAV 字节（单声道 16bit PCM）。优先用自定义文件。"""
        if kind in self._cache:
            return self._cache[kind]
        wav_bytes = None
        # 若音效目录中存在同名 WAV，则直接用它覆盖内置合成音
        custom = os.path.join(SOUND_DIR, f"{kind}.wav")
        if os.path.isfile(custom):
            try:
                with open(custom, "rb") as fp:
                    wav_bytes = fp.read()
            except Exception:
                wav_bytes = None
        if wav_bytes is None:
            segs = self._SYNTH.get(kind, [(0.1, 440, 440, 0.4, "sine")])
            pcm = b"".join(self._synth_segment(s) for s in segs)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(self._SAMPLE_RATE)
                w.writeframes(pcm)
            wav_bytes = buf.getvalue()
        self._cache[kind] = wav_bytes
        return wav_bytes

    def play(self, kind):
        if not self.enabled or winsound is None:
            return
        try:
            data = self._render(kind)
        except Exception:
            return
        # 在后台线程播放，避免阻塞 tkinter 主循环；SND_ASYNC 保证不卡 UI
        threading.Thread(
            target=self._play_async, args=(data,), daemon=True
        ).start()

    @staticmethod
    def _play_async(data):
        if winsound is None:
            return
        try:
            # 注意：SND_MEMORY 不能和 SND_ASYNC 一起用（会抛 RuntimeError），
            # 所以放到后台线程里“同步”播放，既不卡 UI 又能正常出声。
            winsound.PlaySound(
                data, winsound.SND_MEMORY | winsound.SND_NODEFAULT
            )
        except Exception:
            pass


# ---------------------------------------------------------------- 信息卡绘制
INFO_CARD_W = 212
INFO_CARD_H = 110
INFO_CARD_LINGER = 2.0  # 鼠标离开鱼后，信息卡继续跟随鱼显示的秒数（鱼在游动，便于看清）


def draw_fish_info_card(img, draw, fish, x, y, font):
    """在 (x, y) 处画一张玻璃卡片样式的鱼信息卡：名字/等级、成长、血量、繁衍倒计时、价值、速度。"""
    cw, ch = INFO_CARD_W, INFO_CARD_H
    # 投影
    try:
        draw.rounded_rectangle([x + 3, y + 4, x + cw + 3, y + ch + 4],
                               radius=13, fill=(0, 0, 0, 90))
    except Exception:
        pass
    # 圆角渐变底（半透明）
    try:
        mask = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, cw - 1, ch - 1],
                                               radius=13, fill=255)
        grad = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        gd = ImageDraw.Draw(grad)
        top = (52, 68, 112, 188)
        bot = (18, 24, 44, 188)
        for i in range(ch):
            t = i / max(1, ch - 1)
            col = tuple(int(top[k] + (bot[k] - top[k]) * t) for k in range(4))
            gd.line([(0, i), (cw, i)], fill=col)
        sub = img.crop((x, y, x + cw, y + ch))
        sub.paste(grad, (0, 0), mask)
        img.paste(sub, (x, y))
    except Exception:
        draw.rectangle([x, y, x + cw, y + ch], fill=(20, 28, 48, 235))
    # 柔和描边
    draw.rounded_rectangle([x, y, x + cw, y + ch], radius=13,
                           outline=(130, 190, 245, 210), width=2)
    # 左侧高亮条：狂暴时变红
    berserk = getattr(fish, "berserk", False)
    accent = (255, 95, 85, 220) if berserk else (110, 205, 255, 210)
    draw.rounded_rectangle([x + 7, y + 12, x + 11, y + ch - 12], radius=2, fill=accent)

    if not font:
        return cw, ch

    def _shadow_text(px, py, text, fill):
        draw.text((px + 1, py + 1), text, fill=(0, 0, 0, 170), font=font)
        draw.text((px, py), text, fill=fill, font=font)

    def _tw(text):
        bb = draw.textbbox((0, 0), text, font=font)
        return bb[2] - bb[0]

    # 第一行：名字（白）+ 等级（青）+ 成年（金）/ 狂暴（红）
    tx = x + 18
    name = getattr(fish, "name", "")
    _shadow_text(tx, y + 8, name, (240, 245, 255))
    tx += _tw(name) + 7
    _shadow_text(tx, y + 8, "Lv%d" % fish.level, (130, 220, 255))
    tx += _tw("Lv%d" % fish.level) + 6
    if getattr(fish, "is_mature", None) and fish.is_mature():
        _shadow_text(tx, y + 8, "成年", (255, 205, 90))
        tx += _tw("成年") + 6
    if berserk:
        _shadow_text(tx, y + 8, "狂暴", (255, 110, 100))

    # 圆角进度条
    bx, bw, bh = x + 52, cw - 52 - 16, 8

    def _bar(by, ratio, col):
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=bh // 2,
                               fill=(38, 48, 74, 220))
        fw = int(bw * max(0.0, min(1.0, ratio)))
        if fw > 2:
            draw.rounded_rectangle([bx, by, bx + fw, by + bh], radius=bh // 2, fill=col)
            # 顶部高光：不透明浅色（半透明白会被 ImageDraw 直接替换像素，导致分层窗口里变透明）
            if fw > 6 and bh >= 6:
                hl = tuple(int(c + (255 - c) * 0.38) for c in col[:3])
                draw.rounded_rectangle([bx + 2, by + 2, bx + fw - 2, by + bh // 2],
                                       radius=max(1, bh // 2 - 2), fill=hl)

    def _right(text, by, fill):
        _shadow_text(x + cw - 8 - _tw(text), by, text, fill)

    def _center(text, by, fill):
        _shadow_text(bx + bw / 2 - _tw(text) / 2, by, text, fill)

    # 成长（带百分比，文字居中在进度条上）
    growth = getattr(fish, "growth", 0.0)
    _shadow_text(x + 18, y + 30, "成长", (185, 215, 255))
    _bar(y + 31, growth, (115, 220, 145))
    _center("%d%%" % int(growth * 100), y + 30, (200, 255, 210))

    # HP（带数值，文字居中在进度条上）
    hp = getattr(fish, "hp", 1)
    maxhp = getattr(fish, "max_hp", 1)
    hpr = hp / max(1, maxhp)
    _shadow_text(x + 18, y + 50, "HP", (255, 160, 150))
    _bar(y + 51, hpr, (235, 85, 75))
    _center("%d/%d" % (int(hp), int(maxhp)), y + 50, (255, 200, 190))

    # 繁衍倒计时（仅成年鱼有意义，文字居中在进度条上）
    mature = getattr(fish, "is_mature", None) and fish.is_mature()
    by_breed = y + 70
    if mature:
        bt = getattr(fish, "breed_timer", BREED_COOLDOWN)
        ratio = max(0.0, min(1.0, 1.0 - bt / BREED_COOLDOWN))
        left = max(0, int(math.ceil(bt)))
        _shadow_text(x + 18, by_breed, "繁衍", (255, 205, 120))
        _bar(by_breed + 1, ratio, (255, 205, 120))
        _center("%ds" % left, by_breed, (255, 225, 160))
    else:
        _shadow_text(x + 18, by_breed, "繁衍", (150, 160, 180))
        _shadow_text(x + 52, by_breed, "Lv%d成年可繁殖" % MATURE_LEVEL, (150, 160, 180))

    # 底部：价值（左）+ 速度（右）
    try:
        value = int(fish.app._fish_info(fish)[0])
    except Exception:
        value = 0
    speed = int(getattr(fish, "base_speed", 0))
    _shadow_text(x + 18, y + 90, "价值 %d" % value, (255, 220, 120))
    _right("速度 %d" % speed, y + 90, (160, 220, 255))

    return cw, ch


# ---------------------------------------------------------------- 小鱼窗口
class Fish:
    TICK_MS = 33

    def __init__(self, app, species, scale, x, y, level=1, growth=0.0):
        self.app = app
        self.species = species
        self.name = species[0]  # find_species 返回的 (显示名, 目录)
        self.base_scale = scale
        self.level = max(1, int(level))
        self.growth = max(0.0, min(1.0, float(growth)))
        self.frame_ms = 90
        self._apply_scale()
        w, h = self.w, self.h
        self.x, self.y = float(x), float(y)
        self.vx = self.base_speed
        self.vy = 0.0
        self.frame = 0
        self.anim_t = 0.0
        self.timer = random.uniform(2.0, 5.0)
        self.mode = "swim"
        self.dart_t = 0.0
        self.bob = random.uniform(0, 6.28)
        self.facing_right = True
        self.drag = None
        self.max_hp = 1
        self.hp = 1
        self.max_hp_set = False
        self.berserk = False
        self.berserk_t = 0.0
        self.breed_timer = BREED_COOLDOWN  # 成年后的生育冷却，加载后先等一轮

        self.win = tk.Toplevel(app.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="black")
        self.win.geometry(f"+{int(x)}+{int(y)}")
        self.win.update_idletasks()

        self.hwnd = user32.GetAncestor(self.win.winfo_id(), GA_ROOT)
        ex = user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
        ex |= WS_EX_LAYERED | WS_EX_TOOLWINDOW
        if getattr(app, "mouse_penetration", False):
            ex |= WS_EX_TRANSPARENT
        user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, ex)

        self.hdc_screen = user32.GetDC(0)
        self.hdc_mem = gdi32.CreateCompatibleDC(self.hdc_screen)
        self.hbm = None
        self.old_hbm = None
        self.bits = None
        self.dib_size = (0, 0)
        self._make_dib(w, h)

        self._bind()
        self.render()

    # ---------- 成长 / 缩放 ----------
    def _effective_scale(self):
        """由基础尺寸与等级推导实际渲染缩放（封顶 GROWTH_MAX_FACTOR）。"""
        return min(self.base_scale * (1.0 + (self.level - 1) * GROWTH_STEP),
                   self.base_scale * GROWTH_MAX_FACTOR)

    def _apply_scale(self):
        """按当前等级重算实际缩放并重新加载帧序列 / 尺寸 / 基础速度。"""
        self.scale = self._effective_scale()
        self.right, self.left = species_frames(self.species[1], self.scale)
        w, h = self.right[0][1]
        self.w, self.h = w, h
        self.base_speed = 60.0 * (0.5 + self.scale)
        self.frame = 0
        self.anim_t = 0.0

    def is_mature(self):
        """达到 MATURE_LEVEL 视为成年「大鱼」，可以生小鱼。"""
        return self.level >= MATURE_LEVEL

    # ---------- Win32 图层 ----------
    def _make_dib(self, w, h):
        if self.hbm:
            gdi32.SelectObject(self.hdc_mem, self.old_hbm)
            gdi32.DeleteObject(self.hbm)
        bi = BITMAPINFO()
        bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.bmiHeader.biWidth = w
        bi.bmiHeader.biHeight = -h  # 负值 = 自上而下
        bi.bmiHeader.biPlanes = 1
        bi.bmiHeader.biBitCount = 32
        bi.bmiHeader.biCompression = 0  # BI_RGB
        bits = ctypes.c_void_p()
        self.hbm = gdi32.CreateDIBSection(self.hdc_screen, ctypes.byref(bi), 0,
                                          ctypes.byref(bits), None, 0)
        self.bits = bits
        self.old_hbm = gdi32.SelectObject(self.hdc_mem, self.hbm)
        self.dib_size = (w, h)

    def render(self):
        frames = self.right if self.facing_right else self.left
        data, (w, h) = frames[self.frame]
        if (w, h) != self.dib_size:
            self._make_dib(w, h)
            self.w, self.h = w, h
        ctypes.memmove(self.bits, data, w * h * 4)
        blend = BLENDFUNCTION(0, 0, 255, 1)  # AC_SRC_OVER, 255, AC_SRC_ALPHA
        dst = POINT(int(self.x), int(self.y))
        sz = SIZE(w, h)
        src = POINT(0, 0)
        user32.UpdateLayeredWindow(self.hwnd, self.hdc_screen, ctypes.byref(dst),
                                   ctypes.byref(sz), self.hdc_mem, ctypes.byref(src),
                                   0, ctypes.byref(blend), ULW_ALPHA)

    def destroy(self):
        try:
            if self.hbm:
                gdi32.SelectObject(self.hdc_mem, self.old_hbm)
                gdi32.DeleteObject(self.hbm)
            gdi32.DeleteDC(self.hdc_mem)
            user32.ReleaseDC(0, self.hdc_screen)
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass

    # ---------- 行为 ----------
    def poke(self):
        """被点了一下：受惊猛窜。"""
        ang = random.uniform(0, 2 * math.pi)
        sp = self.base_speed * 4
        self.vx = math.cos(ang) * sp
        self.vy = math.sin(ang) * sp * 0.5
        self.dart_t = 0.8
        self.app.sounds.play("poke")

    def tick(self, dt):
        if self.mode == "drag":
            return
        wa = self.app.roam  # 跨屏游走边界
        L, T, R, B = wa

        # 狂暴计时：到点自动解除
        if self.berserk:
            self.berserk_t -= dt
            if self.berserk_t <= 0:
                self.berserk = False
        mul = BERSERK_MUL if self.berserk else 1.0

        # 成长：随时间积累经验，满级后停止；升级时放大体型并播放音效
        if self.level < GROWTH_MAX_LEVEL:
            self.growth += dt / GROWTH_SECONDS_PER_LEVEL
            if self.growth >= 1.0:
                self.growth -= 1.0
                self.level += 1
                self._apply_scale()
                self.app.sounds.play("levelup")
        else:
            self.growth = 1.0

        # 繁殖：成年鱼每隔一段时间在附近随机繁殖若干条小鱼（受鱼池上限约束，不消耗金币）
        if self.is_mature():
            self.breed_timer -= dt
            if self.breed_timer <= 0 and len(self.app.fishes) < self.app.max_fish:
                if self.app.breed_fish(self) is not None:
                    self.breed_timer = BREED_COOLDOWN

        anim_speed = 1.0
        if self.dart_t > 0:
            self.dart_t -= dt
            anim_speed = 3.0
        else:
            self.timer -= dt
            if self.timer <= 0:
                r = random.random()
                if self.berserk and r > 0.15:
                    # 狂暴时大幅提高猛冲概率，几乎不停歇地乱窜
                    r = 0.30 + random.random() * 0.04
                if r < 0.25:
                    self.mode = "idle"
                    self.timer = random.uniform(0.8, 2.0)
                elif r < 0.35:
                    ang = random.uniform(0, 2 * math.pi)
                    sp = self.base_speed * 3.5 * mul
                    self.vx = math.cos(ang) * sp
                    self.vy = math.sin(ang) * sp * 0.5
                    self.dart_t = random.uniform(0.5, 0.9)
                    self.mode = "swim"
                    self.timer = random.uniform(2.5, 6.0)
                else:
                    self.mode = "swim"
                    ang = random.uniform(0, 2 * math.pi)
                    sp = self.base_speed * random.uniform(0.6, 1.4) * mul
                    self.vx = math.cos(ang) * sp
                    self.vy = math.sin(ang) * sp * 0.4
                    self.timer = random.uniform(2.5, 6.0)

        if self.berserk:
            anim_speed = max(anim_speed, 2.0)

        self.bob += dt * 3.0
        if self.mode == "swim":
            self.x += self.vx * dt * mul
            self.y += self.vy * dt * mul + math.sin(self.bob) * 12.0 * dt

        # 贴边反弹
        if self.x < L:
            self.x, self.vx = float(L), abs(self.vx)
        elif self.x + self.w > R:
            self.x, self.vx = R - self.w, -abs(self.vx)
        if self.y < T:
            self.y, self.vy = float(T), abs(self.vy)
        elif self.y + self.h > B:
            self.y, self.vy = B - self.h, -abs(self.vy)

        if abs(self.vx) > 2.0:
            self.facing_right = self.vx > 0

        self.anim_t += dt * 1000.0 * anim_speed
        n = len(self.right)
        while self.anim_t >= self.frame_ms:
            self.anim_t -= self.frame_ms
            self.frame = (self.frame + 1) % n
        self.render()

    # ---------- 鼠标 ----------
    def _bind(self):
        self.win.bind("<Button-1>", self._press)
        self.win.bind("<B1-Motion>", self._motion)
        self.win.bind("<ButtonRelease-1>", self._release)
        self.win.bind("<Button-3>", self._menu)
        self.win.bind("<Enter>", self._enter)
        self.win.bind("<Leave>", self._leave)

    def _enter(self, e):
        self.app.show_fish_info(self)

    def _leave(self, e):
        self.app.hide_fish_info(self)

    def _press(self, e):
        if self.app.fishing:  # 捕鱼模式下不拖动，交给鱼叉
            return
        self.drag = (e.x_root, e.y_root, self.x, self.y)

    def _motion(self, e):
        if not self.drag:
            return
        self.mode = "drag"
        self.x = self.drag[2] + (e.x_root - self.drag[0])
        self.y = self.drag[3] + (e.y_root - self.drag[1])
        self.render()

    def _release(self, e):
        if self.app.fishing or not self.drag:
            return
        moved = abs(e.x_root - self.drag[0]) + abs(e.y_root - self.drag[1])
        self.drag = None
        self.mode = "swim"
        if moved < 6:
            self.poke()
        self.app.save_config()

    def _menu(self, e):
        self.app.show_menu(self, e)


# ---------------------------------------------------------------- 鱼信息浮层
class FishInfoOverlay:
    """鼠标悬停在某条鱼上时，跟随它显示一张信息卡（名字/等级/成长/血条）。
    窗口设为 disabled，不接收鼠标，避免抢走鱼的悬停事件。"""

    def __init__(self, app):
        self.app = app
        self.cw, self.ch = INFO_CARD_W + 8, INFO_CARD_H + 8
        self.win = tk.Toplevel(app.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-disabled", True)  # 不接收鼠标，避免挡住鱼的悬停
        self.win.configure(bg="black")
        self.win.geometry("+0+0")
        self.win.update_idletasks()

        self.hwnd = user32.GetAncestor(self.win.winfo_id(), GA_ROOT)
        ex = user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
        ex |= WS_EX_LAYERED | WS_EX_TOOLWINDOW
        if getattr(app, "mouse_penetration", False):
            ex |= WS_EX_TRANSPARENT
        user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, ex)

        self.hdc_screen = user32.GetDC(0)
        self.hdc_mem = gdi32.CreateCompatibleDC(self.hdc_screen)
        self.bits = None
        self.dib_size = (0, 0)
        self._make_dib(self.cw, self.ch)
        self.img = Image.new("RGBA", (self.cw, self.ch), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.img)
        try:
            self.font = load_cjk_font(14)
        except Exception:
            self.font = None
        self.fish = None
        self.visible = False
        self._hide_at = None  # 延迟隐藏的到期时间（monotonic）；None 表示无待隐藏
        self._hide()

    def _make_dib(self, w, h):
        if getattr(self, "hbm", None):
            gdi32.SelectObject(self.hdc_mem, self.old_hbm)
            gdi32.DeleteObject(self.hbm)
        bi = BITMAPINFO()
        bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.bmiHeader.biWidth = w
        bi.bmiHeader.biHeight = -h
        bi.bmiHeader.biPlanes = 1
        bi.bmiHeader.biBitCount = 32
        bi.bmiHeader.biCompression = 0
        bits = ctypes.c_void_p()
        self.hbm = gdi32.CreateDIBSection(self.hdc_screen, ctypes.byref(bi), 0,
                                          ctypes.byref(bits), None, 0)
        self.bits = bits
        self.old_hbm = gdi32.SelectObject(self.hdc_mem, self.hbm)
        self.dib_size = (w, h)

    def show(self, fish):
        # 捕鱼模式下由叠加层负责画信息卡，这里不重复显示
        if self.app.fishing:
            return
        self.fish = fish
        self.visible = True
        self._hide_at = None  # 取消任何待执行的延迟隐藏

    def hide(self, fish=None, immediate=False):
        if fish is not None and self.fish is not fish:
            return
        if immediate:
            self._do_hide()
            return
        # 延迟隐藏：鱼在游动，鼠标一离开就消失不方便看，故保留一会儿继续跟随鱼
        self._hide_at = time.monotonic() + INFO_CARD_LINGER

    def _do_hide(self):
        self.fish = None
        self.visible = False
        self._hide_at = None
        self._hide()

    def _hide(self):
        # 移出屏幕并清空内容
        self.img.paste((0, 0, 0, 0), [0, 0, self.cw, self.ch])
        r, g, b, a = self.img.split()
        bgra = Image.merge("RGBA", (b, g, r, a)).tobytes()
        ctypes.memmove(self.bits, bgra, self.cw * self.ch * 4)
        blend = BLENDFUNCTION(0, 0, 255, 1)
        dst = POINT(-9999, -9999)
        sz = SIZE(self.cw, self.ch)
        src = POINT(0, 0)
        user32.UpdateLayeredWindow(self.hwnd, self.hdc_screen, ctypes.byref(dst),
                                   ctypes.byref(sz), self.hdc_mem, ctypes.byref(src),
                                   0, ctypes.byref(blend), ULW_ALPHA)

    def update(self):
        """每帧刷新：跟随鱼的当前位置重绘信息卡。"""
        if not self.visible or self.fish is None:
            return
        # 延迟隐藏到期：真正收起信息卡
        if self._hide_at is not None and time.monotonic() >= self._hide_at:
            self._do_hide()
            return
        f = self.fish
        L, T, R, B = self.app.roam  # 信息卡跟随鱼跨屏，按虚拟桌面收拢
        # 默认放在鱼上方；若贴顶则放到下方
        cx = f.x + f.w / 2 - self.cw / 2
        cy = f.y - self.ch - 6
        if cy < T:
            cy = f.y + f.h + 6
        cx = max(L, min(cx, R - self.cw))
        cy = max(T, min(cy, B - self.ch))

        self.img.paste((0, 0, 0, 0), [0, 0, self.cw, self.ch])
        draw_fish_info_card(self.img, self.draw, f, 3, 3, self.font)
        r, g, b, a = self.img.split()
        bgra = Image.merge("RGBA", (b, g, r, a)).tobytes()
        ctypes.memmove(self.bits, bgra, self.cw * self.ch * 4)
        blend = BLENDFUNCTION(0, 0, 255, 1)
        dst = POINT(int(cx), int(cy))
        sz = SIZE(self.cw, self.ch)
        src = POINT(0, 0)
        user32.UpdateLayeredWindow(self.hwnd, self.hdc_screen, ctypes.byref(dst),
                                   ctypes.byref(sz), self.hdc_mem, ctypes.byref(src),
                                   0, ctypes.byref(blend), ULW_ALPHA)

    def destroy(self):
        try:
            if getattr(self, "hbm", None):
                gdi32.SelectObject(self.hdc_mem, self.old_hbm)
                gdi32.DeleteObject(self.hbm)
            gdi32.DeleteDC(self.hdc_mem)
            user32.ReleaseDC(0, self.hdc_screen)
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass


# ---------------------------------------------------------------- 浮动文字浮层
class FloaterOverlay:
    """普通模式下渲染浮动文字（如「繁殖了N条小鱼!」）：一张覆盖虚拟桌面的
    透明叠加窗口，逐帧把 app.floaters 画上去，到期自动清除；无内容时不重绘。
    窗口始终为鼠标穿透，仅作装饰，不会挡住小鱼交互。"""

    def __init__(self, app):
        self.app = app
        L = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        T = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        W = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        H = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        if not (W > 0 and H > 0):  # 取不到虚拟桌面度量时退回主屏工作区
            L, T, R, B = app.workarea
            W, H = R - L, B - T
        self.L, self.T, self.W, self.H = L, T, W, H

        self.win = tk.Toplevel(app.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-disabled", True)  # 不接收鼠标，避免挡住鱼的交互
        self.win.configure(bg="black")
        self.win.geometry("%dx%d+%d+%d" % (W, H, L, T))
        self.win.update_idletasks()

        self.hwnd = user32.GetAncestor(self.win.winfo_id(), GA_ROOT)
        ex = user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
        ex |= WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TRANSPARENT  # 整窗鼠标穿透
        user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, ex)

        self.hdc_screen = user32.GetDC(0)
        self.hdc_mem = gdi32.CreateCompatibleDC(self.hdc_screen)
        self.hbm = None
        self.old_hbm = None
        self.bits = None
        self._make_dib(W, H)
        self.img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.img)
        try:
            self.font = load_cjk_font(20)
        except Exception:
            self.font = None
        self._active = False  # 当前是否已绘制内容（用于按需清屏）
        self._blank()

    def _make_dib(self, w, h):
        if getattr(self, "hbm", None):
            gdi32.SelectObject(self.hdc_mem, self.old_hbm)
            gdi32.DeleteObject(self.hbm)
        bi = BITMAPINFO()
        bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.bmiHeader.biWidth = w
        bi.bmiHeader.biHeight = -h
        bi.bmiHeader.biPlanes = 1
        bi.bmiHeader.biBitCount = 32
        bi.bmiHeader.biCompression = 0
        bits = ctypes.c_void_p()
        self.hbm = gdi32.CreateDIBSection(self.hdc_screen, ctypes.byref(bi), 0,
                                          ctypes.byref(bits), None, 0)
        self.bits = bits
        self.old_hbm = gdi32.SelectObject(self.hdc_mem, self.hbm)
        self.dib_size = (w, h)

    def _push(self):
        r, g, b, a = self.img.split()
        bgra = Image.merge("RGBA", (b, g, r, a)).tobytes()
        ctypes.memmove(self.bits, bgra, self.W * self.H * 4)
        blend = BLENDFUNCTION(0, 0, 255, 1)
        dst = POINT(int(self.L), int(self.T))
        sz = SIZE(self.W, self.H)
        src = POINT(0, 0)
        user32.UpdateLayeredWindow(self.hwnd, self.hdc_screen, ctypes.byref(dst),
                                   ctypes.byref(sz), self.hdc_mem, ctypes.byref(src),
                                   0, ctypes.byref(blend), ULW_ALPHA)

    def _blank(self):
        self.img.paste((0, 0, 0, 0), [0, 0, self.W, self.H])
        self._push()
        self._active = False

    def update(self, dt):
        """推进 app.floaters 的计时并重绘；无内容时保持空白、不重绘。"""
        fls = self.app.floaters
        for fl in list(fls):
            fl["t"] += dt
            fl["y"] -= fl["vy"] * dt
            if fl["t"] >= fl["life"]:
                fls.remove(fl)
        if fls:
            self.img.paste((0, 0, 0, 0), [0, 0, self.W, self.H])
            for fl in fls:
                col = fl.get("color", (255, 205, 120))
                text = fl["text"]
                lx = fl["x"] - self.L
                ly = fl["y"] - self.T
                if self.font:
                    tw = self.draw.textlength(text, font=self.font)
                    self.draw.text((lx - tw / 2, ly), text, fill=col, font=self.font,
                                   stroke_width=3, stroke_fill=(0, 0, 0))
                else:
                    self.draw.text((lx - 14, ly), text, fill=col)
            self._push()
            self._active = True
        elif self._active:
            self._blank()

    def destroy(self):
        try:
            if getattr(self, "hbm", None):
                gdi32.SelectObject(self.hdc_mem, self.old_hbm)
                gdi32.DeleteObject(self.hbm)
            gdi32.DeleteDC(self.hdc_mem)
            user32.ReleaseDC(0, self.hdc_screen)
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass


# ---------------------------------------------------------------- 捕鱼叠加层
class FishingOverlay:
    """捕鱼模式：全屏透明叠加层 + 全局鼠标钩子，画出捕鱼枪并发射鱼叉。"""

    def __init__(self, app):
        self.app = app
        L, T, R, B = app.workarea
        self.L, self.T, self.W, self.H = L, T, R - L, B - T
        self.mx, self.my = self.W // 2, self.H // 2  # 鼠标（叠加层本地坐标）
        self.pending_fires = []
        self._last_fire_at = None  # 上次成功发射的时刻（monotonic）；None 表示尚未发射
        self.bullets = []
        self.effects = []
        self.floaters = []  # 掉血/捕获浮动文字
        self._hover_linger_fish = None  # 瞄具离开鱼后，继续跟随显示的鱼
        self._hover_linger_at = None    # 该跟随的到期时间（monotonic）；None=未挂
        self.gun_len = 52
        self.cannon_tilt_max = 32.0                 # 炮台最大倾斜角（度）
        self.cannons = find_cannons()
        self.cannon_index = getattr(app, "cannon_index", 0)
        self.cannon_img = None
        self.cannon_src = None        # 原始贴图（按等级再缩放）
        self.cannon_base_w = 150      # Lv1 时的炮台宽度
        self.cannon_barrel_len = 0
        self._cannon_level_cache = {}  # 等级 -> 缩放后的贴图
        self._cannon_cache = {}                      # (索引, 等级, 角度) -> 旋转后的贴图
        self.cannon_rect = None                       # 炮台外接矩形（在 _draw_cannon 中更新）
        self._load_cannon()
        self.bullet_speed = 1500.0
        self._recompute_layout()   # 炮台/枪口/HUD 锚点依赖屏幕宽高，切换屏幕时重算
        try:
            self.font = load_cjk_font(14)
        except Exception:
            self.font = None
        try:
            self.hud_font = load_cjk_font(16)  # HUD 用稍大字号
        except Exception:
            self.hud_font = None
        try:
            self.big_font = load_cjk_font(22)
        except Exception:
            self.big_font = self.font

        self.win = tk.Toplevel(app.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="black")
        self.win.geometry(f"+{L}+{T}")
        self.win.update_idletasks()

        self.hwnd = user32.GetAncestor(self.win.winfo_id(), GA_ROOT)
        ex = user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED | WS_EX_TOOLWINDOW)

        self.hdc_screen = user32.GetDC(0)
        self.hdc_mem = gdi32.CreateCompatibleDC(self.hdc_screen)
        self.hbm = None
        self.old_hbm = None
        self.bits = None
        self.dib_size = (0, 0)
        self._make_dib(self.W, self.H)

        self.img = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.img)

        self._hook = None
        self._kb_hook = None
        self._install_hook()
        self.win.bind("<Button-3>", self._cannon_menu)
        self._render()
        # 炮台跟随鼠标所在屏幕：进入捕鱼模式时先按当前鼠标位置切到对应显示器
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        self._cur_x, self._cur_y = pt.x, pt.y
        self._mon_index = None
        idx = self._monitor_index_at(pt.x, pt.y)
        if idx is not None:
            self._set_monitor(idx)

    # ---------- 屏幕跟随 ----------
    def _monitor_index_at(self, x, y):
        """返回包含坐标 (x,y) 的显示器索引；落在间隙/外部时回退主屏。"""
        mons = get_monitors()
        if not mons:
            return None
        for m in mons:
            rl, rt, rr, rb = m["rect"]
            if rl <= x <= rr and rt <= y <= rb:
                return m["index"]
        return mons[0]["index"]

    def _set_monitor(self, index):
        """把捕鱼叠加层整体切到指定显示器：炮台/枪口/鱼检测都随之迁移到该屏。"""
        mons = get_monitors()
        mon = None
        for m in mons:
            if m["index"] == index:
                mon = m
                break
        if mon is None and mons:
            mon = mons[0]
        if mon is None:
            return
        ml, mt, mr, mb = mon["work"]  # 用工作区：炮台贴着下缘、不压任务栏
        self.L, self.T, self.W, self.H = ml, mt, mr - ml, mb - mt
        self.win.geometry("%dx%d+%d+%d" % (self.W, self.H, ml, mt))
        self.win.update_idletasks()
        self._make_dib(self.W, self.H)
        self.img = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.img)
        self._recompute_layout()
        # 切屏时清空在途子弹/特效/浮动文字，避免上一屏的局部坐标残留错位
        self.bullets = []
        self.effects = []
        self.floaters = []
        # 炮台旋转缓存的粘贴位置依赖屏幕宽高，必须清掉否则画在旧屏位置
        self._cannon_cache = {}
        self._mon_index = index

    def _recompute_layout(self):
        """依据当前屏幕宽高重算炮台/枪口/HUD 锚点（屏幕切换时调用）。"""
        self.gun_x, self.gun_y = self.W // 2, self.H - 40
        self.cannon_anchor_y = self.H - 12          # 炮台底部贴着屏幕下缘
        self.muzzle = (self.gun_x, self.gun_y - 60)  # 炮口（绘制时还会按倾角更新）
        self.hud = (12, self.H - 78, 250, 70)  # 信息面板（实际位置在 _draw_hud 里按炮台重算）
        self.upgrade_btn = None                     # 炮台旁升级按钮矩形（每帧重算）

    # ---------- Win32 图层 ----------
    def _make_dib(self, w, h):
        if self.hbm:
            gdi32.SelectObject(self.hdc_mem, self.old_hbm)
            gdi32.DeleteObject(self.hbm)
        bi = BITMAPINFO()
        bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.bmiHeader.biWidth = w
        bi.bmiHeader.biHeight = -h
        bi.bmiHeader.biPlanes = 1
        bi.bmiHeader.biBitCount = 32
        bi.bmiHeader.biCompression = 0
        bits = ctypes.c_void_p()
        self.hbm = gdi32.CreateDIBSection(self.hdc_screen, ctypes.byref(bi), 0,
                                          ctypes.byref(bits), None, 0)
        self.bits = bits
        self.old_hbm = gdi32.SelectObject(self.hdc_mem, self.hbm)
        self.dib_size = (w, h)

    # ---------- 炮台 ----------
    def _load_cannon(self):
        """加载当前炮台皮肤的原始贴图（实际大小按等级在绘制时再缩放）。"""
        self.cannon_img = None
        self.cannon_src = None
        self._cannon_cache = {}
        self._cannon_level_cache = {}
        if not self.cannons:
            return
        path = self.cannons[self.cannon_index % len(self.cannons)]
        try:
            im = Image.open(path).convert("RGBA")
        except Exception:
            return
        self.cannon_src = im

    def _cannon_scale_mult(self, lv):
        """炮台视觉缩放系数：等级越高炮台越大，但封顶（CANNON_VISUAL_CAP）以免
        高等级时贴图大得离谱。等级数字/威力/费用仍按真实 lv 计算。"""
        return 1.0 + (min(lv, CANNON_VISUAL_CAP) - 1) * 0.06

    def _cannon_level_img(self, lv):
        """按炮台等级返回缩放后的贴图（等级越高炮台越大，到封顶后不再变大），带缓存。"""
        if self.cannon_src is None:
            return None
        img = self._cannon_level_cache.get(lv)
        if img is None:
            mult = self._cannon_scale_mult(lv)  # Lv1=1.0 … Lv10≈1.54，之后封顶
            tw = max(1, int(round(self.cannon_base_w * mult)))
            th = max(1, int(round(self.cannon_src.height * tw / self.cannon_src.width)))
            img = self.cannon_src.resize((tw, th), Image.LANCZOS)
            img = self._decorate_cannon_level(img, lv)
            self._cannon_level_cache[lv] = img
        return img

    def _decorate_cannon_level(self, img, lv):
        """把炮台自带屏幕上的「90000」抹掉，改写当前等级（画进贴图，随炮台一起转）。"""
        W, H = img.size
        cx, cy = W * 0.5, H * 0.70
        hw, hh = W * 0.235, H * 0.115
        x0, y0, x1, y1 = int(cx - hw), int(cy - hh), int(cx + hw), int(cy + hh)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(W - 1, x1), min(H - 1, y1)
        px = img.load()
        darks = [px[x, y][:3] for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)
                 if max(px[x, y][:3]) < 130]
        if darks:
            n = len(darks)
            bg = tuple(sorted(c[k] for c in darks)[n // 2] for k in range(3))
        else:
            bg = (12, 20, 40)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([x0, y0, x1, y1], radius=max(3, (y1 - y0) // 3), fill=bg)
        size = max(8, int((y1 - y0) * 0.85))
        font = load_cjk_font(size)
        text = "Lv%d" % lv
        try:
            bbox = d.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            tw, th, bbox = size * 2, size, (0, 0, 0, 0)
        d.text((cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]), text,
               fill=(0, 225, 255), font=font)
        return img

    def set_cannon(self, idx):
        """切换炮台皮肤并立即重绘。"""
        self.cannon_index = idx
        self._load_cannon()
        self._render()

    def _cannon_menu(self, e):
        """右键点击炮台时弹出皮肤切换菜单（仅命中炮台矩形才弹出）。"""
        r = getattr(self, "cannon_rect", None)
        if r is None:
            return
        x0, y0, x1, y1 = r
        if not (x0 - 4 <= e.x <= x1 + 4 and y0 - 4 <= e.y <= y1 + 4):
            return
        menu = tk.Menu(self.app.root, tearoff=0)
        c_menu = tk.Menu(menu, tearoff=0)
        n = max(1, len(self.cannons))
        cur = tk.IntVar(value=self.app.cannon_index % n)
        for i in range(len(self.cannons)):
            c_menu.add_radiobutton(label="炮台 %d" % (i + 1),
                                   variable=cur, value=i,
                                   command=lambda k=i: self.app.set_cannon(k))
        menu.add_cascade(label="更换炮台", menu=c_menu)
        menu.add_separator()
        menu.add_command(label="退出捕鱼模式", command=self.app.toggle_fishing)
        menu.tk_popup(e.x_root, e.y_root)

    def _draw_cannon(self, ang):
        """在底部中央绘制炮台贴图（随等级放大、随鼠标倾斜），并记录炮口位置。"""
        gx = self.gun_x
        anchor_y = self.cannon_anchor_y
        lv = self.app.cannon_level
        if self.cannon_src is None:  # 无贴图时退回简单圆形基座
            self.draw.ellipse([gx - 26, anchor_y - 56, gx + 26, anchor_y],
                              fill=(74, 88, 110))
            self.draw.ellipse([gx - 10, anchor_y - 46, gx + 10, anchor_y - 26],
                              fill=(120, 205, 255))
            self.muzzle = (gx, anchor_y - 56)
            self.cannon_rect = (gx - 26, anchor_y - 56, gx + 26, anchor_y)
            if self.font:
                self.draw.text((gx - 12, anchor_y - 30), "Lv%d" % lv,
                               fill=(235, 240, 255), font=self.font)
            return
        im = self._cannon_level_img(lv)
        # 目标相对“正上方”的偏差 -> 倾斜角（限幅，避免底座倒转）
        rel = ang + math.pi / 2.0
        lim = math.radians(self.cannon_tilt_max)
        tilt = max(-lim, min(lim, rel))
        key = (self.cannon_index, lv, int(round(math.degrees(tilt))))
        item = self._cannon_cache.get(key)
        if item is None:
            pad = int(max(im.width, im.height) * 0.7) + 4
            canvas = Image.new("RGBA", (im.width + pad * 2, im.height + pad * 2), (0, 0, 0, 0))
            canvas.paste(im, (pad, pad))
            pivot = (pad + im.width / 2.0, pad + im.height)  # 贴图底部中心
            rot = canvas.rotate(-math.degrees(tilt), center=pivot, resample=Image.BICUBIC)
            item = (rot, (int(gx - pivot[0]), int(anchor_y - pivot[1])))
            self._cannon_cache[key] = item
        rot, pos = item
        self.img.paste(rot, pos, rot)
        self.cannon_rect = (pos[0], pos[1], pos[0] + rot.width, pos[1] + rot.height)
        # 炮口 = 枢轴 + 旋转后的炮管向量
        L = im.height - 2
        self.muzzle = (gx + L * math.sin(tilt), anchor_y - L * math.cos(tilt))

    def _render(self):
        self.draw.rectangle([0, 0, self.W, self.H], fill=(0, 0, 0, 0))
        dx = self.mx - self.gun_x
        dy = self.my - self.gun_y
        ang = math.atan2(dy, dx) if (dx or dy) else -math.pi / 2

        # 子弹
        for b in self.bullets:
            self.draw.ellipse([b["x"] - b["r"], b["y"] - b["r"], b["x"] + b["r"], b["y"] + b["r"]],
                              fill=(255, 220, 90))
            self.draw.ellipse([b["x"] - 2, b["y"] - 2, b["x"] + 2, b["y"] + 2],
                              fill=(255, 255, 220))

        # 效果：抓捕网 / 落空火花
        for e in self.effects:
            p = e["t"] / e["life"]
            if e["kind"] == "catch":
                r = 8 + p * 40
                self.draw.ellipse([e["x"] - r, e["y"] - r, e["x"] + r, e["y"] + r],
                                  outline=(255, 220, 90), width=3)
                for k in range(6):
                    a = p * 6.28 + k
                    cx = e["x"] + math.cos(a) * r
                    cy = e["y"] + math.sin(a) * r
                    self.draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(255, 215, 60))
            else:
                r = 6 + p * 16
                self.draw.line([e["x"] - r, e["y"] - r, e["x"] + r, e["y"] + r], fill=(200, 200, 200), width=2)
                self.draw.line([e["x"] + r, e["y"] - r, e["x"] - r, e["y"] + r], fill=(200, 200, 200), width=2)

        # 炮台（底部中央，随鼠标小幅倾斜）；同时更新 self.muzzle
        self._draw_cannon(ang)

        # 鱼的血条（受击后短暂显示，最后一次受击 HP_BAR_HIDE_AFTER 秒后自动隐藏）
        now = time.time()
        for f in self.app.fishes:
            self._ensure_hp(f)
            if f.hp < f.max_hp and (now - f.last_hit) <= HP_BAR_HIDE_AFTER:
                bx, by, bw, bh = f.x - self.L, f.y - self.T - 9, f.w, 5
                ratio = max(0.0, f.hp / f.max_hp)
                self.draw.rectangle([bx, by, bx + bw, by + bh], fill=(30, 30, 30, 210))
                col = (int(255 * (1 - ratio)), int(220 * ratio) + 35, 50)
                self.draw.rectangle([bx, by, bx + bw * ratio, by + bh], fill=col)

        # 浮动文字（伤害数字 / 捕获提示）—— 大号字体 + 描边
        for fl in self.floaters:
            col = fl.get("color", (255, 90, 60))
            font = self.big_font or self.font
            text = fl["text"]
            ty = fl["y"]
            if font:
                w = self.draw.textlength(text, font=font)
                self.draw.text((fl["x"] - w / 2, ty), text, fill=col, font=font,
                               stroke_width=3, stroke_fill=(0, 0, 0))
            else:
                self.draw.text((fl["x"] - 14, ty), text, fill=col)

        self._draw_hud()
        self._premultiply_rect(self.hud)  # 半透明面板需预乘，否则颜色偏亮

        # 捕鱼模式下：鼠标所指的鱼，在其上方画信息卡；瞄具离开后延迟 ~3s 跟随该鱼再消失
        hovered = self._hovered_fish()
        if hovered is not None:
            self._hover_linger_fish = hovered
            self._hover_linger_at = None  # 正指着，取消延迟
        elif self._hover_linger_fish is not None:
            if self._hover_linger_at is None:
                self._hover_linger_at = time.monotonic() + INFO_CARD_LINGER  # 仅挂一次
            elif time.monotonic() >= self._hover_linger_at:
                self._hover_linger_fish = None
                self._hover_linger_at = None
        show_fish = hovered if hovered is not None else self._hover_linger_fish
        if show_fish is not None and show_fish in self.app.fishes:
            cw, ch = INFO_CARD_W, INFO_CARD_H
            cx = show_fish.x - self.L + show_fish.w / 2 - cw / 2
            cy = show_fish.y - self.T - ch - 6
            if cy < 0:
                cy = show_fish.y - self.T + show_fish.h + 6
            cx = max(0, min(cx, self.W - cw))
            cy = max(0, min(cy, self.H - ch))
            draw_fish_info_card(self.img, self.draw, show_fish, int(cx), int(cy), self.font)
            self._premultiply_rect((cx, cy, cx + cw, cy + ch))

        # 导出 BGRA（半透明区域已在上面预乘，其余像素 alpha 仍为 0/255）
        r, g, b, a = self.img.split()
        bgra = Image.merge("RGBA", (b, g, r, a)).tobytes()
        ctypes.memmove(self.bits, bgra, self.W * self.H * 4)
        blend = BLENDFUNCTION(0, 0, 255, 1)
        dst = POINT(self.L, self.T)
        sz = SIZE(self.W, self.H)
        src = POINT(0, 0)
        user32.UpdateLayeredWindow(self.hwnd, self.hdc_screen, ctypes.byref(dst),
                                   ctypes.byref(sz), self.hdc_mem, ctypes.byref(src),
                                   0, ctypes.byref(blend), ULW_ALPHA)

    def _premultiply_rect(self, box):
        """对指定矩形做 alpha 预乘（UpdateLayeredWindow 的 ULW_ALPHA 要求）。

        只处理含半透明像素的小块（信息面板 / 信息卡），避免每帧预乘整屏的开销。
        """
        x0, y0 = max(0, int(box[0])), max(0, int(box[1]))
        x1, y1 = min(self.W, int(box[2])), min(self.H, int(box[3]))
        w, h = x1 - x0, y1 - y0
        if w <= 0 or h <= 0:
            return
        try:
            sub = self.img.crop((x0, y0, x1, y1)).convert("RGBA")
            r, g, b, a = sub.split()
            pm = Image.merge("RGBA", (ImageChops.multiply(r, a),
                                      ImageChops.multiply(g, a),
                                      ImageChops.multiply(b, a), a))
            self.img.paste(pm, (x0, y0))
        except Exception:
            pass

    def _hovered_fish(self):
        """返回鼠标当前所指的鱼（屏幕坐标命中检测），无则 None。"""
        sx = self.L + self.mx
        sy = self.T + self.my
        for f in self.app.fishes:
            if f.x <= sx <= f.x + f.w and f.y <= sy <= f.y + f.h:
                return f
        return None

    def _hud_text(self, x, y, text, fill, font):
        """带阴影的 HUD 文字，增加层次感。"""
        if font:
            self.draw.text((x + 1, y + 1), text, fill=(0, 0, 0, 170), font=font)
            self.draw.text((x, y), text, fill=fill, font=font)
        else:
            self.draw.text((x, y), text, fill=fill)

    def _draw_hud(self):
        lv = self.app.cannon_level
        w, h = self.hud[2], self.hud[3]
        # 摆在炮台左侧，底部与炮台底座对齐（炮台随等级变宽，故每帧重算）
        img = self._cannon_level_img(lv)
        cw = img.width if img is not None else int(self.cannon_base_w * self._cannon_scale_mult(lv))
        x0 = self.gun_x - cw / 2.0 - 16 - w
        y0 = self.H - 12 - h
        x0 = max(12, min(x0, self.W - w - 12))
        y0 = max(12, min(y0, self.H - h - 12))
        self.hud = (int(x0), int(y0), int(w), int(h))
        x0, y0, w, h = self.hud

        # 投影
        try:
            self.draw.rounded_rectangle([x0 + 3, y0 + 4, x0 + w + 3, y0 + h + 4],
                                        radius=14, fill=(0, 0, 0, 90))
        except Exception:
            pass
        # 圆角渐变底（半透明）
        try:
            mask = Image.new("L", (w, h), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=14, fill=255)
            grad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            gd = ImageDraw.Draw(grad)
            top = (50, 66, 108, 178)
            bot = (16, 22, 40, 178)
            for i in range(h):
                t = i / max(1, h - 1)
                col = tuple(int(top[k] + (bot[k] - top[k]) * t) for k in range(4))
                gd.line([(0, i), (w, i)], fill=col)
            sub = self.img.crop((x0, y0, x0 + w, y0 + h))
            sub.paste(grad, (0, 0), mask)
            self.img.paste(sub, (x0, y0))
        except Exception:
            self.draw.rectangle([x0, y0, x0 + w, y0 + h], fill=(20, 28, 48, 150))
        # 柔和描边 + 左侧高亮条
        self.draw.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=14,
                                    outline=(130, 190, 245, 210), width=2)
        self.draw.rounded_rectangle([x0 + 7, y0 + 13, x0 + 11, y0 + h - 13], radius=2,
                                    fill=(110, 205, 255, 210))

        font = getattr(self, "hud_font", None) or self.font
        coins = self.app.coins
        rows = [
            ("金币：%d" % coins, (255, 208, 90, 255)),
            ("炮台 Lv%d  威力x%d" % (lv, lv), (130, 220, 255, 255)),
            ("点此面板升级（%d 金币）" % self.app.cannon_upgrade_cost(), (205, 235, 255, 255)),
        ]
        ty = y0 + 10
        for text, col in rows:
            self._hud_text(x0 + 19, ty, text, col, font)
            ty += 19

        # 炮台升级按钮：未满级时显示在炮台右侧；金币足够为金色，否则灰色
        if lv < CANNON_MAX_LEVEL:
            bw, bh = 134, 50
            bx = self.gun_x + cw / 2 + 14
            by = (self.H - 12) - bh
            bx = max(12, min(bx, self.W - bw - 12))
            by = max(12, min(by, self.H - bh - 12))
            bx, by = int(bx), int(by)  # PIL 的 crop/paste 只接受整数坐标
            cost = self.app.cannon_upgrade_cost()
            afford = self.app.coins >= cost
            self.upgrade_btn = (int(bx), int(by), int(bw), int(bh), afford)
            # 渐变底
            btop = (255, 198, 72, 235) if afford else (92, 98, 118, 205)
            bbot = (212, 138, 22, 235) if afford else (62, 68, 86, 205)
            bmask = Image.new("L", (bw, bh), 0)
            ImageDraw.Draw(bmask).rounded_rectangle(
                [0, 0, bw - 1, bh - 1], radius=12, fill=255)
            bgrad = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
            bgd = ImageDraw.Draw(bgrad)
            for i in range(bh):
                t = i / max(1, bh - 1)
                col = tuple(int(btop[k] + (bbot[k] - btop[k]) * t) for k in range(4))
                bgd.line([(0, i), (bw, i)], fill=col)
            bsub = self.img.crop((bx, by, bx + bw, by + bh))
            bsub.paste(bgrad, (0, 0), bmask)
            self.img.paste(bsub, (bx, by))
            self.draw.rounded_rectangle(
                [bx, by, bx + bw, by + bh], radius=12,
                outline=(255, 240, 180, 245) if afford else (150, 160, 180, 220), width=2)
            cx = bx + bw / 2
            self.draw.text((cx, by + 17), "升级炮台", anchor="mm",
                           fill=(255, 255, 255, 255) if afford else (205, 210, 220, 235),
                           font=font)
            sub = ("Lv%d→%d  %d金币" % (lv, lv + 1, cost)) if afford else ("需 %d 金币" % cost)
            self.draw.text((cx, by + 37), sub, anchor="mm",
                           fill=(255, 244, 205, 255) if afford else (185, 190, 205, 225),
                           font=self.font)
        else:
            self.upgrade_btn = None

    # ---------- 逻辑 ----------
    _FISH_VALUE = FISH_VALUE  # 引用模块级鱼价表（单一来源）

    def _fish_info(self, fish):
        name = os.path.basename(fish.species[1])
        return self._FISH_VALUE.get(name, (5, 0.25))

    def tick(self, dt):
        # 炮台跟随鼠标所在屏幕：鼠标跨屏则把叠加层整体迁移过去
        cx, cy = getattr(self, "_cur_x", 0), getattr(self, "_cur_y", 0)
        idx = self._monitor_index_at(cx, cy)
        if idx is not None and idx != getattr(self, "_mon_index", None):
            self._set_monitor(idx)

        if self.pending_fires:
            # 发射冷却：按住空格时系统自动连发约 30 次/秒，直接全打出去会瞬间
            # 起播几十个开炮音，松手后声音仍持续好几秒。按冷却放行，多余按键丢弃
            now = time.monotonic()
            if self._last_fire_at is None or now - self._last_fire_at >= FIRE_COOLDOWN:
                sx, sy = self.pending_fires[-1]  # 取最近一次按键位置（连发时鼠标一般未动）
                self._fire(sx, sy)
                self._last_fire_at = now
        self.pending_fires.clear()

        # 子弹推进 + 碰撞
        for b in list(self.bullets):
            b["x"] += b["vx"] * dt
            b["y"] += b["vy"] * dt
            b["life"] -= dt
            hit = None
            for f in self.app.fishes:
                cx = f.x - self.L + f.w / 2
                cy = f.y - self.T + f.h / 2
                rad = min(f.w, f.h) / 2 * 0.9 + b["r"]
                if (b["x"] - cx) ** 2 + (b["y"] - cy) ** 2 <= rad * rad:
                    hit = f
                    break
            if hit is not None:
                self._impact(b["x"], b["y"], hit)
                self.bullets.remove(b)
                continue
            if b["life"] <= 0 or b["x"] < -30 or b["x"] > self.W + 30 \
                    or b["y"] < -30 or b["y"] > self.H + 30:
                self.bullets.remove(b)

        for e in list(self.effects):
            e["t"] += dt
            if e["t"] >= e["life"]:
                self.effects.remove(e)

        for fl in list(self.floaters):
            fl["t"] += dt
            fl["y"] -= fl["vy"] * dt
            if fl["t"] >= fl["life"]:
                self.floaters.remove(fl)

        self._render()

    def _fire(self, sx, sy):
        """sx,sy 为屏幕坐标；从炮口朝该方向发射子弹（直线飞行）。"""
        lx = sx - self.L
        ly = sy - self.T
        dx = lx - self.gun_x
        dy = ly - self.gun_y
        ang = math.atan2(dy, dx) if (dx or dy) else -math.pi / 2
        x0, y0 = self.muzzle  # 从炮台炮口出生
        lv = self.app.cannon_level
        self.app.coins = max(0, self.app.coins - lv)  # 发射消耗金币
        r = 3 + lv
        self.bullets.append({"x": x0, "y": y0,
                             "vx": math.cos(ang) * self.bullet_speed,
                             "vy": math.sin(ang) * self.bullet_speed,
                             "r": r, "life": 3.0})
        self.app.sounds.play("shoot")

    def _ensure_hp(self, fish):
        """懒初始化鱼的血量（金币倍率越高，血越厚）。"""
        if not getattr(fish, "max_hp_set", False):
            value, _ = self._fish_info(fish)
            fish.max_hp = value * 8
            fish.hp = fish.max_hp
            fish.max_hp_set = True
            fish.last_hit = -1e9  # 初始视为很久没被打，不显示血条

    def _impact(self, x, y, fish):
        self._ensure_hp(fish)
        lv = self.app.cannon_level
        value, _ = self._fish_info(fish)
        dmg = lv * 8  # 炮台等级越高，单发伤害越高
        fish.hp -= dmg
        fish.last_hit = time.time()  # 记录受击时间，用于血条自动隐藏
        # 掉血提示：在鱼身上方弹出伤害数字
        self.floaters.append({"x": fish.x - self.L + fish.w / 2,
                              "y": fish.y - self.T - 6,
                              "text": "-%d" % dmg, "t": 0.0, "life": 0.8,
                              "vy": 55, "color": (255, 90, 60)})
        if fish.hp <= 0:
            reward = value * lv * REWARD_MULT
            self.app.coins += reward
            self.app.remove_fish(fish)
            self.effects.append({"kind": "catch", "x": x, "y": y, "t": 0.0, "life": 0.5})
            self.floaters.append({"x": fish.x - self.L + fish.w / 2,
                                  "y": fish.y - self.T - 22,
                                  "text": "捕获 +%d" % reward, "t": 0.0, "life": 1.1,
                                  "vy": 45, "color": (120, 255, 120)})
            self.app.sounds.play("catch")
            self.app.save_config()
        else:
            self.effects.append({"kind": "miss", "x": x, "y": y, "t": 0.0, "life": 0.25})
            self.app.sounds.play("hit")
            if self.app.berserk_enabled:
                fish.berserk = True
                fish.berserk_t = BERSERK_DURATION
                self.floaters.append({"x": fish.x - self.L + fish.w / 2, "y": fish.y - self.T - 36,
                                      "text": "狂暴!", "t": 0.0, "life": 1.0,
                                      "vy": 40, "color": (255, 70, 70)})

    def _try_upgrade(self):
        lv = self.app.cannon_level
        if lv >= CANNON_MAX_LEVEL:
            return
        cost = self.app.cannon_upgrade_cost()
        if self.app.coins >= cost:
            self.app.coins -= cost
            self.app.cannon_level = lv + 1
            self.app.sounds.play("levelup")
            self.app.save_config()
            self.floaters.append({"x": self.gun_x, "y": self.gun_y - 78,
                                  "text": "升级! Lv%d" % self.app.cannon_level,
                                  "t": 0.0, "life": 1.0, "vy": 42,
                                  "color": (255, 222, 120)})
        else:
            self.floaters.append({"x": self.gun_x, "y": self.gun_y - 78,
                                  "text": "金币不足", "t": 0.0, "life": 0.9,
                                  "vy": 42, "color": (255, 110, 90)})

    # ---------- 鼠标钩子 ----------
    def _install_hook(self):
        self._hook_cb = HOOKPROC(self._hook_proc)
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._hook_cb,
                                              kernel32.GetModuleHandleW(None), 0)
        self._kb_cb = HOOKPROC(self._keyboard_proc)
        self._kb_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_cb,
                                                 kernel32.GetModuleHandleW(None), 0)

    def _hook_proc(self, nCode, wParam, lParam):
        if nCode == 0:
            hs = MSLLHOOKSTRUCT.from_address(lParam)
            if wParam == WM_MOUSEMOVE:
                self._cur_x, self._cur_y = hs.pt.x, hs.pt.y
                self.mx = hs.pt.x - self.L
                self.my = hs.pt.y - self.T
            elif wParam == WM_LBUTTONDOWN:
                lx = hs.pt.x - self.L
                ly = hs.pt.y - self.T
                hx0, hy0, hw, hh = self.hud
                if hx0 <= lx <= hx0 + hw and hy0 <= ly <= hy0 + hh:
                    self._try_upgrade()  # 点 HUD 面板 = 升级炮台
                elif self.upgrade_btn is not None:
                    bx, by, bw, bh, _afford = self.upgrade_btn
                    if bx <= lx <= bx + bw and by <= ly <= by + bh:
                        self._try_upgrade()  # 点炮台旁的升级按钮
                # 左键不再发射（改由空格键发射）
        return user32.CallNextHookEx(self._hook if self._hook else 0, nCode, wParam, lParam)

    # ---------- 键盘钩子（空格发射） ----------
    def _keyboard_proc(self, nCode, wParam, lParam):
        if nCode == 0 and wParam == WM_KEYDOWN:
            ks = KBDLLHOOKSTRUCT.from_address(lParam)
            if ks.vkCode == VK_SPACE:
                # 朝当前鼠标位置发射一发（与左键点击等价）
                self.pending_fires.append((self.mx + self.L, self.my + self.T))
        return user32.CallNextHookEx(self._kb_hook if self._kb_hook else 0, nCode, wParam, lParam)

    def destroy(self):
        try:
            if self._hook:
                user32.UnhookWindowsHookEx(self._hook)
                self._hook = 0
            if self._kb_hook:
                user32.UnhookWindowsHookEx(self._kb_hook)
                self._kb_hook = 0
        except Exception:
            pass
        try:
            if self.hbm:
                gdi32.SelectObject(self.hdc_mem, self.old_hbm)
                gdi32.DeleteObject(self.hbm)
            gdi32.DeleteDC(self.hdc_mem)
            user32.ReleaseDC(0, self.hdc_screen)
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass


# ---------------------------------------------------------------- 鱼钩贴图
HOOK_TILE_W = HOOK_TILE_H = 96           # 瓦片尺寸（取大方格，留足旋转不裁切）
HOOK_EYE = (48, 40)                      # 钩眼在瓦片中的位置（贴绳端时对准这里）
_hook_tile_cache = None


def _make_fishhook_tile():
    """生成反向 J 形鱼钩贴图：算中心线，用渐变变细的粗线沿它描（6 倍超采样后缩小），
    得到平滑、有粗细渐变、带钩眼/倒刺的真鱼钩。弯钩朝左、钩尖在左上。"""
    W, H = HOOK_TILE_W, HOOK_TILE_H
    S = 6
    w, h = W * S, H * S
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    steel = (228, 238, 250, 255)
    edge = (84, 100, 132, 255)
    ex, ey = HOOK_EYE[0] * S, HOOK_EYE[1] * S
    shank, r = 18 * S, 11 * S
    # 中心线：钩眼 -> 钩柄(竖直向下) -> 半圆弯钩(向下沉再向左) -> 钩尖(向上内收)
    pts = [(ex, ey), (ex, ey + shank)]
    for a in range(0, 181, 4):
        rad = math.radians(a)
        pts.append((ex - r + r * math.cos(rad), ey + shank + r * math.sin(rad)))
    tipx, tipy = ex - 2 * r, ey + shank
    pts.append((tipx + 3 * S, tipy - 13 * S))
    widths = [7 * S, 6 * S, 5 * S, 4 * S, 3 * S]   # 由粗到细，做出渐变收尖
    n = len(pts) - 1
    for i in range(n):                              # 深色外轮廓（粗）
        wi = widths[min(i, len(widths) - 1)]
        d.line([pts[i], pts[i + 1]], fill=edge, width=int(wi) + 2 * S, joint="curve")
    for i in range(n):                              # 亮色金属主体（细）
        wi = widths[min(i, len(widths) - 1)]
        d.line([pts[i], pts[i + 1]], fill=steel, width=int(wi), joint="curve")
    bx, by = pts[-1]                               # 倒刺（向钩口内侧后方）
    d.line([(bx, by), (bx + 6 * S, by + 4 * S)], fill=edge, width=3 * S)
    d.ellipse([ex - 4 * S, ey - 6 * S, ex + 4 * S, ey + 2 * S], outline=edge, width=3 * S)  # 钩眼
    d.ellipse([ex - 4 * S, ey - 6 * S, ex + 4 * S, ey + 2 * S], outline=steel, width=1 * S)
    return im.resize((W, H), Image.LANCZOS)


def _get_hook_tile():
    """生成并缓存鱼钩贴图（进程内一次）；失败返回 None 走矢量回退。"""
    global _hook_tile_cache
    if _hook_tile_cache is None:
        try:
            _hook_tile_cache = _make_fishhook_tile()
        except Exception:
            _hook_tile_cache = False
    return _hook_tile_cache or None


# ---------------------------------------------------------------- 应用
class GoldMinerOverlay:
    """黄金矿工模式：全屏透明叠加层 + 全局鼠标/键盘钩子。

    顶端中央垂下一条会钟摆摆动的钩绳；空格放钩（沿当前角度伸出），钩到鱼则
    收回（鱼越大收回越慢），回到顶端时按「鱼价值 × 等级」给金币并把鱼收走。
    与捕鱼模式（炮台）互斥，作为独立的托盘开关存在。
    """

    def __init__(self, app):
        self.app = app
        L, T, R, B = app.workarea
        self.L, self.T, self.W, self.H = L, T, R - L, B - T
        self.mx, self.my = self.W // 2, self.H // 2
        self._FISH_VALUE = FISH_VALUE

        # 钩子状态机：idle（摆动）/ firing（伸出）/ retract（收回）
        self.state = "idle"
        self.angle = 0.0                       # 与竖直向下方向的夹角（弧度）
        self.swing_dir = 1
        self.swing_speed = 1.7                  # 摆动角速度（弧度/秒）
        self.swing_max = math.radians(80)
        self.rest_len = 60
        self.max_len = int(math.hypot(self.W, self.H)) + 80
        self.len = self.rest_len
        self.extend_speed = 1500.0
        self.retract_base = 1000.0
        self.carry_fish = None
        self.carry_speed = 1.0
        self.floaters = []
        self.effects = []
        self._carry_cache = {}     # (id(fish), frame) -> 已还原的直乘 alpha 图像
        self._cur_x, self._cur_y = 0, 0
        self._mon_index = None
        self.pivot = (self.W / 2, 16)

        try:
            self.font = load_cjk_font(14)
        except Exception:
            self.font = None
        try:
            self.hud_font = load_cjk_font(16)
        except Exception:
            self.hud_font = None
        try:
            self.big_font = load_cjk_font(22)
        except Exception:
            self.big_font = self.font

        self.win = tk.Toplevel(app.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="black")
        self.win.geometry(f"+{L}+{T}")
        self.win.update_idletasks()

        self.hwnd = user32.GetAncestor(self.win.winfo_id(), GA_ROOT)
        ex = user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED | WS_EX_TOOLWINDOW)

        self.hdc_screen = user32.GetDC(0)
        self.hdc_mem = gdi32.CreateCompatibleDC(self.hdc_screen)
        self.hbm = None
        self.old_hbm = None
        self.bits = None
        self.dib_size = (0, 0)
        self._make_dib(self.W, self.H)

        self.img = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.img)

        self._hook = None
        self._kb_hook = None
        self._install_hook()
        self.win.bind("<Button-3>", self._menu)
        self._render()

        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        self._cur_x, self._cur_y = pt.x, pt.y
        idx = self._monitor_index_at(pt.x, pt.y)
        if idx is not None:
            self._set_monitor(idx)

    # ---------- 屏幕跟随（与捕鱼模式同理） ----------
    def _monitor_index_at(self, x, y):
        mons = get_monitors()
        if not mons:
            return None
        for m in mons:
            rl, rt, rr, rb = m["rect"]
            if rl <= x <= rr and rt <= y <= rb:
                return m["index"]
        return mons[0]["index"]

    def _set_monitor(self, index):
        mons = get_monitors()
        mon = None
        for m in mons:
            if m["index"] == index:
                mon = m
                break
        if mon is None and mons:
            mon = mons[0]
        if mon is None:
            return
        ml, mt, mr, mb = mon["work"]
        self.L, self.T, self.W, self.H = ml, mt, mr - ml, mb - mt
        self.win.geometry("%dx%d+%d+%d" % (self.W, self.H, ml, mt))
        self.win.update_idletasks()
        self._make_dib(self.W, self.H)
        self.img = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.img)
        self.pivot = (self.W / 2, 16)
        self.max_len = int(math.hypot(self.W, self.H)) + 80
        self.floaters = []
        self.effects = []
        self._carry_cache = {}
        self._mon_index = index

    # ---------- Win32 图层 ----------
    def _make_dib(self, w, h):
        if self.hbm:
            gdi32.SelectObject(self.hdc_mem, self.old_hbm)
            gdi32.DeleteObject(self.hbm)
        bi = BITMAPINFO()
        bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.bmiHeader.biWidth = w
        bi.bmiHeader.biHeight = -h
        bi.bmiHeader.biPlanes = 1
        bi.bmiHeader.biBitCount = 32
        bi.bmiHeader.biCompression = 0
        bits = ctypes.c_void_p()
        self.hbm = gdi32.CreateDIBSection(self.hdc_screen, ctypes.byref(bi), 0,
                                          ctypes.byref(bits), None, 0)
        self.bits = bits
        self.old_hbm = gdi32.SelectObject(self.hdc_mem, self.hbm)
        self.dib_size = (w, h)

    # ---------- 钩子 ----------
    def _install_hook(self):
        self._hook_cb = HOOKPROC(self._hook_proc)
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._hook_cb,
                                              kernel32.GetModuleHandleW(None), 0)
        self._kb_cb = HOOKPROC(self._keyboard_proc)
        self._kb_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_cb,
                                                 kernel32.GetModuleHandleW(None), 0)

    def _hook_proc(self, nCode, wParam, lParam):
        if nCode == 0:
            hs = MSLLHOOKSTRUCT.from_address(lParam)
            if wParam == WM_MOUSEMOVE:
                self._cur_x, self._cur_y = hs.pt.x, hs.pt.y
                self.mx = hs.pt.x - self.L
                self.my = hs.pt.y - self.T
            # 左键在矿工模式不发射（放钩用空格）
        return user32.CallNextHookEx(self._hook if self._hook else 0, nCode, wParam, lParam)

    def _keyboard_proc(self, nCode, wParam, lParam):
        if nCode == 0 and wParam == WM_KEYDOWN:
            ks = KBDLLHOOKSTRUCT.from_address(lParam)
            if ks.vkCode == VK_SPACE and self.state == "idle":
                self.state = "firing"
                self.len = self.rest_len
                self.app.sounds.play("poke")
        return user32.CallNextHookEx(self._kb_hook if self._kb_hook else 0, nCode, wParam, lParam)

    # ---------- 右键菜单 ----------
    def _menu(self, e):
        """钓鱼模式下右键弹出菜单：退出钓鱼模式。"""
        menu = tk.Menu(self.app.root, tearoff=0)
        menu.add_command(label="退出钓鱼模式", command=self.app.toggle_goldminer)
        menu.tk_popup(e.x_root, e.y_root)

    # ---------- 逻辑 ----------
    def _tip(self):
        px, py = self.pivot
        return (px + math.sin(self.angle) * self.len,
                py + math.cos(self.angle) * self.len)

    def _fish_at(self, x, y):
        for f in self.app.fishes:
            fx = f.x - self.L
            fy = f.y - self.T
            if fx <= x <= fx + f.w and fy <= y <= fy + f.h:
                return f
        return None

    def _fish_info(self, fish):
        name = os.path.basename(fish.species[1])
        return self._FISH_VALUE.get(name, (5, 0.25))

    def tick(self, dt):
        cx, cy = self._cur_x, self._cur_y
        idx = self._monitor_index_at(cx, cy)
        if idx is not None and idx != self._mon_index:
            self._set_monitor(idx)

        if self.state == "idle":
            self.angle += self.swing_dir * self.swing_speed * dt
            if self.angle > self.swing_max:
                self.angle = self.swing_max
                self.swing_dir = -1
            elif self.angle < -self.swing_max:
                self.angle = -self.swing_max
                self.swing_dir = 1
            self.len = self.rest_len
        elif self.state == "firing":
            self.len += self.extend_speed * dt
            tipx, tipy = self._tip()
            hit = self._fish_at(tipx, tipy)
            if hit is not None:
                self.carry_fish = hit
                user32.ShowWindow(hit.hwnd, SW_HIDE)  # 藏起桌面鱼，避免双重绘制
                sizef = (hit.w + hit.h) / 2.0
                self.carry_speed = max(0.16, 240.0 / (sizef + 140.0))  # 大鱼收得更慢
                self.state = "retract"
            elif self.len >= self.max_len or tipy > self.H + 30 \
                    or tipx < -30 or tipx > self.W + 30:
                self.state = "retract"
        elif self.state == "retract":
            speed = self.retract_base if self.carry_fish is None \
                else self.retract_base * self.carry_speed
            self.len -= speed * dt
            if self.len <= self.rest_len:
                self.len = self.rest_len
                if self.carry_fish is not None:
                    self._collect(self.carry_fish)
                    self.carry_fish = None
                self.state = "idle"

        for fl in list(self.floaters):
            fl["t"] += dt
            fl["y"] -= fl["vy"] * dt
            if fl["t"] >= fl["life"]:
                self.floaters.remove(fl)
        for e in list(self.effects):
            e["t"] += dt
            if e["t"] >= e["life"]:
                self.effects.remove(e)

        self._render()

    def _collect(self, fish):
        value, _ = self._fish_info(fish)
        reward = value * fish.level
        self.app.coins += reward
        self.app.remove_fish(fish)  # 内部会 destroy 鱼窗口
        self.app.sounds.play("catch")
        self.effects.append({"kind": "catch", "x": self.pivot[0],
                             "y": self.pivot[1] + 24, "t": 0.0, "life": 0.5})
        self.floaters.append({"x": self.pivot[0], "y": self.pivot[1] + 40,
                              "text": "钓到! +%d" % reward, "t": 0.0, "life": 1.1,
                              "vy": 45, "color": (120, 255, 120)})

    # ---------- 绘制 ----------
    def _draw_hook(self, x, y):
        """贴鱼钩图：钩眼对准绳端 (x, y)，并按当前绳角旋转（钩身顺绳悬挂）。"""
        tile = _get_hook_tile()
        if tile is not None:
            try:
                rot = tile.rotate(math.degrees(self.angle), center=HOOK_EYE,
                                  resample=Image.BICUBIC)
                self.img.paste(rot, (int(x - HOOK_EYE[0]), int(y - HOOK_EYE[1])), rot)
                return
            except Exception:
                pass
        self.draw.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(210, 220, 240, 255))

    def _draw_carry_fish(self, f, x, y):
        # 用鱼当前的朝向（桌面鱼可能朝左游，用 f.left），避免拉上来后镜像变样
        imgs = f.right if getattr(f, "facing_right", True) else f.left
        if not imgs:
            return
        fi = f.frame % len(imgs)
        raw, (iw, ih) = imgs[fi]
        # species_frames 缓存的是 _premultiply 后的字节（预乘 alpha、R/B 已对调），
        # 不是 PIL.Image。先还原成直乘 alpha 的 PIL 图像（颜色顺序仍保留对调，
        # 留给本叠加层 _render 导出时的 R/B 互换再修正），并缓存避免每帧重算。
        key = (id(f), fi)
        im = self._carry_cache.get(key)
        if im is None:
            try:
                base = Image.frombytes("RGBA", (iw, ih), raw)
            except Exception:
                return
            im = self._unpremultiply(base)
            self._carry_cache[key] = im
        # 按鱼实际尺寸绘制（封顶避免过大），保持与桌面鱼一致
        maxd = 160
        if max(iw, ih) > maxd:
            s = maxd / max(iw, ih)
            im = im.resize((max(1, int(iw * s)), max(1, int(ih * s))), Image.LANCZOS)
        # 鱼挂在钩尖下方：水平居中，鱼顶在绳端下方一点，身体向下垂
        x0 = int(x - im.width / 2)
        y0 = int(y + 16)
        try:
            self.img.paste(im, (x0, y0), im)
        except Exception:
            pass

    def _unpremultiply(self, im):
        """把 _premultiply 出来的预乘字节还原成【正常顺序的直乘 alpha】图像。

        _premultiply 产出的字节序是 [B*a, G*a, R*a, A]（预乘、且 R/B 已对调），
        因为桌面鱼直接喂给 UpdateLayeredWindow 的 BGRA DIB。而本叠加层 _render
        是用 merge((b,g,r,a)) 把 self.img 当【正常 RGBA】再转成 BGRA，所以贴到
        self.img 上必须是正常顺序的直乘图像。这里在还原直乘的同时把 R/B 对调回来，
        否则整条鱼红蓝互换、和桌面鱼完全不一样。
        """
        try:
            import numpy as np
            a = np.frombuffer(im.tobytes(), dtype=np.uint8).reshape(im.height, im.width, 4)
            out = a.astype(np.uint16).copy()
            alpha = out[:, :, 3].astype(np.uint16)
            am = np.where(alpha == 0, 1, alpha)
            # 原字节: [B*a, G*a, R*a, A] -> 除回 alpha 得直乘，并把 0/2 通道对调成 [R, G, B, A]
            rr = (out[:, :, 2] * 255 + am // 2) // am   # 第3字节 = R*a -> 红
            bb = (out[:, :, 0] * 255 + am // 2) // am   # 第1字节 = B*a -> 蓝
            out[:, :, 0] = rr
            out[:, :, 1] = (out[:, :, 1] * 255 + am // 2) // am
            out[:, :, 2] = bb
            out[:, :, 3] = alpha
            return Image.frombytes("RGBA", (im.width, im.height), out.astype(np.uint8).tobytes())
        except Exception:
            px = im.load()
            w, h = im.size
            for yy in range(h):
                for xx in range(w):
                    ba, ga, ra, al = px[xx, yy]  # frombytes(raw): R=B*a, G=G*a, B=R*a
                    if al == 0 or al == 255:
                        # 全不透明/透明无需除，仅把 R/B 对调成正常顺序
                        px[xx, yy] = (ra, ga, ba, al)
                    else:
                        inv = 255.0 / al
                        px[xx, yy] = (min(255, int(round(ra * inv))),
                                      min(255, int(round(ga * inv))),
                                      min(255, int(round(ba * inv))), al)
            return im

    def _draw_hud(self):
        font = self.hud_font or self.font
        x0, y0, w, h = 12, 12, 250, 60
        self.hud = (x0, y0, x0 + w, y0 + h)
        self.draw.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=12,
                                    fill=(18, 24, 42, 205),
                                    outline=(120, 150, 200, 220), width=2)
        self._hud_text(x0 + 16, y0 + 11, "金币：%d" % self.app.coins,
                       (255, 222, 120, 255), font)
        self._hud_text(x0 + 16, y0 + 35, "空格放钩 · 钩到鱼收回",
                       (205, 235, 255, 255), font)

    def _hud_text(self, x, y, text, fill, font):
        if font:
            self.draw.text((x + 1, y + 1), text, fill=(0, 0, 0, 170), font=font)
            self.draw.text((x, y), text, fill=fill, font=font)
        else:
            self.draw.text((x, y), text, fill=fill)

    def _premultiply_rect(self, box):
        x0, y0 = max(0, int(box[0])), max(0, int(box[1]))
        x1, y1 = min(self.W, int(box[2])), min(self.H, int(box[3]))
        w, h = x1 - x0, y1 - y0
        if w <= 0 or h <= 0:
            return
        try:
            sub = self.img.crop((x0, y0, x1, y1)).convert("RGBA")
            r, g, b, a = sub.split()
            pm = Image.merge("RGBA", (ImageChops.multiply(r, a),
                                      ImageChops.multiply(g, a),
                                      ImageChops.multiply(b, a), a))
            self.img.paste(pm, (x0, y0))
        except Exception:
            pass

    def _render(self):
        self.draw.rectangle([0, 0, self.W, self.H], fill=(0, 0, 0, 0))
        px, py = self.pivot
        tipx, tipy = self._tip()
        # 绳
        self.draw.line([(px, py), (tipx, tipy)], fill=(225, 235, 255, 235), width=3)
        # 顶端滑轮座
        self.draw.ellipse([px - 14, py - 14, px + 14, py + 14], fill=(60, 70, 95, 235))
        self.draw.ellipse([px - 7, py - 7, px + 7, py + 7], fill=(150, 170, 210, 255))
        # 先画被钩住的鱼（挂在钩尖下方），再把钩压在鱼顶，像钩子咬住鱼
        if self.carry_fish is not None:
            self._draw_carry_fish(self.carry_fish, tipx, tipy)
        # 钩（鱼钩贴图，钩眼对准绳端并按绳角旋转）
        self._draw_hook(tipx, tipy)
        # 特效
        for e in self.effects:
            p = e["t"] / e["life"]
            r = 8 + p * 40
            self.draw.ellipse([e["x"] - r, e["y"] - r, e["x"] + r, e["y"] + r],
                              outline=(255, 220, 90), width=3)
            for k in range(6):
                a = p * 6.28 + k
                cx = e["x"] + math.cos(a) * r
                cy = e["y"] + math.sin(a) * r
                self.draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(255, 215, 60))
        # 浮动文字
        for fl in self.floaters:
            col = fl.get("color", (255, 90, 60))
            font = self.big_font or self.font
            text = fl["text"]
            ty = fl["y"]
            if font:
                w = self.draw.textlength(text, font=font)
                self.draw.text((fl["x"] - w / 2, ty), text, fill=col, font=font,
                               stroke_width=3, stroke_fill=(0, 0, 0))
            else:
                self.draw.text((fl["x"] - 14, ty), text, fill=col)
        self._draw_hud()
        self._premultiply_rect(self.hud)
        # 导出 BGRA
        r, g, b, a = self.img.split()
        bgra = Image.merge("RGBA", (b, g, r, a)).tobytes()
        ctypes.memmove(self.bits, bgra, self.W * self.H * 4)
        blend = BLENDFUNCTION(0, 0, 255, 1)
        dst = POINT(self.L, self.T)
        sz = SIZE(self.W, self.H)
        src = POINT(0, 0)
        user32.UpdateLayeredWindow(self.hwnd, self.hdc_screen, ctypes.byref(dst),
                                   ctypes.byref(sz), self.hdc_mem, ctypes.byref(src),
                                   0, ctypes.byref(blend), ULW_ALPHA)

    def destroy(self):
        # 收回过程中若仍挂着鱼，恢复其桌面窗口避免凭空消失
        if self.carry_fish is not None:
            try:
                user32.ShowWindow(self.carry_fish.hwnd, SW_SHOW)
            except Exception:
                pass
            self.carry_fish = None
        try:
            if self._hook:
                user32.UnhookWindowsHookEx(self._hook)
                self._hook = 0
            if self._kb_hook:
                user32.UnhookWindowsHookEx(self._kb_hook)
                self._kb_hook = 0
        except Exception:
            pass
        try:
            if self.hbm:
                gdi32.SelectObject(self.hdc_mem, self.old_hbm)
                gdi32.DeleteObject(self.hbm)
            gdi32.DeleteDC(self.hdc_mem)
            user32.ReleaseDC(0, self.hdc_screen)
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass


class App:
    TICK_MS = 33
    SCALES = [("很小", 0.28), ("小", 0.45), ("中", 0.70), ("大", 1.00)]

    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()

        rect = RECT()
        user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
        self.workarea = (rect.left, rect.top, rect.right, rect.bottom)

        self.species_list = find_species()
        if not self.species_list:
            raise RuntimeError(f"在 {FISH_ROOT} 下没有找到鱼素材")

        self.fishes = []
        self.floaters = []  # 普通模式的浮动文字（如繁殖提示）；捕鱼模式用叠加层自己的列表
        self.paused = False
        self.hidden = False
        self.tray = None
        self.fishing = False
        self.fishing_overlay = None
        self.goldminer = False
        self.goldminer_overlay = None
        self.coins = 1000
        self.cannon_level = 1
        self.cannon_index = 0
        self.sound_enabled = True
        self.sounds = SoundManager()
        self.berserk_enabled = True
        self.autostart_enabled = self.is_autostart_enabled()  # 以注册表现状为准
        self.cross_screen = True  # 跨屏游走开关（screen==-1 时为真）；load_config 可能覆盖
        self.screen = -1  # 鱼游走的屏幕：-1=全部屏幕（虚拟桌面），0..n-1=指定显示器；load_config 可能覆盖
        self.mouse_penetration = False  # 鼠标穿透：整窗点击穿透到桌面；load_config 可能覆盖
        self.max_fish = MAX_FISH  # 鱼数量上限；load_config 可能覆盖
        self._save_ticks = 0

        # 运行期数据目录（配置 / 日志）——发布包不含该目录，需在运行时确保存在
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
        except Exception:
            pass
        saved = self.load_config()
        # 依据屏幕设置计算鱼的游走边界（screen==-1 取虚拟桌面，否则取该屏工作区）
        self.apply_roam()
        L, T, R, B = self.roam  # 鱼在游走边界内生成/收拢
        if saved:
            for sp, scale, x, y, level, growth in saved:
                w, h = self._species_size(sp, scale)
                x = max(L, min(x, R - w))
                y = max(T, min(y, B - h))
                self.fishes.append(Fish(self, sp, scale, x, y, level, growth))
        if not self.fishes:  # 没有有效配置时给两条默认鱼
            cx, cy = (L + R) / 2, (T + B) / 2
            for i in range(2):
                sp = self.species_list[i % len(self.species_list)]
                self.fishes.append(Fish(self, sp, App.SCALES[0][1], cx - 160 + i * 320, cy))

        self.build_tray()
        # 鱼信息浮层（悬停显示），需在 build_tray 之后创建
        self.fish_info = FishInfoOverlay(self)
        # 普通模式的浮动文字浮层（繁殖提示等），需在 build_tray 之后创建
        self.floater_overlay = FloaterOverlay(self)
        # 上次若开启了鼠标穿透，则恢复窗口样式（鱼与信息卡整窗穿透）
        if self.mouse_penetration:
            self._apply_mouse_penetration()
        # 上次若在捕鱼模式，则自动恢复
        if getattr(self, "_restore_fishing", False):
            self.toggle_fishing()
        self.root.after(App.TICK_MS, self._loop)
        self.root.mainloop()

    # ---------- 配置持久化 ----------
    def _species_size(self, sp, scale):
        right, _ = species_frames(sp[1], scale)
        return right[0][1]

    def save_config(self):
        data = {"fish": [], "coins": self.coins, "cannon_level": self.cannon_level,
                "cannon": self.cannon_index, "sound": self.sound_enabled,
                "berserk": self.berserk_enabled, "fishing": self.fishing,
                "cross_screen": self.cross_screen, "screen": self.screen,
                "mouse_penetration": self.mouse_penetration,
                "max_fish": self.max_fish}
        for f in self.fishes:
            rel = os.path.relpath(f.species[1], FISH_ROOT)
            data["fish"].append({"path": rel, "scale": round(f.base_scale, 3),
                                 "level": f.level, "growth": round(f.growth, 3),
                                 "x": int(f.x), "y": int(f.y)})
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def load_config(self):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fp:
                data = json.load(fp)
        except Exception:
            return None
        by_path = {s[1]: s for s in self.species_list}
        out = []
        for item in data.get("fish", []):
            path = os.path.join(FISH_ROOT, item.get("path", ""))
            sp = by_path.get(path)
            if sp is None:
                continue
            scale = float(item.get("scale", 0.7))
            x = float(item.get("x", 0.0))
            y = float(item.get("y", 0.0))
            level = int(item.get("level", 1))
            growth = float(item.get("growth", 0.0))
            out.append((sp, scale, x, y, level, growth))
        # 金币与炮台等级持久化
        if isinstance(data.get("coins"), (int, float)):
            self.coins = int(data["coins"])
        if isinstance(data.get("cannon_level"), (int, float)):
            self.cannon_level = max(1, min(CANNON_MAX_LEVEL, int(data["cannon_level"])))
        if isinstance(data.get("cannon"), (int, float)):
            self.cannon_index = max(0, int(data["cannon"]))
        self.sound_enabled = bool(data.get("sound", True))
        self.sounds.enabled = self.sound_enabled
        self.berserk_enabled = bool(data.get("berserk", True))
        self._restore_fishing = bool(data.get("fishing", False))
        self.cross_screen = bool(data.get("cross_screen", True))
        if "screen" in data:  # 新配置：screen 为准，-1 即跨屏
            try:
                sc = int(data["screen"])
            except (TypeError, ValueError):
                sc = -1
            self.screen = sc
            self.cross_screen = (sc == -1)
        else:  # 旧配置无 screen 字段，由 cross_screen 推导
            self.screen = -1 if self.cross_screen else 0
        self.mouse_penetration = bool(data.get("mouse_penetration", False))
        if isinstance(data.get("max_fish"), (int, float)):
            self.max_fish = max(1, min(MAX_FISH_LIMIT, int(data["max_fish"])))
        return out or None

    def _fish_under_cursor(self):
        """返回鼠标当前所指的鱼（屏幕坐标命中检测），无则 None。
        用 GetCursorPos 轮询，不依赖 Tk 的 <Enter>/<Leave>（鱼窗口每帧移动，事件时序不可靠）。"""
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        sx, sy = pt.x, pt.y
        for f in self.fishes:
            if f.x <= sx <= f.x + f.w and f.y <= sy <= f.y + f.h:
                return f
        return None

    def _loop(self):
        dt = App.TICK_MS / 1000.0
        if not self.paused and not self.hidden:
            for f in self.fishes:
                f.tick(dt)
        if self.fishing and self.fishing_overlay is not None:
            self.fishing_overlay.tick(dt)
            if not self.fishes:  # 鱼被抓光了，自动补几条继续玩（按买价扣费，静默）
                self._spawn_fish(random.choice(self.species_list))
                self._spawn_fish(random.choice(self.species_list))
        if self.goldminer and self.goldminer_overlay is not None:
            self.goldminer_overlay.tick(dt)
            if not self.fishes:  # 鱼被钓光了，自动补几条继续玩
                self._spawn_fish(random.choice(self.species_list))
                self._spawn_fish(random.choice(self.species_list))
        if not self.fishing:
            # 捕鱼模式由叠加层画信息卡；普通/钓鱼模式用轮询命中检测驱动信息卡，
            # 不依赖 Tk 的 <Enter>/<Leave>（鱼窗口每帧 geometry 移动，Leave 事件时序不可靠，会立刻隐藏）
            if self.hidden:
                # 小鱼已隐藏：不再弹信息卡，把残留（含延迟中的）立刻收起
                self.fish_info.hide(immediate=True)
            else:
                hovered = self._fish_under_cursor()
                if hovered is not None:
                    self.fish_info.show(hovered)        # 指着鱼：显示并取消延迟隐藏
                elif self.fish_info.visible and self.fish_info._hide_at is None:
                    self.fish_info.hide()               # 离开鱼：仅挂一次延迟，不每帧重置（否则永不隐藏）
                self.fish_info.update()                 # 跟随鱼重绘；延迟到期则真正隐藏
        self.floater_overlay.update(dt)                 # 繁殖提示等浮动文字（到期自动清除）
        self._save_ticks += 1
        if self._save_ticks >= 180:  # 约每 6 秒自动存一次位置
            self._save_ticks = 0
            self.save_config()
        self.root.after(App.TICK_MS, self._loop)

    # ---------- 托盘 ----------
    def build_tray(self):
        try:
            icon_img = make_tray_icon()
        except Exception:
            icon_img = Image.new("RGBA", (64, 64), (0, 120, 215, 255))
        menu_items = [
            TrayItem(lambda item: "暂停游动" if not self.paused else "继续游动",
                     lambda icon, item: self._invoke(self.toggle_pause)),
            TrayItem("显示小鱼", lambda icon, item: self._invoke(self.toggle_hide),
                     checked=lambda item: not self.hidden),
            TrayItem("鱼池管理", TrayMenu(
                TrayItem("放一条小鱼", lambda icon, item: self._invoke(self.add_fish)),
                TrayItem("随机放几条鱼", lambda icon, item: self._invoke(self.add_fish_random)),
            )),
            TrayItem("捕鱼模式", lambda icon, item: self._invoke(self.toggle_fishing),
                     checked=lambda item: self.fishing),
            TrayItem("钓鱼模式", lambda icon, item: self._invoke(self.toggle_goldminer),
                     checked=lambda item: self.goldminer),
            TrayItem("鼠标穿透", lambda icon, item: self._invoke(self.toggle_mouse_penetration),
                     checked=lambda item: self.mouse_penetration),
            TrayItem("设置", lambda icon, item: self._invoke(self.open_settings)),
            TrayItem("商城", lambda icon, item: self._invoke(self.open_shop)),
            TrayItem("退出", lambda icon, item: self._invoke(self.quit)),
        ]
        menu = TrayMenu(*menu_items)
        self.tray = TrayIcon("desk_fish", icon_img, "桌面小鱼", menu)
        self.tray.run_detached()

    def _invoke(self, fn):
        """把托盘线程里的操作切回 tkinter 主线程执行。"""
        self.root.after(0, fn)

    def _pick_webview_screen(self, index):
        """返回 pywebview 的 Screen 对象，用于 create_window 的 screen 参数。

        pywebview（winforms 后端）会按该屏的「逻辑像素」把窗口居中，并自行处理
        DPI 缩放；若改用手动 window.move 传物理像素，会被二次缩放、把窗口甩到
        屏幕外（这就是之前窗口消失的原因）。index 取 App.screen（-1/0=主屏，
        >=1=指定显示器）；无匹配则回退主屏，再不行返回 None（pywebview 默认
        CenterScreen 仍居中于主屏）。
        """
        try:
            scr = webview.screens()
        except Exception:
            return None
        if not scr:
            return None
        mons = get_monitors()
        primary_rect = None
        target_rect = None
        for m in mons:
            if m["primary"]:
                primary_rect = m["rect"]
            if index is not None and index >= 0 and m["index"] == index:
                target_rect = m["rect"]
        if target_rect is None:
            target_rect = primary_rect

        def find(rect):
            if not rect:
                return None
            L, T, R, B = rect
            for s in scr:
                if (s.physical_x, s.physical_y,
                        s.physical_x + s.physical_width,
                        s.physical_y + s.physical_height) == (L, T, R, B):
                    return s
            return None

        return find(target_rect) or find(primary_rect)

    # ---------- 商城：HTML（pywebview） ----------
    def open_shop(self):
        """打开商城窗口（HTML 界面，由主线程的 pywebview 宿主渲染）。"""
        if webview is None:
            self._shop_fallback()
            return
        # 窗口已开：刷新数据并置顶
        win = getattr(self, "_shop_window", None)
        if win is not None and getattr(win, "_alive", False):
            try:
                win.evaluate_js("refreshShop(true)")
            except Exception:
                pass
            return

        api = ShopAPI(self)
        self._shop_api = api
        html = load_shop_html()
        w = webview.create_window(
            "商城", html=html, js_api=api,
            width=760, height=580, resizable=False, on_top=True,
            screen=self._pick_webview_screen(self.screen),
        )
        self._shop_window = w
        w._alive = True
        w.events.closed += lambda *a: self._on_shop_closed()

    def _on_shop_closed(self, *args):
        """商城窗口被关闭时，复位状态以便下次重新打开。"""
        w = getattr(self, "_shop_window", None)
        if w is not None:
            w._alive = False
        self._shop_window = None

    def _shop_fallback(self):
        """未安装 pywebview 时的降级提示。"""
        try:
            import tkinter.messagebox as mb
            mb.showinfo("商城",
                        "商城界面需要 pywebview 才能以网页形式打开。\n"
                        "请先安装依赖：pip install pywebview")
        except Exception:
            pass

    # ---------- 设置：HTML（pywebview） ----------
    def open_settings(self):
        """打开设置窗口（HTML 界面，由主线程的 pywebview 宿主渲染）。"""
        if webview is None:
            self._settings_fallback()
            return
        # 窗口已开：刷新数据并置顶
        win = getattr(self, "_settings_window", None)
        if win is not None and getattr(win, "_alive", False):
            try:
                win.evaluate_js("refreshSettings(true)")
            except Exception:
                pass
            return

        api = SettingsAPI(self)
        self._settings_api = api
        html = load_settings_html()
        w = webview.create_window(
            "设置", html=html, js_api=api,
            width=520, height=660, resizable=False, on_top=True,
            screen=self._pick_webview_screen(self.screen),
        )
        self._settings_window = w
        w._alive = True
        w.events.closed += lambda *a: self._on_settings_closed()

    def _on_settings_closed(self, *args):
        """设置窗口被关闭时，复位状态以便下次重新打开。"""
        w = getattr(self, "_settings_window", None)
        if w is not None:
            w._alive = False
        self._settings_window = None

    def _settings_fallback(self):
        """未安装 pywebview 时的降级提示。"""
        try:
            import tkinter.messagebox as mb
            mb.showinfo("设置",
                        "设置界面需要 pywebview 才能以网页形式打开。\n"
                        "请先安装依赖：pip install pywebview")
        except Exception:
            pass

    def toggle_pause(self):
        self.paused = not self.paused
        try:
            self.tray.update_menu()
        except Exception:
            pass

    def toggle_hide(self):
        self.hidden = not self.hidden
        flag = SW_HIDE if self.hidden else SW_SHOW
        for f in self.fishes:
            user32.ShowWindow(f.hwnd, flag)
            if not self.hidden:
                f.render()
        if self.hidden:
            # 信息卡是独立置顶窗口，不随鱼窗口隐藏，需立刻收起（含延迟中的）
            self.fish_info.hide(immediate=True)
        try:
            self.tray.update_menu()
        except Exception:
            pass

    def toggle_sound(self):
        self.sound_enabled = not self.sound_enabled
        self.sounds.enabled = self.sound_enabled
        if self.sound_enabled:
            self.sounds.play("poke")  # 开音效时给个反馈
        self.save_config()
        try:
            self.tray.update_menu()
        except Exception:
            pass

    def toggle_berserk(self):
        self.berserk_enabled = not self.berserk_enabled
        if not self.berserk_enabled:  # 关掉时立刻解除所有鱼的狂暴
            for f in self.fishes:
                f.berserk = False
                f.berserk_t = 0.0
        self.save_config()
        try:
            self.tray.update_menu()
        except Exception:
            pass

    # ---------- 开机自启 ----------
    def _autostart_command(self):
        """生成写入 Run 项的启动命令：优先用 pythonw 无控制台启动本脚本；
        打包成 exe（PyInstaller 等）时直接用 exe 自身。"""
        if getattr(sys, "frozen", False):
            return '"%s"' % sys.executable
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.isfile(pyw):
            pyw = sys.executable
        return '"%s" "%s"' % (pyw, os.path.abspath(__file__))

    def is_autostart_enabled(self):
        """读取 HKCU Run 项，判断是否已设置开机自启。"""
        if winreg is None:
            return False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as k:
                winreg.QueryValueEx(k, RUN_VALUE_NAME)
            return True
        except Exception:
            return False

    def set_autostart(self, on):
        """开/关开机自启：写入或删除 HKCU Run 项。返回是否成功。"""
        if winreg is None:
            return False
        try:
            k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH)
            try:
                if on:
                    winreg.SetValueEx(k, RUN_VALUE_NAME, 0, winreg.REG_SZ,
                                      self._autostart_command())
                else:
                    try:
                        winreg.DeleteValue(k, RUN_VALUE_NAME)
                    except FileNotFoundError:
                        pass
            finally:
                winreg.CloseKey(k)
            return True
        except Exception as e:
            print("[错误] 设置开机自启失败：%s" % e)
            return False

    def toggle_autostart(self):
        on = not self.is_autostart_enabled()
        if self.set_autostart(on):
            self.autostart_enabled = on
            if on:
                self.sounds.play("poke")  # 开自启时给个反馈
        try:
            self.tray.update_menu()
        except Exception:
            pass

    # ---------- 跨屏游走 / 屏幕选择 ----------
    def apply_roam(self):
        """按 screen 设置重算鱼的游走边界：
        screen==-1 取整个虚拟桌面（跨屏）；screen>=0 取该显示器工作区；其它回退主屏工作区。"""
        if self.cross_screen:
            self.roam = compute_roam_area(self.workarea)
        elif self.screen >= 0:
            rect = monitor_work_rect(self.screen)
            self.roam = rect if rect else self.workarea
        else:
            self.roam = self.workarea

    def toggle_cross_screen(self):
        self.cross_screen = not self.cross_screen
        self.screen = -1 if self.cross_screen else 0  # 关掉跨屏则收拢回主屏幕
        self.apply_roam()  # 关掉时 roam 收缩回主屏，鱼会在下一帧贴边收拢回来
        self.save_config()
        try:
            self.tray.update_menu()
        except Exception:
            pass

    def set_screen(self, idx):
        """选择鱼游走的屏幕：-1=全部屏幕（虚拟桌面），0..n-1=指定显示器；无效索引忽略。"""
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            return
        mons = get_monitors()
        if idx == -1:
            self.screen = -1  
            self.cross_screen = True
        elif 0 <= idx < len(mons):
            self.screen = idx
            self.cross_screen = False
        else:
            return  # 无效索引
        self.apply_roam()  # 鱼会在下一帧贴边收拢到新边界
        self.save_config()
        try:
            self.tray.update_menu()
        except Exception:
            pass

    def set_max_fish(self, n):
        """设置鱼数量上限（同时限制手动添加与自动繁殖）。"""
        self.max_fish = max(1, min(MAX_FISH_LIMIT, int(n)))
        self.save_config()
        try:
            self.tray.update_menu()
        except Exception:
            pass

    # ---------- 鼠标穿透 ----------
    def _set_ex_style(self, hwnd, style, on):
        """给指定窗口句柄增/删某个扩展样式位（on=True 增，False 删）。"""
        if not hwnd:
            return
        ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        ex = ex | style if on else ex & ~style
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex)

    def _apply_mouse_penetration(self):
        """把鼠标穿透样式套用到所有鱼窗口与信息卡窗口（穿透=整窗点击落到桌面）。"""
        for f in self.fishes:
            if getattr(f, "hwnd", None):
                self._set_ex_style(f.hwnd, WS_EX_TRANSPARENT, self.mouse_penetration)
        if getattr(self.fish_info, "hwnd", None):
            self._set_ex_style(self.fish_info.hwnd, WS_EX_TRANSPARENT, self.mouse_penetration)

    def toggle_mouse_penetration(self):
        self.mouse_penetration = not self.mouse_penetration
        self._apply_mouse_penetration()
        self.save_config()
        try:
            self.tray.update_menu()
        except Exception:
            pass

    def toggle_fishing(self):
        if self.fishing:
            self.fishing = False
            if self.fishing_overlay is not None:
                self.fishing_overlay.destroy()
                self.fishing_overlay = None
        else:
            if self.goldminer:  # 互斥：开炮台捕鱼前先关钓鱼模式
                self.toggle_goldminer()
            self.fishing = True
            self.fishing_overlay = FishingOverlay(self)
            self.fish_info.hide(immediate=True)  # 进捕鱼模式时收起普通信息卡（含延迟中的）
        try:
            self.tray.update_menu()
        except Exception:
            pass

    def toggle_goldminer(self):
        """钓鱼模式开关；与捕鱼模式互斥（同时只开一个叠加层）。"""
        if self.goldminer:
            self.goldminer = False
            if self.goldminer_overlay is not None:
                self.goldminer_overlay.destroy()
                self.goldminer_overlay = None
        else:
            if self.fishing:  # 互斥：开矿工前先关炮台捕鱼
                self.toggle_fishing()
            self.goldminer = True
            self.goldminer_overlay = GoldMinerOverlay(self)
            self.fish_info.hide(immediate=True)  # 进矿工模式时收起普通信息卡
        try:
            self.tray.update_menu()
        except Exception:
            pass

    # ---------- 菜单 ----------
    def show_menu(self, fish, event):
        menu = tk.Menu(self.root, tearoff=0)

        sp_menu = tk.Menu(menu, tearoff=0)
        for label, path in self.species_list:
            sp_menu.add_command(label=label,
                                command=lambda p=(label, path): self.set_species(fish, p))
        menu.add_cascade(label="更换品种", menu=sp_menu)

        sz_menu = tk.Menu(menu, tearoff=0)
        for label, s in App.SCALES:
            sz_menu.add_command(label=label, command=lambda v=s: self.set_scale(fish, v))
        menu.add_cascade(label="大小", menu=sz_menu)

        menu.add_separator()
        if fish.is_mature():
            menu.add_command(label="繁殖小鱼", command=lambda: self.breed_fish(fish))
        menu.add_command(label="放一条小鱼", command=self.add_fish)
        menu.add_command(label="随机放几条鱼", command=self.add_fish_random)
        if len(self.fishes) > 1:
            menu.add_command(label="移除这条鱼", command=lambda: self.remove_fish(fish))
        menu.add_separator()
        menu.add_command(label="退出", command=self.quit)
        menu.tk_popup(event.x_root, event.y_root)

    # ---------- 操作 ----------
    def add_fish(self):
        """手动放一条随机鱼：按商城买价扣金币；金币不足/鱼池满则提示音。"""
        sp = random.choice(self.species_list)
        fish = self._spawn_fish(sp, charge=True)
        if fish is None:
            self.sounds.play("error")
        return fish

    def add_fish_random(self):
        """随机放 2~5 条鱼：每条按商城买价扣费，钱不够或鱼池满即停。"""
        for _ in range(random.randint(2, 5)):
            if self._spawn_fish(random.choice(self.species_list), charge=True) is None:
                break

    def breed_fish(self, parent):
        """成年鱼繁殖小鱼（同品种、1 级、很小，出现在父鱼附近）。
        随机繁殖 1~4 条，仅受鱼池上限约束，自然繁殖不消耗金币。"""
        if len(self.fishes) >= self.max_fish:
            return None
        L, T, R, B = self.roam  # 鱼在虚拟桌面内生成/收拢（跨屏）
        baby_scale = App.SCALES[0][1]  # 很小
        w, h = self._species_size(parent.species, baby_scale)
        count = random.randint(1, 4)
        born = 0
        for _ in range(count):
            if len(self.fishes) >= self.max_fish:
                break
            cx = parent.x + parent.w / 2 + random.uniform(-90, 90)
            cy = parent.y + parent.h / 2 + random.uniform(-70, 70)
            bx = max(L, min(cx - w / 2, R - w))
            by = max(T, min(cy - h / 2, B - h))
            baby = Fish(self, parent.species, baby_scale, bx, by, level=1, growth=0.0)
            self.fishes.append(baby)
            born += 1
        if born == 0:
            return None
        self.sounds.play("birth")
        # 捕鱼模式与普通模式都给出繁殖提示：捕鱼模式弹在捕鱼浮层，普通模式弹在桌面主窗口
        floater = {
            "x": parent.x + parent.w / 2, "y": parent.y - 22,
            "text": "繁殖了%d条小鱼!" % born, "t": 0.0, "life": 1.2, "vy": 40,
            "color": (255, 205, 120)}
        if self.fishing_overlay is not None:
            self.fishing_overlay.floaters.append(floater)
        else:
            self.floaters.append(floater)
        self.save_config()
        return True

    def remove_fish(self, fish):
        if fish in self.fishes:
            self.fishes.remove(fish)
            self.fish_info.hide(fish, immediate=True)
            fish.destroy()
            self.save_config()

    # ---------- 放鱼（统一扣费入口） ----------
    def _spawn_fish(self, sp, scale=None, x=None, y=None, charge=True):
        """向鱼池放一条鱼的核心入口。charge=True 时按商城买价扣金币；
        金币不足或鱼池已满则返回 None（不扣费、不放鱼）。"""
        if len(self.fishes) >= self.max_fish:
            return None
        name = os.path.basename(sp[1])
        if charge:
            price = self.fish_buy_price(name)
            if self.coins < price:
                return None
            self.coins -= price
        if scale is None:
            scale = App.SCALES[0][1]
        if x is None or y is None:
            L, T, R, B = self.roam
            w, h = self._species_size(sp, scale)
            if x is None:
                x = random.uniform(L + 50, max(L + 51, R - w))
            if y is None:
                y = random.uniform(T + 50, max(T + 51, B - h))
        self.fishes.append(Fish(self, sp, scale, x, y))
        self.save_config()
        return self.fishes[-1]

    def add_fish_species(self, sp, scale=None):
        """购买指定品种的鱼并加入鱼池（商城调用，按买价扣费）。"""
        return self._spawn_fish(sp, scale=scale, charge=True)

    def fish_buy_price(self, name):
        """买鱼价格：鱼基础价值 × 倍数，下限 5。name 为鱼目录名。"""
        value = FISH_VALUE.get(name, (5, 0.25))[0]
        return max(5, int(value * FISH_BUY_MULT))

    def fish_sell_price(self, fish):
        """卖鱼返还：鱼基础价值 × 当前等级 × 比例。"""
        name = os.path.basename(fish.species[1])
        value = FISH_VALUE.get(name, (5, 0.25))[0]
        return max(5, int(value * fish.level * FISH_SELL_RATE))

    def _fish_info(self, fish):
        """返回鱼的基础价值与捕获率（与 FishingOverlay._fish_info 语义一致）。"""
        name = os.path.basename(fish.species[1])
        return FISH_VALUE.get(name, (5, 0.25))

    def sell_fish(self, fish):
        """出售一条鱼：移除并返还金币，返回返还数额。"""
        if fish not in self.fishes:
            return 0
        price = self.fish_sell_price(fish)
        self.coins += price
        self.remove_fish(fish)
        return price

    def cannon_upgrade_cost(self):
        """升到下一级所需金币。"""
        return CANNON_UPGRADE_BASE * self.cannon_level

    def upgrade_cannon(self):
        """升级炮台一级（扣除金币），成功返回 True。"""
        if self.cannon_level >= CANNON_MAX_LEVEL:
            return False
        cost = self.cannon_upgrade_cost()
        if self.coins < cost:
            return False
        self.coins -= cost
        self.cannon_level += 1
        self.save_config()
        return True

    def sell_cannon(self):
        """出售炮台：降级一级并返还部分金币，返回返还数额。"""
        if self.cannon_level <= 1:
            return 0
        refund = int(CANNON_UPGRADE_BASE * (self.cannon_level - 1) * CANNON_SELL_RATE)
        self.coins += refund
        self.cannon_level -= 1
        self.save_config()
        return refund

    # ---------- 鱼信息浮层 ----------
    def show_fish_info(self, fish):
        self.fish_info.show(fish)

    def hide_fish_info(self, fish):
        self.fish_info.hide(fish)

    def set_species(self, fish, species):
        fish.species = species
        self._reload(fish)
        self.save_config()

    def set_scale(self, fish, scale):
        fish.base_scale = scale
        self._reload(fish)
        self.save_config()

    def set_cannon(self, idx):
        """切换捕鱼炮台皮肤（索引从 0 起）。"""
        self.cannon_index = idx
        if self.fishing_overlay is not None:
            self.fishing_overlay.set_cannon(idx)
        self.save_config()
        try:
            self.tray.update_menu()
        except Exception:
            pass

    def _reload(self, fish):
        cx, cy = fish.x + fish.w / 2, fish.y + fish.h / 2
        fish._apply_scale()
        fish.x, fish.y = cx - fish.w / 2, cy - fish.h / 2
        fish.render()

    def quit(self):
        try:
            self.save_config()
        except Exception:
            pass
        try:
            if self.tray is not None:
                self.tray.stop()
        except Exception:
            pass
        for f in list(self.fishes):
            f.destroy()
        try:
            if getattr(self, "fish_info", None) is not None:
                self.fish_info.destroy()
        except Exception:
            pass
        try:
            if getattr(self, "floater_overlay", None) is not None:
                self.floater_overlay.destroy()
        except Exception:
            pass
        # 先关闭已打开的设置 / 商城窗口，避免退出时它们残留
        for name in ("_settings_window", "_shop_window"):
            w = getattr(self, name, None)
            if w is not None:
                try:
                    w.destroy()
                except Exception:
                    pass
        self.root.destroy()
        # 关闭 pywebview 宿主窗口，让主线程的 webview.start() 返回并退出进程
        try:
            if webview is not None:
                host = globals().get("WEBVIEW_HOST")
                if host is not None:
                    host.destroy()
        except Exception:
            pass


# ---------------------------------------------------------------- 商城 HTML 桥接
def load_shop_html():
    """读取商城页面（自包含的 HTML/CSS/JS）。"""
    path = os.path.join(HTML_DIR, "shop.html")
    with open(path, "r", encoding="utf-8") as fp:
        return fp.read()


class ShopAPI:
    """商城与前端 HTML/JS 的桥接层（pywebview 的 js_api）。
    所有读写都切回 tkinter 主线程执行，避免跨线程操作 Tk。"""

    def __init__(self, app):
        self.app = app

    def _run_on_main(self, fn):
        """在 tkinter 主线程执行 fn，等待完成并返回其结果。"""
        box, done = {}, threading.Event()

        def _task():
            try:
                box["r"] = fn()
            except Exception as e:  # noqa: BLE001
                box["r"] = {"ok": False, "msg": "操作失败：%s" % e}
            done.set()

        self.app.root.after(0, _task)
        done.wait()
        return box.get("r")

    # ---------- 只读：一次性取回全部数据 ----------
    def get_data(self):
        return self._run_on_main(self._collect)

    def _collect(self):
        import base64
        import io
        app = self.app

        gif_cache = {}

        def img_uri(path, height):
            """把单张 PNG 缩放到指定高度，返回 data URI（炮台等非帧序列素材用）。"""
            if not path or not os.path.isfile(path):
                return ""
            try:
                im = Image.open(path).convert("RGBA")
                if im.height > 0 and height:
                    scale = float(height) / im.height
                    im = im.resize((max(1, round(im.width * scale)), int(height)),
                                   Image.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, format="PNG")
                return "data:image/png;base64," + base64.b64encode(
                    buf.getvalue()).decode("ascii")
            except Exception:
                return ""

        def fish_gif(dir_path):
            """把鱼的 PNG 帧序列合成为一段循环 GIF（data URI），供前端 <img> 播放。
            鱼素材是 Resources/ 下的帧 PNG，需要合成 GIF 才能在前端动起来。"""
            if not dir_path:
                return ""
            if dir_path in gif_cache:
                return gif_cache[dir_path]
            uri = ""
            try:
                res = os.path.join(dir_path, "Resources")
                if os.path.isdir(res):
                    pairs = []
                    for f in os.listdir(res):
                        m = re.search(r"[_-](\d{2})\.png$", f, re.I)
                        if m:
                            pairs.append((int(m.group(1)), f))
                    pairs.sort()
                    if pairs:
                        imgs = []
                        for _, fn in pairs:
                            im = Image.open(os.path.join(res, fn)).convert("RGBA")
                            if im.height > 0:
                                scale = 56.0 / im.height
                                imgs.append(im.resize(
                                    (max(1, round(im.width * scale)), 56),
                                    Image.LANCZOS))
                        if imgs:
                            buf = io.BytesIO()
                            imgs[0].save(buf, format="GIF", save_all=True,
                                         append_images=imgs[1:], duration=80,
                                         loop=0, disposal=2)
                            uri = "data:image/gif;base64," + base64.b64encode(
                                buf.getvalue()).decode("ascii")
            except Exception:
                uri = ""
            gif_cache[dir_path] = uri
            return uri

        species = []
        for label, path in app.species_list:
            name = os.path.basename(path)
            species.append({"label": label, "path": path,
                            "price": app.fish_buy_price(name),
                            "gif": fish_gif(path)})
        # 出售列表只带品种序号（sp），GIF 由前端复用 species 数组里同一张。
        # 每条鱼都内嵌一份 GIF 会把 payload 撑爆：满鱼池（100 条）时 ~4.5MB，
        # pywebview 桥直接丢消息/不返回，商城整页空白（顶栏小请求轮询仍正常）。
        fishes = self._fishes_only()
        cannons = []
        cannon_paths = find_cannons()
        for i, cp in enumerate(cannon_paths):
            cannons.append({
                "index": i,
                "label": "炮台 %d" % (i + 1),
                "img": img_uri(cp, 56),          # 格子缩略图
                "big": img_uri(cp, 132),         # 炮台卡片大图预览
            })
        return {
            "coins": app.coins,
            "max_fish": app.max_fish,
            "fish_count": len(app.fishes),
            "cannon_level": app.cannon_level,
            "cannon_max": CANNON_MAX_LEVEL,
            "cannon_index": app.cannon_index,
            "cannon_count": len(cannon_paths),
            "cannon_img": (cannons[app.cannon_index]["big"]
                           if 0 <= app.cannon_index < len(cannons) else ""),
            "upgrade_cost": app.cannon_upgrade_cost(),
            "sell_cannon_refund": int(CANNON_UPGRADE_BASE
                                      * (app.cannon_level - 1)
                                      * CANNON_SELL_RATE),
            "species": species,
            "fishes": fishes,
            "cannons": cannons,
        }

    # ---------- 轻量状态（供前端定时轮询，避免每次重编码图片） ----------
    def get_status(self):
        """只返回易变的少量字段（金币、鱼池数量），供商城前端定时同步顶栏数字。

        完整 get_data 会重新合成 GIF/编码 PNG，开销大，不宜每秒轮询；这里只读
        标量，游戏内金币变动、鱼被捕获/新增时，商城顶栏能实时跟随。
        """
        return self._run_on_main(self._status)

    def _status(self):
        return {"coins": self.app.coins,
                "fish_count": len(self.app.fishes),
                "max_fish": self.app.max_fish}

    # ---------- 轻量鱼列表（供前端定时轮询，无 GIF、不重编码图片） ----------
    def get_fishes(self):
        """只返回鱼池列表（id/品种序号/名字/等级/售价），供出售页实时同步。

        完整 get_data 要合成 GIF/编码 PNG，开销大；这里只读标量，游戏内
        繁殖/捕获/出售导致鱼池变化时，商城出售页每秒就能跟上。
        """
        return self._run_on_main(self._fishes_only)

    def _fishes_only(self):
        """鱼池列表的公共构造：sp 为品种在 species_list 里的序号（前端据此
        复用 species 数组的 GIF），不内嵌任何图片。"""
        app = self.app
        sp_index = {path: i for i, (_lb, path) in enumerate(app.species_list)}
        return [{"id": id(f), "sp": sp_index.get(f.species[1], -1),
                 "label": f.species[0], "level": f.level,
                 "price": app.fish_sell_price(f)}
                for f in list(app.fishes)]

    # ---------- 写操作 ----------
    def buy(self, key, qty=1):
        return self._run_on_main(lambda: self._buy(key, qty))

    def _buy(self, key, qty=1):
        app = self.app
        sp = self._resolve_species(key)
        if sp is None:
            try:
                with open(os.path.join(DATA_DIR, "fish_pet_error.log"), "a",
                          encoding="utf-8") as fp:
                    fp.write("[buy] 找不到该鱼 key=%r species=%d\n"
                             % (key, len(app.species_list)))
            except Exception:
                pass
            return {"ok": False, "msg": "找不到该鱼", "bought": 0}
        try:
            qty = max(1, int(qty))
        except (TypeError, ValueError):
            qty = 1
        # add_fish_species 内部按买价扣费，金币不足/鱼池已满时返回 None
        bought = 0
        for _ in range(qty):
            if app.add_fish_species(sp) is None:
                break
            bought += 1
        if bought:
            app.sounds.play("poke")
            return {"ok": True, "msg": "成功购买 %d 条" % bought, "bought": bought}
        return {"ok": False, "msg": "金币不足或鱼池已满", "bought": 0}

    def _resolve_species(self, key):
        """把前端传来的 key 解析成 species_list 里的一条 (label, path)。

        前端优先传鱼种在 species 数组里的序号（与 species_list 同序），彻底避开
        把带反斜杠/中文的整条路径透传过 pywebview 桥可能带来的匹配失败；同时兼容
        直接传路径字符串的老调用（含分隔符被规范化的兜底）。
        """
        app = self.app
        sl = app.species_list
        # 数字：按序号定位（JS 数字过来可能是 int/float，极端情况下是数字字符串）
        if isinstance(key, str) and key.strip().isdigit():
            key = int(key.strip())
        if isinstance(key, bool):
            pass
        elif isinstance(key, (int, float)):
            i = int(key)
            if 0 <= i < len(sl):
                return sl[i]
            return None
        # 字符串：先精确路径匹配，再按分隔符归一 + basename 兜底
        if isinstance(key, str) and key:
            for s in sl:
                if s[1] == key:
                    return s
            base = os.path.basename(key.replace("/", "\\").rstrip("\\"))
            if base:
                for s in sl:
                    if os.path.basename(s[1]) == base:
                        return s
        return None

    def sell(self, fish_id):
        return self._run_on_main(lambda: self._sell(fish_id))

    def _sell(self, fish_id):
        app = self.app
        fish = next((f for f in app.fishes if id(f) == fish_id), None)
        if fish is None:
            return {"ok": False, "msg": "该鱼已不在鱼池"}
        app.sell_fish(fish)
        app.sounds.play("catch")
        return {"ok": True, "msg": "出售成功"}

    def sell_many(self, fish_ids):
        return self._run_on_main(lambda: self._sell_many(fish_ids))

    def _sell_many(self, fish_ids):
        """批量出售：传入鱼 id 列表，逐条出售并汇总返还金币。

        单条 sell 的批量版：id 解析失败的（已卖掉/已不在鱼池）跳过并在
        消息里注明，不影响其余鱼的成交。
        """
        app = self.app
        ids = list(fish_ids) if isinstance(fish_ids, (list, tuple)) \
            else [fish_ids]
        sold, gain, gone = 0, 0, 0
        for raw in ids:
            try:
                fid = int(raw)
            except (TypeError, ValueError):
                continue
            fish = next((f for f in app.fishes if id(f) == fid), None)
            if fish is None:
                gone += 1
                continue
            gain += app.sell_fish(fish)
            sold += 1
        if sold:
            app.sounds.play("catch")
            msg = "成功出售 %d 条，获得 %d 金币" % (sold, gain)
            if gone:
                msg += "（%d 条已不在鱼池）" % gone
            return {"ok": True, "msg": msg, "sold": sold, "gain": gain}
        return {"ok": False, "msg": "没有可出售的鱼", "sold": 0, "gain": 0}

    def upgrade(self):
        return self._run_on_main(self._upgrade)

    def _upgrade(self):
        app = self.app
        if app.cannon_level >= CANNON_MAX_LEVEL:
            return {"ok": False, "msg": "炮台已满级"}
        if app.coins < app.cannon_upgrade_cost():
            return {"ok": False, "msg": "金币不足"}
        app.upgrade_cannon()
        app.sounds.play("levelup")
        return {"ok": True, "msg": "升级成功"}

    def sell_cannon(self):
        return self._run_on_main(self._sell_cannon)

    def _sell_cannon(self):
        app = self.app
        refund = app.sell_cannon()
        if refund <= 0:
            return {"ok": False, "msg": "炮台已是最低等级"}
        app.sounds.play("catch")
        return {"ok": True, "msg": "出售成功，返还 %d 金币" % refund}

    def set_cannon(self, idx):
        return self._run_on_main(lambda: self._set_cannon(idx))

    def _set_cannon(self, idx):
        self.app.set_cannon(int(idx))
        return {"ok": True, "msg": "已切换炮台"}


# ---------------------------------------------------------------- 设置 HTML 桥接
def load_settings_html():
    """读取设置页面（自包含的 HTML/CSS/JS）。"""
    path = os.path.join(HTML_DIR, "settings.html")
    with open(path, "r", encoding="utf-8") as fp:
        return fp.read()


class SettingsAPI:
    """设置页与前端 HTML/JS 的桥接层（pywebview 的 js_api）。
    所有读写都切回 tkinter 主线程执行，避免跨线程操作 Tk。"""

    def __init__(self, app):
        self.app = app

    def _run_on_main(self, fn):
        """在 tkinter 主线程执行 fn，等待完成并返回其结果。"""
        box, done = {}, threading.Event()

        def _task():
            try:
                box["r"] = fn()
            except Exception as e:  # noqa: BLE001
                box["r"] = {"ok": False, "msg": "操作失败：%s" % e}
            done.set()

        self.app.root.after(0, _task)
        done.wait()
        return box.get("r")

    # ---------- 只读：一次性取回全部设置 ----------
    def get_settings(self):
        return self._run_on_main(self._collect)

    def _collect(self):
        app = self.app
        return {
            "coins": app.coins,
            "fish_count": len(app.fishes),
            "max_fish": app.max_fish,
            "max_fish_choices": list(MAX_FISH_CHOICES),
            "paused": app.paused,
            "show_fish": not app.hidden,
            "fishing": app.fishing,
            "goldminer": app.goldminer,
            "sound_enabled": app.sound_enabled,
            "autostart": app.is_autostart_enabled(),
            "cross_screen": app.cross_screen,
            "screen": app.screen,
            "monitors": get_monitors(),
            "mouse_penetration": app.mouse_penetration,
            "berserk_enabled": app.berserk_enabled,
            "cannon_index": app.cannon_index,
            "cannon_count": len(find_cannons()),
        }

    # ---------- 写操作 ----------
    def _toggle(self, name):
        getattr(self.app, name)()
        return {"ok": True, "msg": "已切换"}

    def toggle_pause(self):
        return self._run_on_main(lambda: self._toggle("toggle_pause"))

    def toggle_hide(self):
        return self._run_on_main(lambda: self._toggle("toggle_hide"))

    def toggle_fishing(self):
        return self._run_on_main(lambda: self._toggle("toggle_fishing"))

    def toggle_goldminer(self):
        return self._run_on_main(lambda: self._toggle("toggle_goldminer"))

    def toggle_sound(self):
        return self._run_on_main(lambda: self._toggle("toggle_sound"))

    def toggle_autostart(self):
        return self._run_on_main(lambda: self._toggle("toggle_autostart"))

    def toggle_cross_screen(self):
        return self._run_on_main(lambda: self._toggle("toggle_cross_screen"))

    def set_screen(self, idx):
        def _t():
            self.app.set_screen(int(idx))
            return {"ok": True, "msg": "已切换屏幕"}
        return self._run_on_main(_t)

    def toggle_mouse_penetration(self):
        return self._run_on_main(lambda: self._toggle("toggle_mouse_penetration"))

    def toggle_berserk(self):
        return self._run_on_main(lambda: self._toggle("toggle_berserk"))

    def set_max_fish(self, v):
        def _t():
            self.app.set_max_fish(int(v))
            return {"ok": True, "msg": "已设置上限 %d 条" % int(v)}
        return self._run_on_main(_t)

    def set_cannon(self, idx):
        def _t():
            self.app.set_cannon(int(idx))
            return {"ok": True, "msg": "已切换炮台"}
        return self._run_on_main(_t)

    def add_fish(self):
        def _t():
            before = len(self.app.fishes)
            self.app.add_fish()
            after = len(self.app.fishes)
            return {"ok": after > before,
                    "msg": "已添加小鱼" if after > before else "鱼池已满或金币不足"}
        return self._run_on_main(_t)

    def add_fish_random(self):
        def _t():
            before = len(self.app.fishes)
            self.app.add_fish_random()
            after = len(self.app.fishes)
            return {"ok": after > before,
                    "msg": ("已随机添加 %d 条" % (after - before))
                           if after > before else "鱼池已满或金币不足"}
        return self._run_on_main(_t)

    def quit(self):
        def _t():
            self.app.quit()
            return {"ok": True}
        return self._run_on_main(_t)


def _app_thread():
    """在后台线程运行 tkinter（建窗 + 主循环），主线程留给 pywebview。"""
    try:
        App()
    except Exception:
        import traceback
        traceback.print_exc()
        if sys.stdout is None:  # pythonw 下把错误写到文件，方便排查
            with open(os.path.join(DATA_DIR, "fish_pet_error.log"), "w", encoding="utf-8") as fp:
                traceback.print_exc(file=fp)
            # App 启动失败时销毁宿主窗口，避免主线程的 webview.start() 卡死
        try:
            host = globals().get("WEBVIEW_HOST")
            if host is not None:
                host.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    if webview is not None:
        # pywebview 必须在主线程启动；tkinter 改到后台线程运行。
        # 隐藏的宿主窗口让 webview.start() 持续阻塞、保持进程存活，
        # 退出时由 App.quit() 销毁它，主线程随之结束。
        WEBVIEW_HOST = webview.create_window(
            "host", html="<html><body></body></html>", hidden=True)
        threading.Thread(target=_app_thread, daemon=True).start()
        webview.start()
    else:
        try:
            App()
        except Exception:
            import traceback
            traceback.print_exc()
            if sys.stdout is None:  # pythonw 下把错误写到文件，方便排查
                with open(os.path.join(DATA_DIR, "fish_pet_error.log"), "w", encoding="utf-8") as fp:
                    traceback.print_exc(file=fp)
                input("按回车退出...")
