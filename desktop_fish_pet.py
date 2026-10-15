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
import json
import math
import os
import random
import re
import sys
from ctypes import wintypes

import tkinter as tk
from PIL import Image, ImageChops, ImageDraw
from pystray import Icon as TrayIcon, Menu as TrayMenu, MenuItem as TrayItem

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
ULW_ALPHA = 2
SPI_GETWORKAREA = 0x0030
GA_ROOT = 2


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
FISH_ROOT = os.path.join(BASE_DIR, "鱼")
GROUPS = ["新版鱼", "中型鱼"]
CONFIG_PATH = os.path.join(BASE_DIR, "fish_pet_config.json")

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


# ---------------------------------------------------------------- 小鱼窗口
class Fish:
    TICK_MS = 33

    def __init__(self, app, species, scale, x, y):
        self.app = app
        self.species = species
        self.scale = scale
        self.frame_ms = 90
        self.right, self.left = species_frames(species[1], scale)
        w, h = self.right[0][1]
        self.w, self.h = w, h
        self.x, self.y = float(x), float(y)
        self.base_speed = 60.0 * (0.5 + scale)
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

        self.win = tk.Toplevel(app.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="black")
        self.win.geometry(f"+{int(x)}+{int(y)}")
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
        self._make_dib(w, h)

        self._bind()
        self.render()

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

    def tick(self, dt):
        if self.mode == "drag":
            return
        wa = self.app.workarea
        L, T, R, B = wa
        anim_speed = 1.0
        if self.dart_t > 0:
            self.dart_t -= dt
            anim_speed = 3.0
        else:
            self.timer -= dt
            if self.timer <= 0:
                r = random.random()
                if r < 0.25:
                    self.mode = "idle"
                    self.timer = random.uniform(0.8, 2.0)
                elif r < 0.35:
                    ang = random.uniform(0, 2 * math.pi)
                    sp = self.base_speed * 3.5
                    self.vx = math.cos(ang) * sp
                    self.vy = math.sin(ang) * sp * 0.5
                    self.dart_t = random.uniform(0.5, 0.9)
                    self.mode = "swim"
                    self.timer = random.uniform(2.5, 6.0)
                else:
                    self.mode = "swim"
                    ang = random.uniform(0, 2 * math.pi)
                    sp = self.base_speed * random.uniform(0.6, 1.4)
                    self.vx = math.cos(ang) * sp
                    self.vy = math.sin(ang) * sp * 0.4
                    self.timer = random.uniform(2.5, 6.0)

        self.bob += dt * 3.0
        if self.mode == "swim":
            self.x += self.vx * dt
            self.y += self.vy * dt + math.sin(self.bob) * 12.0 * dt

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


# ---------------------------------------------------------------- 捕鱼叠加层
class FishingOverlay:
    """捕鱼模式：全屏透明叠加层 + 全局鼠标钩子，画出捕鱼枪并发射鱼叉。"""

    def __init__(self, app):
        self.app = app
        L, T, R, B = app.workarea
        self.L, self.T, self.W, self.H = L, T, R - L, B - T
        self.mx, self.my = self.W // 2, self.H // 2  # 鼠标（叠加层本地坐标）
        self.pending_fires = []
        self.bullets = []
        self.effects = []
        self.floaters = []  # 掉血/捕获浮动文字
        self.gun_len = 40
        self.gun_x, self.gun_y = self.W // 2, self.H - 40
        self.bullet_speed = 1500.0
        self.hud = (12, self.H - 78, 250, 66)  # 左下角信息面板
        try:
            self.font = ImageDraw.ImageFont.load_default()
        except Exception:
            self.font = None
        try:
            self.big_font = ImageDraw.ImageFont.load_default(size=30)
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
        self._render()

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

    def _render(self):
        self.draw.rectangle([0, 0, self.W, self.H], fill=(0, 0, 0, 0))
        dx = self.mx - self.gun_x
        dy = self.my - self.gun_y
        ang = math.atan2(dy, dx) if (dx or dy) else -math.pi / 2
        ex = self.gun_x + math.cos(ang) * self.gun_len
        ey = self.gun_y + math.sin(ang) * self.gun_len

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

        # 炮台（底部中央，跟随鼠标转向）
        self.draw.line([(self.gun_x, self.gun_y), (ex, ey)], fill=(150, 160, 170), width=16)
        self.draw.line([(self.gun_x, self.gun_y), (ex, ey)], fill=(90, 100, 110), width=7)
        self.draw.ellipse([self.gun_x - 26, self.gun_y - 26, self.gun_x + 26, self.gun_y + 26],
                          fill=(60, 70, 80))
        self.draw.ellipse([self.gun_x - 12, self.gun_y - 12, self.gun_x + 12, self.gun_y + 12],
                          fill=(30, 40, 50))
        self.draw.ellipse([ex - 7, ey - 7, ex + 7, ey + 7], fill=(220, 230, 240))

        # 鱼的血条（被打过才显示）
        for f in self.app.fishes:
            self._ensure_hp(f)
            if f.hp < f.max_hp:
                bx, by, bw, bh = f.x, f.y - 9, f.w, 5
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

        # 导出 BGRA（本叠加层无半透明像素，alpha 仅 0/255，无需预乘）
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

    def _draw_hud(self):
        x0, y0, w, h = self.hud
        self.draw.rectangle([x0, y0, x0 + w, y0 + h], fill=(20, 28, 48))
        self.draw.rectangle([x0, y0, x0 + w, y0 + h], outline=(120, 160, 220), width=2)
        coins = self.app.coins
        lv = self.app.cannon_level
        lines = [
            "GOLD: %d" % coins,
            "CANNON LV%d  x%d" % (lv, lv),
            "click panel = UPG (%d)" % (lv * 200),
        ]
        ty = y0 + 8
        for line in lines:
            if self.font:
                self.draw.text((x0 + 12, ty), line, fill=(235, 240, 255), font=self.font)
            else:
                self.draw.text((x0 + 12, ty), line, fill=(235, 240, 255))
            ty += 18

    # ---------- 逻辑 ----------
    _FISH_VALUE = {
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

    def _fish_info(self, fish):
        name = os.path.basename(fish.species[1])
        return self._FISH_VALUE.get(name, (5, 0.25))

    def tick(self, dt):
        for (sx, sy) in self.pending_fires:
            self._fire(sx, sy)
        self.pending_fires.clear()

        # 子弹推进 + 碰撞
        for b in list(self.bullets):
            b["x"] += b["vx"] * dt
            b["y"] += b["vy"] * dt
            b["life"] -= dt
            hit = None
            for f in self.app.fishes:
                cx = f.x + f.w / 2
                cy = f.y + f.h / 2
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
        x0 = self.gun_x + math.cos(ang) * self.gun_len
        y0 = self.gun_y + math.sin(ang) * self.gun_len
        lv = self.app.cannon_level
        self.app.coins = max(0, self.app.coins - lv)  # 发射消耗金币
        r = 3 + lv
        self.bullets.append({"x": x0, "y": y0,
                             "vx": math.cos(ang) * self.bullet_speed,
                             "vy": math.sin(ang) * self.bullet_speed,
                             "r": r, "life": 3.0})

    def _ensure_hp(self, fish):
        """懒初始化鱼的血量（金币倍率越高，血越厚）。"""
        if not getattr(fish, "max_hp_set", False):
            value, _ = self._fish_info(fish)
            fish.max_hp = value * 8
            fish.hp = fish.max_hp
            fish.max_hp_set = True

    def _impact(self, x, y, fish):
        self._ensure_hp(fish)
        lv = self.app.cannon_level
        value, _ = self._fish_info(fish)
        dmg = lv * 8  # 炮台等级越高，单发伤害越高
        fish.hp -= dmg
        # 掉血提示：在鱼身上方弹出伤害数字
        self.floaters.append({"x": fish.x + fish.w / 2, "y": fish.y - 6,
                              "text": "-%d" % dmg, "t": 0.0, "life": 0.8,
                              "vy": 55, "color": (255, 90, 60)})
        if fish.hp <= 0:
            reward = value * lv
            self.app.coins += reward
            self.app.remove_fish(fish)
            self.effects.append({"kind": "catch", "x": x, "y": y, "t": 0.0, "life": 0.5})
            self.floaters.append({"x": fish.x + fish.w / 2, "y": fish.y - 22,
                                  "text": "捕获 +%d" % reward, "t": 0.0, "life": 1.1,
                                  "vy": 45, "color": (120, 255, 120)})
            self.app.save_config()
        else:
            self.effects.append({"kind": "miss", "x": x, "y": y, "t": 0.0, "life": 0.25})

    def _try_upgrade(self):
        lv = self.app.cannon_level
        if lv >= 7:
            return
        cost = lv * 200
        if self.app.coins >= cost:
            self.app.coins -= cost
            self.app.cannon_level = lv + 1
            self.app.save_config()

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
                self.mx = hs.pt.x - self.L
                self.my = hs.pt.y - self.T
            elif wParam == WM_LBUTTONDOWN:
                lx = hs.pt.x - self.L
                ly = hs.pt.y - self.T
                hx0, hy0, hw, hh = self.hud
                if hx0 <= lx <= hx0 + hw and hy0 <= ly <= hy0 + hh:
                    self._try_upgrade()  # 点 HUD 面板 = 升级炮台
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


# ---------------------------------------------------------------- 应用
class App:
    TICK_MS = 33
    SCALES = [("小", 0.45), ("中", 0.70), ("大", 1.00)]

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
        self.paused = False
        self.hidden = False
        self.tray = None
        self.fishing = False
        self.fishing_overlay = None
        self.coins = 1000
        self.cannon_level = 1
        self._save_ticks = 0
        L, T, R, B = self.workarea

        saved = self.load_config()
        if saved:
            for sp, scale, x, y in saved:
                w, h = self._species_size(sp, scale)
                x = max(L, min(x, R - w))
                y = max(T, min(y, B - h))
                self.fishes.append(Fish(self, sp, scale, x, y))
        if not self.fishes:  # 没有有效配置时给两条默认鱼
            cx, cy = (L + R) / 2, (T + B) / 2
            for i in range(2):
                sp = self.species_list[i % len(self.species_list)]
                self.fishes.append(Fish(self, sp, 0.7, cx - 160 + i * 320, cy))

        self.build_tray()
        self.root.after(App.TICK_MS, self._loop)
        self.root.mainloop()

    # ---------- 配置持久化 ----------
    def _species_size(self, sp, scale):
        right, _ = species_frames(sp[1], scale)
        return right[0][1]

    def save_config(self):
        data = {"fish": [], "coins": self.coins, "cannon_level": self.cannon_level}
        for f in self.fishes:
            rel = os.path.relpath(f.species[1], FISH_ROOT)
            data["fish"].append({"path": rel, "scale": round(f.scale, 3),
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
            out.append((sp, scale, x, y))
        # 金币与炮台等级持久化
        if isinstance(data.get("coins"), (int, float)):
            self.coins = int(data["coins"])
        if isinstance(data.get("cannon_level"), (int, float)):
            self.cannon_level = max(1, min(7, int(data["cannon_level"])))
        return out or None

    def _loop(self):
        dt = App.TICK_MS / 1000.0
        if not self.paused and not self.hidden:
            for f in self.fishes:
                f.tick(dt)
        if self.fishing and self.fishing_overlay is not None:
            self.fishing_overlay.tick(dt)
            if not self.fishes:  # 鱼被抓光了，自动补几条继续玩
                self.add_fish()
                self.add_fish()
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
        menu = TrayMenu(
            TrayItem(lambda item: "暂停游动" if not self.paused else "继续游动",
                     lambda icon, item: self._invoke(self.toggle_pause)),
            TrayItem(lambda item: "收进托盘" if not self.hidden else "放出小鱼",
                     lambda icon, item: self._invoke(self.toggle_hide)),
            TrayItem(lambda item: "捕鱼模式" if not self.fishing else "退出捕鱼",
                     lambda icon, item: self._invoke(self.toggle_fishing)),
            TrayItem("添加一条小鱼", lambda icon, item: self._invoke(self.add_fish)),
            TrayItem("随机放几条鱼", lambda icon, item: self._invoke(self.add_fish_random)),
            TrayItem("退出", lambda icon, item: self._invoke(self.quit)),
        )
        self.tray = TrayIcon("desk_fish", icon_img, "桌面小鱼", menu)
        self.tray.run_detached()

    def _invoke(self, fn):
        """把托盘线程里的操作切回 tkinter 主线程执行。"""
        self.root.after(0, fn)

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
            self.fishing = True
            self.fishing_overlay = FishingOverlay(self)
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
        menu.add_command(label="再添一条小鱼", command=self.add_fish)
        menu.add_command(label="随机放几条鱼", command=self.add_fish_random)
        if len(self.fishes) > 1:
            menu.add_command(label="移除这条鱼", command=lambda: self.remove_fish(fish))
        menu.add_separator()
        menu.add_command(label="退出", command=self.quit)
        menu.tk_popup(event.x_root, event.y_root)

    # ---------- 操作 ----------
    def add_fish(self):
        L, T, R, B = self.workarea
        sp = random.choice(self.species_list)
        x = random.uniform(L + 50, max(L + 51, R - 350))
        y = random.uniform(T + 50, max(T + 51, B - 300))
        self.fishes.append(Fish(self, sp, 0.7, x, y))
        self.save_config()

    def add_fish_random(self):
        """一次性随机放 2~5 条鱼（随机品种、随机位置）。"""
        for _ in range(random.randint(2, 5)):
            self.add_fish()

    def remove_fish(self, fish):
        if fish in self.fishes:
            self.fishes.remove(fish)
            fish.destroy()
            self.save_config()

    def set_species(self, fish, species):
        fish.species = species
        self._reload(fish)
        self.save_config()

    def set_scale(self, fish, scale):
        fish.scale = scale
        self._reload(fish)
        self.save_config()

    def _reload(self, fish):
        cx, cy = fish.x + fish.w / 2, fish.y + fish.h / 2
        fish.right, fish.left = species_frames(fish.species[1], fish.scale)
        fish.frame = 0
        fish.anim_t = 0.0
        w, h = fish.right[0][1]
        fish.x, fish.y = cx - w / 2, cy - h / 2
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
        self.root.destroy()


if __name__ == "__main__":
    try:
        App()
    except Exception:
        import traceback
        traceback.print_exc()
        if sys.stdout is None:  # pythonw 下把错误写到文件，方便排查
            with open(os.path.join(BASE_DIR, "fish_pet_error.log"), "w", encoding="utf-8") as fp:
                traceback.print_exc(file=fp)
        input("按回车退出...")
