# -*- coding: utf-8 -*-
"""给 README 生成界面截图：逐页截取主窗口客户区，输出到 docs/screenshots/。

用法（在项目根目录）：
    venv\\Scripts\\python.exe tools\\capture_screenshots.py [--fast]

--fast  跳过耗时的真实扫描（硬件/驱动等），只等很短时间，图里数据会少一些

实现要点：
· 用 PrintWindow(flag=2) 逐窗口截图，而不是抓屏——抓屏会把桌面上其它窗口
  一起拍进来，或拍到尚未合成的中间态，看着像渲染 bug。
· 所有用户级落盘路径都指向临时目录：否则退出时 _save_geometry 会覆写用户
  真实的 ~/.unified_toolbox_settings.json。
· 截完统一缩放到统一宽度并优化压缩，避免仓库里堆几 MB 的图。
"""
import ctypes
import importlib.util
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
SRC = ROOT / "unified" / "unified.py"

FAST = "--fast" in sys.argv
TARGET_W = 1100          # 输出宽度，README 里够看清又能压得住体积

# --only <页面名> 只重拍某一页，避免为了改一个页面把其它页拍成低数据量的版本
ONLY = None
if "--only" in sys.argv:
    idx = sys.argv.index("--only")
    if idx + 1 < len(sys.argv):
        ONLY = sys.argv[idx + 1]

import win32gui
import win32ui
from PIL import Image

spec = importlib.util.spec_from_file_location("utb_shot", SRC)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.enable_dark_title_bar = lambda w: None
m.App._setup_tray_and_hotkey = lambda self: None

# 隔离用户数据：绝对不能碰真实的设置/历史文件
tmp = Path(tempfile.mkdtemp(prefix="utb_shot_"))
m.SETTINGS_FILE = tmp / "settings.json"
m.HISTORY_FILE = tmp / "history.json"
m.CLIP_IMG_DIR = tmp / "cache"
m.INDEX_FILE = tmp / "index.gz"
m.SNIPPETS_FILE = tmp / "snippets.json"
m.CleanupModule._CLEAN_LOG = tmp / "clean.log"
m.LAUNCH_FILE = tmp / "launch.json"

# 离线截图：不联网、不弹窗
for name in ("show_info", "show_warning", "show_error", "show_success"):
    setattr(m, name, lambda *a, **k: None)
m.ask_yesno = lambda *a, **k: False


def grab(win, dest):
    hwnd = int(win.winfo_id())
    l, t, r, b = win32gui.GetClientRect(hwnd)
    w, h = r - l, b - t
    hdc = win32gui.GetWindowDC(hwnd)
    src = win32ui.CreateDCFromHandle(hdc)
    dst = src.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(src, w, h)
    dst.SelectObject(bmp)
    ctypes.windll.user32.PrintWindow(hwnd, dst.GetSafeHdc(), 2)
    info = bmp.GetInfo()
    img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]),
                           bmp.GetBitmapBits(True), "raw", "BGRX", 0, 1)
    dst.DeleteDC()
    src.DeleteDC()
    win32gui.ReleaseDC(hwnd, hdc)
    win32gui.DeleteObject(bmp.GetHandle())

    if img.width > TARGET_W:
        img = img.resize((TARGET_W, round(img.height * TARGET_W / img.width)),
                         Image.LANCZOS)
    img.save(dest, optimize=True)
    return img.size


PAGES = [
    # 文件名用 ASCII：中文名在 Markdown 链接和 URL 里都要百分号编码，容易出岔子
    ("home", "01-home", 0),
    ("hardware", "02-hardware", 1),
    ("clipboard", "03-clipboard", 2),
    ("space", "04-space", 3),
    ("software", "05-software", 4),
    ("launch", "06-launch", 5),
    ("utility", "07-utility", 6),
    ("verify", "08-verify", 7),
]

OUT.mkdir(parents=True, exist_ok=True)
root = tk.Tk()
root.geometry("1100x900+40+20")
app = m.App(root)
root.update()

for name, label, _ in PAGES:
    if ONLY and ONLY not in (name, label):
        continue
    app._switch(name)
    # 给异步扫描留时间，图里才有真实数据
    wait = 0.6 if FAST else 6.0
    end = time.time() + wait
    while time.time() < end:
        root.update()
        time.sleep(0.02)
    dest = OUT / f"{label}.png"
    size = grab(root, dest)
    print(f"  {label:<12} {size[0]}x{size[1]}  {dest.stat().st_size/1024:.0f} KB")

app._quit_app()
try:
    if root.winfo_exists():     # _quit_app() 已经把 root 销毁了
        root.destroy()
except Exception:
    pass

total = sum(p.stat().st_size for p in OUT.glob("*.png"))
print(f"\n共 {len(list(OUT.glob('*.png')))} 张，合计 {total/1024:.0f} KB -> {OUT}")
