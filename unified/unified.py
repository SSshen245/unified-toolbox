"""统一工具箱 — 硬件诊断 + 剪贴板增强 + 磁盘清理 + 软件卸载 + 文件洞察 + 快速启动"""
import tkinter as tk
from tkinter import ttk
import threading, queue, time, os, sys, datetime, json, subprocess, re, platform
import fnmatch, hashlib, tempfile
import urllib.request, urllib.error
import ctypes, ctypes.wintypes
import psutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

APP_NAME = "统一工具箱"
APP_VERSION = "v3.9.1"

# 托盘支持（可选依赖：缺失时自动降级为普通窗口行为）
try:
    import pystray
    from PIL import Image as _PILImage, ImageDraw as _PILDraw, ImageTk as _PILImageTk
    from PIL import ImageGrab as _PILImageGrab
    TRAY_OK = True
except Exception:
    TRAY_OK = False

# —— 主题系统：多套配色风格，设置中心实时切换 ——
#    常量名（CYAN/PURPLE 等）沿用历史命名，仅在不同主题下映射到不同色值，
#    避免全文件替换；apply_theme() 启动时与切换时统一改写模块级常量 ——
THEMES = {
    "blue": {
        "label": "⚡ 电光蓝（默认）", "dark": True,
        "BG": "#0d1117", "PANEL": "#161b22", "PANEL2": "#1c2330", "PANEL3": "#242d3d",
        "BORDER": "#3d4a5f", "CYAN": "#0089e9", "PURPLE": "#00b4d8", "GREEN": "#2dd4a0",
        "YELLOW": "#e8c25a", "RED": "#ff5a5a", "ORANGE": "#ff8c42", "TEXT": "#e6edf5",
        "TEXT2": "#8b98ab", "MUTED": "#3d4a5f",
        "STRIP": ("#0089e9", "#3c61c1"),
    },
    "purple": {
        "label": "🌌 暗夜紫", "dark": True,
        "BG": "#0e0c14", "PANEL": "#171420", "PANEL2": "#1e1a2b", "PANEL3": "#292240",
        "BORDER": "#4a4066", "CYAN": "#a78bfa", "PURPLE": "#c084fc", "GREEN": "#34d399",
        "YELLOW": "#fbbf24", "RED": "#f87171", "ORANGE": "#fb923c", "TEXT": "#ece8f5",
        "TEXT2": "#a29bb8", "MUTED": "#4a4066",
        "STRIP": ("#a78bfa", "#5b3fa8"),
    },
    "emerald": {
        "label": "🌿 翡翠暗夜", "dark": True,
        "BG": "#0a100d", "PANEL": "#111a15", "PANEL2": "#16221b", "PANEL3": "#1e3024",
        "BORDER": "#3a5443", "CYAN": "#10b981", "PURPLE": "#2dd4bf", "GREEN": "#a3e635",
        "YELLOW": "#facc15", "RED": "#f87171", "ORANGE": "#fb923c", "TEXT": "#e7f2ea",
        "TEXT2": "#94a89c", "MUTED": "#3a5443",
        "STRIP": ("#10b981", "#0b5c45"),
    },
    "light": {
        "label": "☀ 极简白", "dark": False,
        "BG": "#f5f7fa", "PANEL": "#ffffff", "PANEL2": "#eef1f5", "PANEL3": "#e2e8f0",
        "BORDER": "#c3ccd8", "CYAN": "#0067c0", "PURPLE": "#7c3aed", "GREEN": "#0f9d6a",
        "YELLOW": "#b45309", "RED": "#dc2626", "ORANGE": "#ea580c", "TEXT": "#1a2330",
        "TEXT2": "#5a6a7e", "MUTED": "#9aa7b5",
        "STRIP": ("#0089e9", "#7ab8e8"),
    },
}
_THEME_KEYS = ("BG", "PANEL", "PANEL2", "PANEL3", "BORDER", "CYAN", "PURPLE",
               "GREEN", "YELLOW", "RED", "ORANGE", "TEXT", "TEXT2", "MUTED")
THEME_NAME = "blue"      # 当前主题 key
THEME_IS_DARK = True     # 当前主题是否深色（决定系统标题栏走向）

# 默认值先按电光蓝落位（apply_theme 会在启动时按设置覆盖）
BG = "#0d1117"; PANEL = "#161b22"; PANEL2 = "#1c2330"; PANEL3 = "#242d3d"
BORDER = "#3d4a5f"; CYAN = "#0089e9"; PURPLE = "#00b4d8"; GREEN = "#2dd4a0"
YELLOW = "#e8c25a"; RED = "#ff5a5a"; ORANGE = "#ff8c42"; TEXT = "#e6edf5"
TEXT2 = "#8b98ab"; MUTED = "#3d4a5f"
FONT_UI = "Microsoft YaHei UI"; FONT_MONO = "Consolas"
# 背景基色 RGB（渐变面积计算用）
BG_R, BG_G, BG_B = 0x0d, 0x11, 0x17


def apply_theme(name):
    """把指定主题的色值写入模块级常量（全局生效，控件在创建时读取）。"""
    global THEME_NAME, THEME_IS_DARK, BG_R, BG_G, BG_B
    t = THEMES.get(name) or THEMES["blue"]
    THEME_NAME = name if name in THEMES else "blue"
    g = globals()
    for k in _THEME_KEYS:
        g[k] = t[k]
    THEME_IS_DARK = bool(t.get("dark", True))
    BG_R, BG_G, BG_B = int(BG[1:3], 16), int(BG[3:5], 16), int(BG[5:7], 16)
    return t


HISTORY_FILE = Path.home() / ".unified_toolbox_history.json"
SETTINGS_FILE = Path.home() / ".unified_toolbox_settings.json"
CLIP_IMG_DIR = Path.home() / ".unified_toolbox_cache"

# 剪贴板图片缓存的合法文件名（_trim_cache / 清理 / 退出清空共用同一套白名单）
_CLIP_IMG_RE = re.compile(r"clip_[0-9a-f]{16,64}\.png")


def purge_clip_image_cache():
    """删除剪贴板图片缓存里由本程序写入的截图，返回删除数量。

    只认自己的 clip_<hex>.png 命名，不跟随符号链接、不碰目录里其它文件。
    用于「清理图片缓存」按钮和「退出时清空剪贴板历史」。
    """
    count = 0
    try:
        if not CLIP_IMG_DIR.exists():
            return 0
        for p in CLIP_IMG_DIR.glob("clip_*.png"):
            if p.is_symlink() or not _CLIP_IMG_RE.fullmatch(p.name):
                continue
            try:
                p.unlink()
                count += 1
            except OSError:
                pass
    except OSError:
        pass
    return count

# 全局设置（启动时读入，改动即时写盘）
DEFAULT_SETTINGS = {"hotkey_vk": "V", "close_action": "tray", "autostart": False,
                    "theme": "blue", "geometry": "",
                    # 剪贴板隐私：疑似密码/令牌跳过记录；退出时清空历史
                    "clip_skip_secrets": True, "clip_clear_on_exit": False,
                    # 界面语言："zh" 或 "en"（en 为部分覆盖：页签/托盘/设置）
                    "lang": "zh",
                    # 定时任务
                    "sch_clean_enabled": False, "sch_clean_hours": 168,
                    "sch_rest_enabled": False, "sch_rest_minutes": 45,
                    # 悬浮窗位置记忆（不在这里登记的键会被 load_settings 过滤掉）
                    "float_geo": "",
                    # 窗口状态：maximized = 上次退出时是否最大化；start_maximized =
                    # 用户明确要求"每次启动都最大化"（设置中心可勾）
                    "maximized": False, "start_maximized": False,
                    # 在线更新源 "owner/repo"，留空 = 不启用（见 UPDATE_REPO_DEFAULT）
                    "update_repo": ""}
SETTINGS = dict(DEFAULT_SETTINGS)


# ── 界面语言（轻量 i18n）：中文原文为 key，英文表覆盖；缺失则原样显示 ──
_STRINGS_EN = {
    "◈ 主题风格": "◈ Theme", "◈ 常规": "◈ General",
    "◈ 关闭主窗口时": "◈ When closing main window", "◈ 剪贴板": "◈ Clipboard",
    "◈ 定时任务": "◈ Scheduled tasks", "◈ 关于": "◈ About",
    "设置中心": "Settings", "保存": "Save", "取消": "Cancel",
    "最小化到系统托盘（推荐，可从托盘退出）": "Minimize to tray (recommended)",
    "直接退出程序": "Exit directly",
    "开机自动启动 统一工具箱": "Start 统一工具箱 at login",
    "🧹 清理图片缓存": "🧹 Clear image cache",
    "已保存": "Saved", "设置已保存并即时生效": "Settings saved and applied",
    " ⚡ 剪贴板 · 回车/双击=粘贴 · Esc=关闭 ": " ⚡ Clipboard · Enter/DblClick=Paste · Esc=Close ",
    "剪贴板快速面板": "Clipboard Quick Panel", "统一工具箱 已在运行": "统一工具箱 is already running",
    "退出": "Exit", "显示主窗口": "Show main window", "快速面板": "Quick Panel", "窗口置顶": "Always on Top",
    "剪贴板面板 (Ctrl+Alt+V)": "Clipboard Panel (Ctrl+Alt+V)",
    "窗口置顶 (Ctrl+Alt+T)": "Always on Top (Ctrl+Alt+T)", "设置": "Settings",
    "定时清理系统垃圾（静默执行，写审计日志）": "Scheduled junk cleanup (silent, audited)",
    "休息提醒（护眼）": "Rest reminder (eye care)",
    "疑似密码/令牌自动跳过记录（推荐）": "Skip passwords/tokens (recommended)",
    "退出时清空剪贴板历史": "Clear clipboard history on exit",
    "语言切换在重启后完全生效（当前为部分界面翻译）":
        "Language takes full effect after restart (partial translation)",
}


def T(text):
    """界面文本翻译：中文为基准；语言为 en 时查英文表，缺失则原样返回。"""
    if SETTINGS.get("lang") == "en":
        return _STRINGS_EN.get(text, text)
    return text



def _as_int(value, default, lo=None, hi=None):
    """把设置值稳妥地转成 int。

    设置文件是明文 JSON、用户可手改：null / "abc" / "" 都不该让程序崩。
    旧代码直接 int(SETTINGS.get(...))，一个 null 就会在 _schedule_tick 里抛错，
    而 30 秒定时器一旦抛错就再也排不上队，定时任务静默失效。
    """
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        n = int(default)
    if lo is not None and n < lo:
        n = lo
    if hi is not None and n > hi:
        n = hi
    return n


# ═══════════════════════════════════════════
# 在线更新（可选，默认关闭：填了更新源才生效）
# ═══════════════════════════════════════════
# 更新源填 "owner/repo"（GitHub 公开仓库）。
# 这里内置本项目自己的仓库，让发布出去的 exe 开箱即可「检查更新」；
# fork/二次分发的人改掉这行即可指向自己的仓库。
# 设置里的 update_repo 留空时会回落到这个内置值。
UPDATE_REPO_DEFAULT = "SSshen245/unified-toolbox"

# HTTP 头必须是 latin-1：这里**不能**用 APP_NAME（中文会让 urllib 直接抛
# "'latin-1' codec can't encode characters"）。用纯 ASCII 的 UA。
_UPDATE_UA = {"User-Agent": "UnifiedToolbox-UpdateCheck",
              "Accept": "application/vnd.github+json"}
_CHECK_CACHE = {"repo": None, "at": 0.0, "result": None}   # 查询结果缓存（10 分钟）


def version_key(v):
    """把 "v3.7" / "3.10.2" 这类版本串转成可比较的元组（按数字段比大小）。"""
    parts = re.findall(r"\d+", str(v or ""))
    return tuple(int(x) for x in parts[:4]) or (0,)


def fetch_latest_release(repo, timeout=15, use_cache=True):
    """查最新 Release，返回 (tag, 下载直链, 文件名, 错误串)。

    成功结果缓存 10 分钟：匿名接口每 IP 每小时只有 60 次，重复点按钮
    不该重复消耗额度。
    """
    global _CHECK_CACHE
    repo = (repo or "").strip().strip("/")
    now = time.time()
    if use_cache and _CHECK_CACHE["repo"] == repo and now - _CHECK_CACHE["at"] < 600:
        return _CHECK_CACHE["result"]
    spec_ = (repo or "").strip().strip("/")
    if not spec_:
        return None, None, None, "未配置更新源（需要填 owner/repo）"
    if spec_.lower().startswith("gitee:"):
        slug = spec_.split(":", 1)[1].strip("/")
        if "/" not in slug:
            return None, None, None, "Gitee 更新源格式应为 gitee:owner/repo"
        api = "https://gitee.com/api/v5/repos/%s/releases/latest" % slug
        # Gitee 的 browser_download_url 本身就在 gitee.com 上，可直连，无需特殊头
        headers = {"User-Agent": "UnifiedToolbox-UpdateCheck"}
        use_api_asset = False
        who = "Gitee"
    else:
        if "/" not in spec_:
            return None, None, None, "未配置更新源（需要填 owner/repo）"
        api = "https://api.github.com/repos/%s/releases/latest" % spec_
        headers = _UPDATE_UA
        use_api_asset = True
        who = "GitHub"
    try:
        req = urllib.request.Request(api, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, None, None, who + " 上找不到仓库，或该仓库还没有发布 Release"
        if e.code == 403:
            # 匿名接口每 IP 每小时 60 次；把恢复时间一并告诉用户
            reset = e.headers.get("X-RateLimit-Reset") if e.headers else None
            when = ""
            if reset and str(reset).isdigit():
                when = "，%s 自动恢复" % time.strftime("%H:%M", time.localtime(int(reset)))
            return None, None, None, ("GitHub 匿名接口达到限额（每 IP 每小时 60 次）%s；"
                                      "也可把更新源换成 gitee:owner/repo" % when)
        return None, None, None, who + " 返回 HTTP %s" % e.code
    except Exception as e:
        return None, None, None, "网络错误（%s）：%s" % (who, e)

    tag = data.get("tag_name") or ""
    assets = data.get("assets") or []
    pick = next((a for a in assets
                 if str(a.get("name", "")).lower().endswith(".exe")), None)
    pick = pick or (assets[0] if assets else None)
    if not pick:
        return tag, None, None, "该 Release 没有上传任何文件（需要把 exe 作为附件上传）"
    # GitHub 优先用 API 的 asset 端点（配 Accept: application/octet-stream）下载，而不是
    # browser_download_url：后者指向 github.com，在 github.com 不可达的网络里
    # （实测：代理只放行 API/资产域时）会直接超时；而 API 端点会 302 到
    # release-assets.githubusercontent.com，同一条网络下依然能下。
    url = pick.get("browser_download_url")
    if use_api_asset:
        url = pick.get("url") or url
    result = (tag, url, pick.get("name"), None)
    _CHECK_CACHE.update(repo=spec_, at=time.time(), result=result)
    return result


def download_update(url, dest, progress=None, timeout=300):
    """下载更新包到 dest。progress(done, total) 报进度。返回错误串或 ""。

    Accept 必须是 application/octet-stream：asset 端点靠这个头才会返回文件
    本体（否则返回 JSON 元数据），随后 302 到资产 CDN。
    """
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "UnifiedToolbox-UpdateCheck",
            "Accept": "application/octet-stream"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        return ""
    except Exception as e:
        try:
            Path(dest).unlink(missing_ok=True)
        except Exception:
            pass
        return "下载失败：%s" % e


# 自替换批处理：内容刻意保持纯 ASCII —— 中文路径通过 %~1/%~2 以参数传入，
# 避免 cmd.exe 按 OEM 代码页读 .cmd 文件时把路径读坏。
# 单文件版 PyInstaller 有“引导器+主体”两个进程，主体退出后引导器仍会短暂
# 占用 exe 文件：所以要等“所有同名 exe 进程”退出，且 copy 失败必须重试
# （实测：只等当前 PID + copy 一次，单文件版会复制失败且不留任何提示）。
_UPDATE_SWAPPER = """@echo off
setlocal
:wait
tasklist /FI "IMAGENAME eq %~nx2" 2>nul | find /I "%~nx2" >nul
if not errorlevel 1 (
  ping -n 2 127.0.0.1 >nul
  goto wait
)
set /a TRIES=0
:copy
copy /y "%~1" "%~2" >nul
if not errorlevel 1 goto run
set /a TRIES+=1
if %TRIES% GEQ 20 (
  echo %DATE% %TIME% replace failed: target locked> "%~dp1utb_update_error.txt"
  exit /b 1
)
ping -n 3 127.0.0.1 >nul
goto copy
:run
del "%~1" >nul 2>&1
rem wait a beat: the old instance's singleton mutex is released
rem a moment later than the process vanishing from tasklist
ping -n 3 127.0.0.1 >nul
start "" "%~2" --after-update
rem (goto) idiom: a running .cmd cannot del itself directly
(goto) 2>nul & del "%~f0" >nul 2>&1
"""


def write_update_swapper():
    """生成"等本进程退出后替换 exe 并重启"的批处理，返回其路径。

    正在运行的 exe 无法覆盖自己（文件被占用），所以必须先下载到别处、
    等退出后再替换 —— 这是 Windows 上自更新的通用做法。
    注意行尾必须是 CRLF：cmd.exe 对 LF-only 的批处理（goto/括号块）行为不可靠。
    """
    script = Path(tempfile.gettempdir()) / "utb_apply_update.cmd"
    script.write_bytes(_UPDATE_SWAPPER.replace("\n", "\r\n").encode("ascii"))
    return script


def load_settings():
    global SETTINGS
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            SETTINGS.update({k: data[k] for k in DEFAULT_SETTINGS if k in data})
    except Exception:
        pass
    return SETTINGS


def save_settings():
    try:
        tmp = SETTINGS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(SETTINGS, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(SETTINGS_FILE)
    except Exception:
        pass


load_settings()
# 恢复自定义配色（若存在），否则 theme=custom 会回落到 blue
try:
    _ctf = Path.home() / ".unified_toolbox_theme_custom.json"
    if SETTINGS.get("theme") == "custom" and _ctf.exists():
        _ct = json.loads(_ctf.read_text(encoding="utf-8"))
        if isinstance(_ct, dict) and all(k in _ct for k in _THEME_KEYS):
            _ct.setdefault("dark", True)
            _ct.setdefault("label", "🎨 自定义")
            _ct.setdefault("STRIP", (_ct["CYAN"], _ct["BORDER"]))
            THEMES["custom"] = {k: _ct[k] for k in
                                list(_THEME_KEYS) + ["dark", "label", "STRIP"] if k in _ct}
except Exception:
    pass
apply_theme(SETTINGS.get("theme", "blue"))   # 启动即应用已保存的主题


def get_autostart():
    """工具箱自身是否已设开机自启（HKCU Run）"""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run") as k:
            winreg.QueryValueEx(k, "UnifiedToolbox")
            return True
    except OSError:
        return False


def set_autostart(enable):
    """开关工具箱自身开机自启（仅 HKCU，无需管理员）"""
    import winreg
    try:
        if enable:
            if getattr(sys, "frozen", False):
                cmd = f'"{sys.executable}"'
            else:
                pw = Path(sys.executable).with_name("pythonw.exe")
                script = Path(__file__).resolve()
                cmd = f'"{pw}" "{script}"'
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
                                0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, "UnifiedToolbox", 0, winreg.REG_SZ, cmd)
        else:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
                                0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, "UnifiedToolbox")
        SETTINGS["autostart"] = bool(enable)
        save_settings()
        return True, ""
    except Exception as e:
        return False, str(e)


# ═══════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════

NL = chr(10)   # 换行（补丁拼接消息用，避免字面转义被工具链改写）


def page_header(parent, text, sub, color):
    """合并模块页统一页头：主标题 + 流程说明（子区块标题带 ①②③ 序号）。"""
    top = tk.Frame(parent, bg=PANEL)
    top.pack(fill="x", padx=20, pady=(12, 8))
    tk.Label(top, text=text, bg=PANEL, fg=color,
             font=(FONT_UI, 13, "bold")).pack(anchor="w", pady=(6, 0))
    tk.Label(top, text=sub, bg=PANEL, fg=TEXT2, font=(FONT_UI, 8)).pack(anchor="w")
    return top


def kb(n):
    if abs(n) >= 1024**3: return f"{n/1024**3:.1f}G"
    if abs(n) >= 1024**2: return f"{n/1024**2:.1f}M"
    if abs(n) >= 1024: return f"{n/1024:.1f}K"
    return f"{n:.0f}B"


def _center_on(child, parent=None, y_ratio=3):
    """把 child 窗口摆到 parent 中间（越界收敛到屏幕内）。

    parent 为 None 时按屏幕居中。这个"居中 + 夹取"的逻辑原先在十几个弹窗里
    各抄了一遍，收敛成一个函数，新弹窗直接用。
    """
    try:
        child.update_idletasks()
        w, h = child.winfo_width(), child.winfo_height()
        sw, sh = child.winfo_screenwidth(), child.winfo_screenheight()
        if parent is not None:
            x = parent.winfo_x() + (parent.winfo_width() - w) // 2
            y = parent.winfo_y() + (parent.winfo_height() - h) // max(1, y_ratio)
        else:
            x, y = (sw - w) // 2, (sh - h) // 3
        x = max(0, min(x, sw - w - 8))
        y = max(0, min(y, sh - h - 36))
        child.geometry("+%d+%d" % (x, y))
    except Exception:
        pass


def parse_size(s):
    """'1.2G'/'900.0M'/'512.0K'/'123B' → 字节数（表格数值排序用）"""
    try:
        m = re.match(r"([\d.]+)\s*([KMG])", str(s).strip().upper())
        if not m: return 0.0
        mult = {"K": 1024, "M": 1024**2, "G": 1024**3}[m.group(2)]
        return float(m.group(1)) * mult
    except Exception:
        return 0.0


def delete_to_recycle_bin(paths):
    """批量删除到 Windows 回收站（SHFileOperationW + FOF_ALLOWUNDO，可恢复）。
    返回 (是否全部成功, 被用户中止与否)。"""
    if not paths:
        return True, False

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", ctypes.c_void_p), ("wFunc", ctypes.c_uint),
                    ("pFrom", ctypes.c_void_p), ("pTo", ctypes.c_void_p),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", ctypes.c_int),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.c_wchar_p)]

    try:
        # pFrom 需要双 \0 结尾的多串；c_wchar_p 会在首个 \0 截断，必须传缓冲区指针
        buf = ctypes.create_unicode_buffer("\0".join(paths) + "\0\0")
        op = SHFILEOPSTRUCTW()
        op.hwnd = None
        op.wFunc = 3  # FO_DELETE
        op.pFrom = ctypes.cast(buf, ctypes.c_void_p)
        op.pTo = None
        # FOF_ALLOWUNDO(0x40) | FOF_NOCONFIRMATION(0x10) | FOF_SILENT(0x4) | FOF_NOERRORUI(0x400)
        op.fFlags = 0x40 | 0x10 | 0x4 | 0x400
        ret = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return ret == 0 and not op.fAnyOperationsAborted, bool(op.fAnyOperationsAborted)
    except Exception:
        return False, False


def clip_get_text():
    """跨线程安全的剪贴板读取（ctypes Win32，不依赖 Tk 主线程）
    注意：64位下必须显式设置 restype/argtypes，否则句柄被截断为32位导致段错误"""
    try:
        CF_UNICODETEXT = 13
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        u32.OpenClipboard.restype = ctypes.c_int
        u32.GetClipboardData.restype = ctypes.c_void_p
        u32.GetClipboardData.argtypes = [ctypes.c_uint]
        k32.GlobalLock.restype = ctypes.c_void_p
        k32.GlobalLock.argtypes = [ctypes.c_void_p]
        k32.GlobalUnlock.restype = ctypes.c_int
        k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        if not u32.OpenClipboard(None): return ""
        try:
            h = u32.GetClipboardData(CF_UNICODETEXT)
            if not h: return ""
            locked = k32.GlobalLock(ctypes.c_void_p(h))
            if not locked: return ""
            try:
                return ctypes.c_wchar_p(locked).value or ""
            finally:
                k32.GlobalUnlock(ctypes.c_void_p(locked))
        finally:
            u32.CloseClipboard()
    except Exception:
        return ""


def clip_get_dib():
    """读取剪贴板 CF_DIB 原始位图字节（无图返回 None）——供图片历史使用"""
    try:
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        u32.OpenClipboard.restype = ctypes.c_int
        u32.GetClipboardData.restype = ctypes.c_void_p
        u32.GetClipboardData.argtypes = [ctypes.c_uint]
        k32.GlobalLock.restype = ctypes.c_void_p
        k32.GlobalLock.argtypes = [ctypes.c_void_p]
        k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        k32.GlobalSize.restype = ctypes.c_size_t
        k32.GlobalSize.argtypes = [ctypes.c_void_p]
        if not u32.OpenClipboard(None):
            return None
        try:
            h = u32.GetClipboardData(8)  # CF_DIB
            if not h:
                return None
            size = k32.GlobalSize(h)
            p = k32.GlobalLock(h)
            if not p or not size:
                return None
            try:
                return ctypes.string_at(p, size)
            finally:
                k32.GlobalUnlock(h)
        finally:
            u32.CloseClipboard()
    except Exception:
        return None


def dib_to_pil(dib):
    """DIB 字节 → PIL.Image（支持 24/32bpp 非压缩；异常返回 None）"""
    if not dib or not TRAY_OK or len(dib) < 40:
        return None
    import struct
    try:
        hdr = struct.unpack("<I", dib[:4])[0]
        w, h = struct.unpack("<ii", dib[4:12])
        bpp = struct.unpack("<H", dib[14:16])[0]
        compress = struct.unpack("<I", dib[16:20])[0]
        if bpp not in (24, 32) or compress != 0 or w <= 0 or w > 12000 or h == 0 or abs(h) > 12000:
            return None
        top_down = h < 0
        h = abs(h)
        stride = (w * (bpp // 8) + 3) // 4 * 4
        if len(dib) < hdr + stride * h:
            return None
        body = dib[hdr:hdr + stride * h]
        px = bpp // 8
        rows = [body[y * stride: y * stride + w * px] for y in range(h)]
        if not top_down:
            rows.reverse()
        packed = b"".join(rows)
        # BGR/BGRA 只是 raw 解码器的 rawmode，不是 PIL 标准 mode——
        # 必须用 frombytes(mode, size, data, "raw", rawmode) 四参形式
        if bpp == 32:
            img = _PILImage.frombytes("RGBA", (w, h), packed, "raw", "BGRA")
        else:
            img = _PILImage.frombytes("RGB", (w, h), packed, "raw", "BGR")
        return img.convert("RGB")
    except Exception:
        return None


def _pil_to_dib(img):
    """PIL.Image → 32bpp CF_DIB 字节（bottom-up，供写回剪贴板）"""
    import struct
    w, h = img.size
    rgba = img.convert("RGBA")
    stride = w * 4
    data = rgba.tobytes("raw", "BGRA")
    rows = [data[y * stride: (y + 1) * stride] for y in range(h)]
    body = b"".join(reversed(rows))
    header = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 32, 0, len(body), 0, 0, 0, 0)
    return header + body


_ICON_CACHE = {}     # (path_lower, size) -> PIL.Image RGBA（None=提取失败，也缓存防重试）
_PHOTO_CACHE = {}    # (path_lower, size) -> tk.PhotoImage（必须在 UI 线程创建且持有引用）


def _exe_path_from_cmd(val):
    """从启动项命令行提取可执行文件路径（剥引号/参数/环境变量）"""
    v = os.path.expandvars(str(val).strip())
    if v.lower().startswith("rundll32") or v.lower().startswith("regsvr32"):
        return ""
    if v.startswith('"'):
        p = v.split('"')[1] if '"' in v[1:] else v.strip('"')
    else:
        # 无引号路径：按常见参数分隔符切（" -"、" /"、" --"）
        for sep in (" -", " /", " --"):
            if sep in v:
                v = v.split(sep)[0]
        p = v.strip()
    return p if p.lower().endswith((".exe", ".lnk", ".dll")) else ""


def get_file_icon_img(path, size=28):
    """提取文件/.lnk 的显示图标 → PIL RGBA（shell 负责解析 lnk 目标图标）。
    失败返回 None（结果缓存，避免重复打开 GDI 句柄）。"""
    key = (str(path).lower(), size)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    img = None
    if TRAY_OK and path and Path(path).is_file():
        try:
            SHGFI_ICON, SHGFI_LARGEICON = 0x100, 0x0

            class SHFILEINFOW(ctypes.Structure):
                _fields_ = [("hIcon", ctypes.c_void_p), ("iIcon", ctypes.c_int),
                            ("dwAttributes", ctypes.c_uint),
                            ("szDisplayName", ctypes.c_wchar * 260),
                            ("szTypeName", ctypes.c_wchar * 80)]
            shfi = SHFILEINFOW()
            if ctypes.windll.shell32.SHGetFileInfoW(str(path), 0, ctypes.byref(shfi),
                                                    ctypes.sizeof(shfi),
                                                    SHGFI_ICON | SHGFI_LARGEICON) and shfi.hIcon:
                hico = shfi.hIcon
                u32, g32 = ctypes.windll.user32, ctypes.windll.gdi32
                hdc = u32.GetDC(None)
                mdc = g32.CreateCompatibleDC(hdc)

                class BMIH(ctypes.Structure):
                    _fields_ = [("biSize", ctypes.c_uint), ("biWidth", ctypes.c_int),
                                ("biHeight", ctypes.c_int), ("biPlanes", ctypes.c_ushort),
                                ("biBitCount", ctypes.c_ushort), ("biCompression", ctypes.c_uint),
                                ("biSizeImage", ctypes.c_uint), ("biXPelsPerMeter", ctypes.c_int),
                                ("biYPelsPerMeter", ctypes.c_int), ("biClrUsed", ctypes.c_uint),
                                ("biClrImportant", ctypes.c_uint)]
                bi = BMIH(ctypes.sizeof(BMIH), size, -size, 1, 32, 0, 0, 0, 0, 0, 0)
                pv = ctypes.c_void_p()
                hbmp = g32.CreateDIBSection(hdc, ctypes.byref(bi), 0, ctypes.byref(pv), None, 0)
                if hbmp and pv:
                    old = g32.SelectObject(mdc, hbmp)
                    u32.DrawIconEx(mdc, 0, 0, hico, size, size, 0, None, 0x0003)  # DI_NORMAL
                    buf = ctypes.string_at(pv, size * size * 4)
                    g32.SelectObject(mdc, old)
                    g32.DeleteObject(hbmp)
                    img = _PILImage.frombytes("RGBA", (size, size), buf, "raw", "BGRA")
                g32.DeleteDC(mdc)
                u32.ReleaseDC(None, hdc)
                u32.DestroyIcon(hico)
        except Exception:
            img = None
    _ICON_CACHE[key] = img
    return img


_EXE_PUB_CACHE = {}   # exe 路径小写 -> CompanyName（"" 也缓存防重试）


def get_exe_company(path):
    """读 exe 版本资源的 CompanyName——控制面板「发布者」列的同款兜底
    （现代安装器大多不写注册表 DisplayPublisher，只能从文件元数据拿）。
    无 Tk/GDI 依赖，可后台线程调用。"""
    if not path:
        return ""
    key = str(path).lower()
    if key in _EXE_PUB_CACHE:
        return _EXE_PUB_CACHE[key]
    company = ""
    try:
        ver = ctypes.windll.version
        size = ver.GetFileVersionInfoSizeW(str(path), None)
        if size:
            data = ctypes.create_string_buffer(size)
            if ver.GetFileVersionInfoW(str(path), 0, size, data):
                val = ctypes.c_wchar_p()
                n = ctypes.c_uint()
                # 常见语言代码页：英文标准/中文/中性
                for lang in ("040904b0", "080404b0", "000004b0", "040904e4"):
                    if ver.VerQueryValueW(data, "\\StringFileInfo\\" + lang + "\\CompanyName",
                                          ctypes.byref(val), ctypes.byref(n)) and val.value:
                        company = val.value
                        break
    except Exception:
        company = ""
    _EXE_PUB_CACHE[key] = company
    return company


def put_image_to_clipboard(img):
    """把 PIL 图片写入剪贴板（CF_DIB），供图片条目"复制"使用"""
    try:
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        if not u32.OpenClipboard(None):
            return False
        try:
            u32.EmptyClipboard()
            dib = _pil_to_dib(img)
            k32.GlobalAlloc.restype = ctypes.c_void_p
            k32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
            k32.GlobalLock.restype = ctypes.c_void_p
            k32.GlobalLock.argtypes = [ctypes.c_void_p]
            k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            u32.SetClipboardData.restype = ctypes.c_void_p
            u32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
            h = k32.GlobalAlloc(0x0002, len(dib))  # GMEM_MOVEABLE
            if not h:
                return False
            p = k32.GlobalLock(h)
            if not p:
                return False
            ctypes.memmove(p, dib, len(dib))
            k32.GlobalUnlock(h)
            # SetClipboardData 接管 h 的所有权，不再释放
            return bool(u32.SetClipboardData(8, h))  # CF_DIB
        finally:
            u32.CloseClipboard()
    except Exception:
        return False


def uuid4_str():
    import uuid
    return uuid.uuid4().hex


def enable_dark_title_bar(root):
    """让系统标题栏跟随主题（深色主题→深色标题栏，浅色主题→浅色标题栏），
    Win10 2004+/Win11；顺带开启 Win11 圆角窗口"""
    try:
        root.update_idletasks()
        GA_ROOT = 2
        hwnd = ctypes.windll.user32.GetAncestor(root.winfo_id(), GA_ROOT)
        if not hwnd:
            return
        val = ctypes.c_int(1 if THEME_IS_DARK else 0)
        for attr in (20, 19):  # 20=新命名，19=旧版本号
            r = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
            if r == 0:
                break
        # Win11 圆角窗口（33=DWMWA_WINDOW_CORNER_PREFERENCE, 2=ROUND）
        corner = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))
    except Exception:
        pass


def toggle_pin_hwnd(hwnd):
    """切换指定窗口的置顶状态（官方 SetWindowPos TOPMOST/NOTOPMOST）。
    置顶状态以窗口当前 WS_EX_TOPMOST 位为准（即使用户手动改过也能正确翻转）。
    返回 (新状态 bool|None, 窗口标题)。"""
    try:
        u32 = ctypes.windll.user32
        if not hwnd:
            return None, ""
        buf = ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(hwnd, buf, 256)
        title = buf.value.strip() or "(无标题窗口)"
        GWL_EXSTYLE, WS_EX_TOPMOST = -20, 0x0008
        topmost = bool(u32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)
        # HWND_TOPMOST(-1)/HWND_NOTOPMOST(-2) 是句柄宽度的伪指针，
        # 64 位下必须显式 argtypes 走 c_void_p，否则默认 32 位传参高位不稳
        u32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                     ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        # SWP_NOMOVE|SWP_NOSIZE|SWP_NOACTIVATE：只改层级，不动位置不抢焦点
        u32.SetWindowPos(hwnd,
                         ctypes.c_void_p(-2) if topmost else ctypes.c_void_p(-1),
                         0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
        return (not topmost), title
    except Exception:
        return None, ""


def toggle_pin_foreground():
    """Ctrl+Alt+T 入口：切换前台窗口置顶。"""
    try:
        return toggle_pin_hwnd(ctypes.windll.user32.GetForegroundWindow())
    except Exception:
        return None, ""


def _reg_read(root, path, name):
    """读注册表值（类型自适应 int/str/bytes），失败返回 None"""
    import winreg
    try:
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def get_win_info():
    """真实 Windows 版本。platform.platform() 在 Win11 上谎报 'Windows-10-...'——
    Python 可执行文件清单未声明 Win11 支持，内核走兼容模式返回 10.0；
    必须读注册表 CurrentBuildNumber，build >= 22000 即 Windows 11。"""
    import winreg
    CV = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    prod = _reg_read(winreg.HKEY_LOCAL_MACHINE, CV, "ProductName")
    disp = _reg_read(winreg.HKEY_LOCAL_MACHINE, CV, "DisplayVersion") or ""
    build_s = _reg_read(winreg.HKEY_LOCAL_MACHINE, CV, "CurrentBuildNumber")
    ubr = _reg_read(winreg.HKEY_LOCAL_MACHINE, CV, "UBR")
    try:
        build = int(build_s)
    except (TypeError, ValueError):
        build = 0
    try:
        ubr = int(ubr)
    except (TypeError, ValueError):
        ubr = 0
    if build >= 22000:
        name, ver = "Windows 11", "11"   # 注册表 ProductName 在 Win11 上仍写 "Windows 10..."，以 build 号为准
    else:
        name = (prod or "Windows 10").replace("Windows 10", "Windows 10").strip()
        ver = "10"
    return {"name": name, "ver": ver, "build": build, "ubr": ubr, "disp": disp}


def get_sys_info():
    info = {}
    # CPU 型号：platform.processor() 只给 "AMD64 Family 25 Model 33..." 这种
    # 平台描述串——注册表 ProcessorNameString 才是真实型号（如 Ryzen 5 5600）
    import winreg
    cpu_name = _reg_read(winreg.HKEY_LOCAL_MACHINE,
                         r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
                         "ProcessorNameString")
    if isinstance(cpu_name, str) and cpu_name.strip():
        info["CPU"] = " ".join(cpu_name.split())
    else:
        info["CPU"] = platform.processor() or "未知"
    info["内存"] = f"{psutil.virtual_memory().total / 1024**3:.0f}GB"
    w = get_win_info()
    ver = f"{w['name']} {w['disp']}".strip()
    if w["build"]:
        ver += f" ({w['build']}.{w['ubr']})"
    info["操作系统"] = ver or platform.platform()
    info["内核"] = f"{w['ver']} · NT 10.0.{w['build']}" if w["build"] else platform.release()
    info["位数"] = f"{ctypes.sizeof(ctypes.c_void_p) * 8}-bit"
    info["Python"] = platform.python_version()
    return info


def get_extra_info():
    """获取额外硬件信息（GPU/频率/温度/BIOS/IPv4/磁盘），全部使用 timeout 保护。"""
    extra = {"GPU": "未知", "显存": "未知", "频率": "未知", "温度": "未知",
             "IPv4": "未知", "安全启动": "未知", "BIOS": "未知", "磁盘": "未知"}

    def _run(cmd):
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags = subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=8,
                               startupinfo=si, shell=True, encoding="gbk", errors="ignore")
            return r.stdout.strip()
        except:
            return ""

    def _run_list(cmd):
        v = _run(cmd)
        return [x.strip() for x in v.replace("\n", "\r").split("\r") if x.strip()]

    # GPU
    gpu = _run('powershell -NoProfile -Command "(Get-CimInstance Win32_VideoController)[-1].Name"')
    if gpu: extra["GPU"] = gpu

    # 显存：Win32_VideoController.AdapterRAM 是 32 位无符号数，>4GB 的显卡会
    # 被截断成 4293918720（≈4GB）——RX 5600 XT 6GB 实测显示 4GB 就是这个坑。
    # 优先读注册表 HardwareInformation.qwMemorySize（64 位真值），失败再退回 WMI。
    import winreg
    vram_bytes = 0
    for idx in range(3):
        q = _reg_read(winreg.HKEY_LOCAL_MACHINE,
                      rf"SYSTEM\CurrentControlSet\Control\Class"
                      rf"\{{4d36e968-e325-11ce-bfc1-08002be10318}}\{idx:04d}",
                      "HardwareInformation.qwMemorySize")
        if isinstance(q, int) and q > 100*1024*1024:   # >100MB 才像显存
            vram_bytes = q
            break
        if isinstance(q, bytes) and len(q) == 8:
            import struct as _s
            v = _s.unpack("<Q", q)[0]
            if v > 100*1024*1024:
                vram_bytes = v
                break
    if not vram_bytes:
        vram = _run('powershell -NoProfile -Command "(Get-CimInstance Win32_VideoController | Select -Last 1).AdapterRAM"')
        try:
            vram_bytes = float(vram)
        except (TypeError, ValueError):
            vram_bytes = 0
    if vram_bytes:
        extra["显存"] = f"{vram_bytes/1024**3:.0f}GB" if vram_bytes > 1024**3 else f"{vram_bytes/1024**2:.0f}MB"

    # BIOS：WMI 查询可能空返回/超时，注册表 HARDWARE 描述块是更快的可靠来源；
    # 版本号后附带发布日期（如 "2803 (04/28/2022)"）
    bios = _run('powershell -NoProfile -Command "(Get-CimInstance Win32_BIOS).SMBIOSBIOSVersion"')
    if not bios or len(bios) > 60 or "\n" in bios:
        bios = str(_reg_read(winreg.HKEY_LOCAL_MACHINE,
                             r"HARDWARE\DESCRIPTION\System\BIOS", "BIOSVersion") or "")
    if bios:
        d = _reg_read(winreg.HKEY_LOCAL_MACHINE,
                      r"HARDWARE\DESCRIPTION\System\BIOS", "BIOSReleaseDate")
        if d and str(d) not in bios and len(bios) + len(str(d)) < 50:
            bios = f"{bios} ({d})"
        extra["BIOS"] = bios
    # 主板型号（报告导出用）
    bb = _reg_read(winreg.HKEY_LOCAL_MACHINE,
                   r"HARDWARE\DESCRIPTION\System\BIOS", "BaseBoardProduct")
    if isinstance(bb, str) and bb.strip():
        extra["主板"] = bb.strip()

    # 安全启动：注册表 UEFISecureBootEnabled（1=已启用；键不存在 = 非 UEFI 固件）
    sb = _reg_read(winreg.HKEY_LOCAL_MACHINE,
                   r"SYSTEM\CurrentControlSet\Control\SecureBoot\State",
                   "UEFISecureBootEnabled")
    if sb is None:
        extra["安全启动"] = "非 UEFI 固件"
    else:
        extra["安全启动"] = "已启用" if sb == 1 or str(sb) == "1" else "已关闭"

    # 磁盘：列出全部物理盘型号（去重，最多 3 块）
    disk_models = _run_list('powershell -NoProfile -Command "(Get-CimInstance Win32_DiskDrive).Model"')
    seen_d = []
    for m in disk_models:
        if m not in seen_d:
            seen_d.append(m)
    if seen_d:
        extra["磁盘"] = " + ".join(seen_d[:3])

    # CPU 频率
    try:
        freq = psutil.cpu_freq()
        if freq and freq.current: extra["频率"] = f"{freq.current/1000:.1f}GHz"
    except: pass

    # CPU 温度
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            best = None
            for zone, entries in temps.items():
                for e in entries:
                    if e.current and e.current > 0:
                        if best is None or "cpu" in zone.lower():
                            best = (e.current, zone)
            if best:
                extra["温度"] = f"{best[0]:.0f}°C"
    except: pass
    # 温度 fallback 1：LibreHardwareMonitor / OpenHardwareMonitor 的 WMI 命名空间
    # （用户装了任一监控软件并启动其服务即可读到真实 CPU 温度，无需管理员）
    if extra["温度"] == "未知":
        for ns in ("root/LibreHardwareMonitor", "root/OpenHardwareMonitor"):
            try:
                si = subprocess.STARTUPINFO()
                si.dwFlags = subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = 0
                script = ("Get-CimInstance -Namespace %s -ClassName Sensor "
                          "-Filter \"SensorType='Temperature'\" | "
                          "Where-Object { $_.Name -match 'CPU' } | "
                          "Measure-Object -Property Value -Maximum | "
                          "Select-Object -ExpandProperty Maximum" % ns)
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", script],
                    capture_output=True, text=True, timeout=6, startupinfo=si,
                    encoding="gbk", errors="ignore")
                v = float((r.stdout or "").strip() or "nan")
                if v == v and 0 < v < 120:   # NaN 过滤
                    extra["温度"] = f"{v:.0f}°C"
                    break
            except Exception:
                continue
    # 温度 fallback 2：MSAcpi_ThermalZoneTemperature（需要管理员权限）
    if extra["温度"] == "未知":
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags = subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            r = subprocess.run(
                'powershell -NoProfile -Command "Get-CimInstance MSAcpi_ThermalZoneTemperature -Namespace root/wmi"',
                capture_output=True, text=True, timeout=5, startupinfo=si,
                shell=True, encoding="gbk", errors="ignore")
            for line in r.stdout.split("\n"):
                if "CurrentTemperature" in line:
                    try:
                        # 温度单位是 0.01 Kelvin
                        temp = (int(line.split(":")[1].strip()) / 10 - 273.15)
                        extra["温度"] = f"{temp:.0f}°C"
                        break
                    except: pass
        except: pass

    # IPv4 (用 psutil)
    try:
        for nic, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == 2:  # AF_INET
                    ip = addr.address
                    if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
                        extra["IPv4"] = ip; break
            if extra["IPv4"] != "未知": break
    except: pass

    return extra


def _vram_total_bytes():
    """显卡总显存（注册表 HardwareInformation.qwMemorySize 64 位真值优先）。"""
    import winreg
    for idx in range(3):
        q = _reg_read(winreg.HKEY_LOCAL_MACHINE,
                      rf"SYSTEM\CurrentControlSet\Control\Class"
                      rf"\{{4d36e968-e325-11ce-bfc1-08002be10318}}\{idx:04d}",
                      "HardwareInformation.qwMemorySize")
        if isinstance(q, int) and q > 100 * 1024 * 1024:
            return q
        if isinstance(q, bytes) and len(q) == 8:
            import struct as _s
            v = _s.unpack("<Q", q)[0]
            if v > 100 * 1024 * 1024:
                return v
    return 0


_GPU_PS_STATE = {"ok": None}   # None=未探测 / True=可用 / False=本会话禁用


def query_gpu_status():
    """GPU 实时状态：先试 nvidia-smi（N 卡，含温度），失败则走 Windows 通用
    GPU 性能计数器（A 卡/N 卡/核显通吃：GPU Engine 利用率 + 专用显存）。
    返回 "利用率% · 已用/共GB[ · 温度°C]"，不可用返回空串。"""
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags = subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        r = subprocess.run(
            'nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu '
            '--format=csv,noheader,nounits',
            capture_output=True, text=True, timeout=4, startupinfo=si, shell=True,
            encoding="gbk", errors="ignore")
        lines = (r.stdout or "").strip().splitlines()
        parts = [p.strip() for p in lines[0].split(",")] if lines else []
        if len(parts) == 4:
            return f"{parts[0]}% · {int(parts[1])/1024:.1f}/{int(parts[2])/1024:.1f}GB · {parts[3]}°C"
    except Exception:
        pass
    # —— 通用 GPU 计数器路径（这台机器是 RX 5600 XT，nvidia-smi 永远为空）——
    if _GPU_PS_STATE["ok"] is False:
        return ""
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags = subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        script = ("$u=(Get-Counter '\\GPU Engine(*engtype_3D)\\Utilization Percentage' "
                  "-ErrorAction Stop).CounterSamples | Measure-Object CookedValue -Sum; "
                  "$m=(Get-Counter '\\GPU Adapter Memory(*)\\Dedicated Usage' "
                  "-ErrorAction Stop).CounterSamples | Measure-Object CookedValue -Sum; "
                  "'{0:F0};{1:F0}' -f [Math]::Min(100,$u.Sum), $m.Sum")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                           capture_output=True, text=True, timeout=8,
                           startupinfo=si, encoding="gbk", errors="ignore")
        out = (r.stdout or "").strip()
        if ";" not in out:
            raise ValueError(out or "no counter output")
        u_str, m_str = out.split(";", 1)
        util = min(100.0, max(0.0, float(u_str)))
        used = max(0.0, float(m_str))
        total = _vram_total_bytes()
        txt = f"{util:.0f}% · {used/1024**3:.1f}"
        txt += f"/{total/1024**3:.1f}GB" if total else "GB"
        _GPU_PS_STATE["ok"] = True
        return txt
    except Exception:
        _GPU_PS_STATE["ok"] = False   # 计数器不可用（精简系统/驱动不支持），本会话不再重试
        return ""


def get_startup():
    """开机自启项（结构化）：kind=reg(注册表 Run/RunOnce) / file(启动文件夹)。
    启用/禁用走 Windows 官方的 StartupApproved 机制（与任务管理器一致）。"""
    import winreg
    items = []
    seen = set()
    hives = [(winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")]
    for hive, hname in hives:
        for runkey in ("Run", "RunOnce"):
            try:
                h = winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\{runkey}")
                for i in range(winreg.QueryInfoKey(h)[1]):
                    name, val, _ = winreg.EnumValue(h, i)
                    key = f"{hname}:{runkey}:{name}"
                    if name and key not in seen:
                        seen.add(key)
                        items.append({"name": name, "val": val, "kind": "reg",
                                      "hive": hname, "runkey": runkey})
                winreg.CloseKey(h)
            except OSError:
                pass
    # 启动文件夹
    for folder in [Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup",
                   Path("C:/ProgramData/Microsoft/Windows/Start Menu/Programs/Startup")]:
        if folder.exists():
            for f in folder.iterdir():
                if f.suffix in (".lnk", ".exe") and str(f).lower() not in seen:
                    seen.add(str(f).lower())
                    items.append({"name": f.name, "val": str(f), "kind": "file",
                                  "hive": "HKCU" if "AppData" in str(folder) else "HKLM",
                                  "runkey": "StartupFolder"})
    # StartupApproved 状态（缺值 = 启用）
    for it in items:
        it["disabled"] = _startup_approved_state(it) is False
    # 计划任务自启项（注册表 Run 键 + 启动文件夹都抓不到，现代软件最爱藏这儿）
    items.extend(get_task_startups())
    return items


_TASK_LOGON_TRIGGERS = ("MSFT_TaskLogonTrigger", "MSFT_TaskBootTrigger",
                        "MSFT_TaskSessionStateChangeTrigger")


def get_task_startups():
    """计划任务中的开机/登录自启项。返回 kind="task" 的字典列表。
    实测：注册表+启动文件夹只报 5 项，计划任务里还有 50+ 项（OneDrive/AMD/主板管家等）。"""
    script = (
        "Get-ScheduledTask | ForEach-Object { "
        "$trg = ($_.Triggers | ForEach-Object { $_.CimClass.CimClassName }) -join '|'; "
        "$act = ($_.Actions | ForEach-Object { $_.Execute }) -join '|'; "
        "if ($trg) { $_.TaskName + \"`t\" + $_.TaskPath + \"`t\" + $_.State + \"`t\" "
        "+ $trg + \"`t\" + $act } }")
    out = _ps_query(script, timeout=60)
    items = []
    for line in (out or "").splitlines():
        p = line.split("\t")
        if len(p) < 4:
            continue
        trig = p[3]
        if not any(k in trig for k in _TASK_LOGON_TRIGGERS):
            continue
        name, path, state = p[0].strip(), p[1].strip(), p[2].strip()
        act = p[4].strip() if len(p) > 4 else ""
        if not name:
            continue
        items.append({"name": name, "val": act or "(计划任务 · 无显式动作)",
                      "kind": "task", "hive": "TASK", "runkey": "TaskScheduler",
                      "task_name": name, "task_path": path or "\\",
                      "disabled": state.lower() == "disabled"})
    # 系统任务（Microsoft 目录下）排后面，用户级优先展示
    items.sort(key=lambda x: (x["task_path"].lower().startswith("\\microsoft"), x["name"].lower()))
    return items


def toggle_task_item(item):
    """启用/禁用计划任务。用户级任务免管理员；系统任务失败时如实报错。"""
    name = item.get("task_name", "")
    path = item.get("task_path", "\\") or "\\"
    cur = not bool(item.get("disabled"))
    verb = "Disable" if cur else "Enable"

    def esc(s):
        return str(s).replace("'", "''")
    script = (
        f"$t = Get-ScheduledTask -TaskName '{esc(name)}' -TaskPath '{esc(path)}' "
        f"-ErrorAction SilentlyContinue; "
        f"if ($t) {{ {verb}-ScheduledTask -TaskName '{esc(name)}' "
        f"-TaskPath '{esc(path)}' -ErrorAction SilentlyContinue | Out-Null; 'OK' }} "
        f"else {{ 'NOTFOUND' }}")
    out = _ps_query(script, timeout=40)
    if "OK" not in (out or ""):
        return False, cur, "操作失败（系统任务需要管理员权限）"
    return True, not cur, ("已禁用" if cur else "已启用")


def _startup_approved_key(item):
    import winreg
    hive = winreg.HKEY_CURRENT_USER if item["hive"] == "HKCU" else winreg.HKEY_LOCAL_MACHINE
    sub = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\{item['runkey']}"
    return hive, sub


def _startup_approved_state(item):
    """True=启用 / False=禁用 / None=未知（如权限不足）。禁用标志：首字节为奇数。"""
    import winreg
    try:
        hive, sub = _startup_approved_key(item)
        with winreg.OpenKey(hive, sub) as k:
            data, _t = winreg.QueryValueEx(k, item["name"])
            if isinstance(data, bytes) and data:
                return (data[0] & 0x01) == 0
        return True
    except FileNotFoundError:
        return True   # 无记录 = 默认启用
    except OSError:
        return None


def toggle_startup_item(item):
    """禁用/启用自启项。返回 (成功, 新状态bool|None, 消息)。"""
    if item.get("kind") == "task":
        return toggle_task_item(item)
    import winreg
    import struct
    cur = _startup_approved_state(item)
    if cur is None:
        return False, None, "无法读写 StartupApproved（HKLM 项需要管理员权限）"
    hive, sub = _startup_approved_key(item)
    try:
        with winreg.CreateKeyEx(hive, sub, 0, winreg.KEY_SET_VALUE) as k:
            if cur:  # 启用中 → 禁用（03 + 当前时间 FILETIME，与任务管理器一致）
                data = b"\x03\x00\x00\x00" + struct.pack("<Q", int((time.time() + 11644473600) * 10_000_000))
                winreg.SetValueEx(k, item["name"], 0, winreg.REG_BINARY, data)
                return True, False, "已禁用"
            else:    # 已禁用 → 启用（删除标志值即可）
                winreg.DeleteValue(k, item["name"])
                return True, True, "已启用"
    except OSError as e:
        return False, cur, f"操作失败（HKLM 项需要管理员权限）：{e}"


def get_disk_health():
    """物理磁盘 SMART 概览：健康状态/介质/总线/容量/通电时长/所辖盘符。
    通电时长需管理员（Get-StorageReliabilityCounter），无权限时置 None——不编造数字。
    letters 用于把「卷」对上它的物理盘（卷是分区、SMART 是按物理盘给的，
    两者数量并不相等，只按下标硬配会把别的盘的数据显示到本卷旁边）。"""
    script = (
        "Get-PhysicalDisk | ForEach-Object { "
        "$d = $_; "
        "$rc = $d | Get-StorageReliabilityCounter -ErrorAction SilentlyContinue; "
        "$h = if ($rc -and $rc.PowerOnHours -ne $null) { $rc.PowerOnHours } else { '' }; "
        "$t = if ($rc -and $rc.Temperature -ne $null) { $rc.Temperature } else { '' }; "
        "$ls = ((Get-Partition -DiskNumber $d.DeviceId -ErrorAction SilentlyContinue) | "
        "Where-Object { $_.DriveLetter } | ForEach-Object { [string]$_.DriveLetter }) -join ','; "
        "$d.FriendlyName + \"`t\" + $d.MediaType + \"`t\" + $d.HealthStatus + \"`t\" "
        "+ $d.BusType + \"`t\" + $d.Size + \"`t\" + $h + \"`t\" + $t + \"`t\" + $ls }")
    out = _ps_query(script, timeout=45)
    rows = []
    for line in (out or "").splitlines():
        p = [x.strip() for x in line.split("\t")]
        if len(p) < 4 or not p[0]:
            continue
        try:
            size = int(float(p[4])) if len(p) > 4 and p[4] else 0
        except ValueError:
            size = 0
        hours = None
        if len(p) > 5 and p[5]:
            try:
                hours = int(float(p[5]))
            except ValueError:
                hours = None
        temp = None
        if len(p) > 6 and p[6]:
            try:
                temp = int(float(p[6]))
            except ValueError:
                temp = None
        rows.append({"name": p[0], "media": p[1] or "-", "health": p[2] or "-",
                     "bus": p[3] or "-", "size": size, "hours": hours, "temp": temp,
                     "letters": p[7].strip().upper() if len(p) > 7 else ""})
    return rows


def _health_for_mount(health, mount, idx=None, vol_count=None):
    """按盘符把「卷」对上它的物理盘 SMART 行；认不出就返回 None（宁可不显示）。"""
    letter = ""
    try:
        letter = os.path.splitdrive(str(mount or ""))[0].rstrip(":\\").strip().upper()
    except Exception:
        letter = ""
    if letter:
        for h in health:
            letters = {x.strip().upper()
                       for x in str(h.get("letters", "") or "").split(",") if x.strip()}
            if letter in letters:
                return h
    # 盘符信息整体拿不到（老系统 / 权限受限）时，只有在"卷数 == 物理盘数"
    # 这种 1:1 情形下才退回按序号对应
    if not any(str(h.get("letters", "") or "").strip() for h in health):
        if idx is not None and vol_count is not None and len(health) == vol_count:
            return health[idx]
    return None


def find_empty_dirs(roots, stop=None):
    """查找空文件夹（自底向上，空目录收集后其父目录若也空会被一并记录）。
    系统/受保护目录自动跳过；stop 为可调用对象，返回 True 时中断扫描。"""
    found = []
    skip = {os.path.realpath(os.environ.get("WINDIR", r"C:\Windows")).lower(),
            os.path.realpath(os.environ.get("PROGRAMFILES", r"C:\Program Files")).lower(),
            os.path.realpath(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")).lower()}
    for root in roots:
        root = str(root)
        if not root or not os.path.isdir(root):
            continue
        base = os.path.realpath(root).lower()
        if any(base == s or base.startswith(s + os.sep) for s in skip):
            continue
        try:
            for cur, dirs, files in os.walk(root, topdown=False):
                if stop and stop():
                    return found
                try:
                    cur_r = os.path.realpath(cur).lower()
                except OSError:
                    continue
                if any(cur_r == s or cur_r.startswith(s + os.sep) for s in skip):
                    continue
                try:
                    if not os.listdir(cur):
                        found.append(cur)
                except OSError:
                    continue
        except OSError:
            continue
    return found


# ═══ OCR 文字识别（Windows 自带 WinRT OCR，无需额外依赖）═══
_OCR_PS1 = r'''
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Storage.StorageFile,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream,Windows.Foundation,ContentType=WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
                   $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
Function Await($op, $t) {
    $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    $task.Result
}
$ocr = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if (-not $ocr) { [Console]::Error.WriteLine('NO_OCR_LANGUAGE'); exit 2 }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($args[0])) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$create = [Windows.Graphics.Imaging.BitmapDecoder].GetMethod('CreateAsync', [type[]]@([Windows.Storage.Streams.IRandomAccessStream]))
$decoder = Await ($create.Invoke($null, @($stream))) ([Windows.Graphics.Imaging.BitmapDecoder])
$bmp = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$result = Await ($ocr.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
[IO.File]::WriteAllText($args[1], $result.Text, [Text.Encoding]::UTF8)
'''


def ocr_image_text(image_path, timeout=120):
    """识别图片中的文字。返回 (文本, 错误)；错误为 None 表示成功。
    使用 Windows.Media.Ocr（系统已装语言包即可，离线）。"""
    image_path = str(image_path)
    if not os.path.isfile(image_path):
        return "", "图片文件不存在"
    ps1 = Path(tempfile.gettempdir()) / "utb_ocr.ps1"
    out = Path(tempfile.gettempdir()) / f"utb_ocr_{os.getpid()}.txt"
    try:
        ps1.write_text(_OCR_PS1, encoding="utf-8-sig")
        try: out.unlink(missing_ok=True)
        except Exception: pass
        powershell = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) /
                         "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")
        r = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(ps1), image_path, str(out)],
            capture_output=True, timeout=timeout)
        if r.returncode != 0:
            err = (r.stderr or b"").decode("gbk", "ignore").strip()
            return "", err or f"OCR 失败（码 {r.returncode}）"
        if not out.exists():
            return "", "OCR 未产生结果"
        return out.read_text(encoding="utf-8-sig"), None
    except subprocess.TimeoutExpired:
        return "", "OCR 超时"
    except Exception as e:
        return "", str(e)
    finally:
        for p in (ps1, out):
            try: p.unlink(missing_ok=True)
            except Exception: pass


def text_transform(text, op):
    """剪贴板文本工具箱：纯函数文本变换。返回 (结果, 错误信息)。"""
    import base64, hashlib, urllib.parse, json as _json
    t = text or ""
    try:
        if op == "upper":    return t.upper(), ""
        if op == "lower":    return t.lower(), ""
        if op == "title":    return t.title(), ""
        if op == "trim":     return t.strip(), ""
        if op == "strip":    return "\n".join(l.rstrip() for l in t.splitlines()), ""
        if op == "no_blank": return "\n".join(l for l in t.splitlines() if l.strip()), ""
        if op == "collapse": return re.sub(r"[ \t]{2,}", " ", t).strip(), ""
        if op == "dedupe":
            seen, out = set(), []
            for l in t.splitlines():
                k = l.strip()
                if not k:
                    out.append(l)
                elif k not in seen:
                    seen.add(k)
                    out.append(l)
            return "\n".join(out), ""
        if op == "sort":     return "\n".join(sorted(t.splitlines())), ""
        if op == "reverse":  return "\n".join(reversed(t.splitlines())), ""
        if op == "quote":
            return "\n".join(('"' + l + '"') for l in t.splitlines()), ""
        if op == "comma":
            return ", ".join(x.strip() for x in t.splitlines() if x.strip()), ""
        if op == "b64e":     return base64.b64encode(t.encode("utf-8")).decode(), ""
        if op == "b64d":
            return base64.b64decode(t.encode("utf-8")).decode("utf-8", "replace"), ""
        if op == "url_e":    return urllib.parse.quote(t, safe=""), ""
        if op == "url_d":    return urllib.parse.unquote(t), ""
        if op == "md5":      return hashlib.md5(t.encode("utf-8")).hexdigest(), ""
        if op == "sha1":     return hashlib.sha1(t.encode("utf-8")).hexdigest(), ""
        if op == "sha256":   return hashlib.sha256(t.encode("utf-8")).hexdigest(), ""
        if op == "json":
            return _json.dumps(_json.loads(t), ensure_ascii=False, indent=2), ""
        if op == "json_min":
            return _json.dumps(_json.loads(t), ensure_ascii=False,
                               separators=(",", ":")), ""
        if op == "count":
            return (f"字符 {len(t)} · 行 {len(t.splitlines())} · "
                    f"词 {len(t.split())} · 字节 {len(t.encode('utf-8'))}"), ""
        # ── 编码类（v3.6）：乱码修复与转义 ──
        if op == "fix_utf8_as_gbk":
            # UTF-8 字节被当成 GBK 打开（如"鏂囦欢"）→ 还原
            fixed = t.encode("gbk", "ignore").decode("utf-8", "ignore")
            return (fixed, "") if fixed else ("", "无法按此方式还原（原文可能不含此类乱码）")
        if op == "fix_gbk_as_utf8":
            # GBK 字节被当成 UTF-8 打开（如"ÎÄ¼þ"）→ 还原
            fixed = t.encode("utf-8", "ignore").decode("gbk", "ignore")
            return (fixed, "") if fixed else ("", "无法按此方式还原（原文可能不含此类乱码）")
        if op == "uni_escape":
            return t.encode("unicode_escape").decode("ascii"), ""
        if op == "uni_unescape":
            return t.encode("ascii", "ignore").decode("unicode_escape"), ""
        if op == "hex_view":
            data = t.encode("utf-8")
            return " ".join(f"{b:02X}" for b in data[:256]), ""
    except Exception as e:
        return "", f"转换失败：{type(e).__name__}: {e}"
    return t, ""


# ═══ 电源定时（v3.6）：交给系统 shutdown 计时器，关掉工具箱也照常执行 ═══
_POWER_ACTIONS = {"shutdown": ("/s", "关机"), "restart": ("/r", "重启")}


def schedule_power_action(action, seconds):
    """定时关机/重启。走系统 shutdown 计时器（工具箱退出/重启也不影响执行）。
    返回 (ok, 提示信息)。"""
    if action not in _POWER_ACTIONS:
        return False, "未知操作"
    try:
        secs = int(seconds)
    except (TypeError, ValueError):
        return False, "时间格式无效"
    if not 10 <= secs <= 86400:
        return False, "时间需在 10 秒 ~ 24 小时之间"
    flag, label = _POWER_ACTIONS[action]
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags = subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        r = subprocess.run(["shutdown", flag, "/t", str(secs)],
                           capture_output=True, text=True, timeout=15,
                           startupinfo=si, encoding="gbk", errors="ignore")
        if r.returncode == 0:
            return True, f"已设定 {secs // 60} 分 {secs % 60} 秒后{label}"
        return False, (r.stderr or r.stdout or "系统拒绝该操作").strip()[:120]
    except Exception as e:
        return False, f"调用失败：{str(e)[:100]}"


def cancel_power_action():
    """取消已设定的关机/重启倒计时（shutdown /a）"""
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags = subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        r = subprocess.run(["shutdown", "/a"], capture_output=True, text=True,
                           timeout=15, startupinfo=si, encoding="gbk", errors="ignore")
        if r.returncode == 0:
            return True, "已取消定时任务"
        return False, (r.stderr or r.stdout or "没有待取消的定时任务").strip()[:120]
    except Exception as e:
        return False, f"取消失败：{str(e)[:100]}"


def power_action_now(action):
    """立即执行：休眠走 shutdown /h；关机/重启带 10 秒缓冲（留反悔余地）。"""
    if action == "hibernate":
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags = subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            r = subprocess.run(["shutdown", "/h"], capture_output=True, text=True,
                               timeout=15, startupinfo=si, encoding="gbk", errors="ignore")
            if r.returncode == 0:
                return True, "正在休眠"
            return False, (r.stderr or r.stdout or "休眠失败（系统可能未启用休眠）").strip()[:120]
        except Exception as e:
            return False, f"休眠失败：{str(e)[:100]}"
    return schedule_power_action(action, 10)


def grab_pixel_rgb(x, y):
    """取屏幕坐标 (x, y) 处的颜色 → (r, g, b)；失败返回 None"""
    try:
        im = _PILImageGrab.grab(bbox=(int(x), int(y), int(x) + 1, int(y) + 1))
        return im.convert("RGB").getpixel((0, 0))
    except Exception:
        return None


def grab_region_zoom(x, y, half=8, zoom=9):
    """取屏幕 (x, y) 周围一小块并放大 → PIL Image（取色器放大镜）"""
    try:
        im = _PILImageGrab.grab(bbox=(int(x) - half, int(y) - half,
                                      int(x) + half + 1, int(y) + half + 1))
        return im.convert("RGB").resize(((half * 2 + 1) * zoom,) * 2, _PILImage.NEAREST)
    except Exception:
        return None


# ═══ 批量重命名（v3.6）：先算计划、再落盘，预览与执行共用同一份计算 ═══
_ILLEGAL_NAME_CHARS = set('\\/:*?"<>|')


def plan_rename(names, prefix="", suffix="", find="", repl="", use_regex=False,
                seq_start=1, seq_digits=2, seq_pos="none", case="keep",
                keep_ext=True, existing=None):
    """按规则计算新文件名 → [(原名, 新名, 错误说明)]。
    顺序：大小写 → 查找替换 → 前后缀 → 序号（seq_pos="none" 时不加序号，
    这是默认值——不能因为用户没提序号就强加编号）。
    keep_ext=True 时扩展名不动。
    existing：目录内【未列入本批】的已有文件名集合（小写），用于提前暴露
    "新名与磁盘上既有文件撞车"——否则用户要等到执行时才看到"已跳过"。
    只做计划，不碰磁盘。"""
    out = []
    try:
        rx = re.compile(find) if (use_regex and find) else None
    except re.error as e:
        return [(n, n, f"正则无效：{e}") for n in names]
    for idx, old in enumerate(names):
        stem, ext = (os.path.splitext(old) if keep_ext else (old, ""))
        new = stem
        err = ""
        if case == "lower":
            new = new.lower()
        elif case == "upper":
            new = new.upper()
        if find:
            if use_regex:
                new = rx.sub(repl, new)
            else:
                new = new.replace(find, repl)
        if prefix:
            new = prefix + new
        if suffix:
            new = new + suffix
        if seq_pos != "none":
            token = str(seq_start + idx).zfill(max(1, int(seq_digits)))
            new = new + token if seq_pos == "suffix" else token + new
        new = new.strip()
        if not new:
            err = "新名称为空"
        elif any(ch in _ILLEGAL_NAME_CHARS for ch in new):
            err = "含非法字符 \\ / : * ? \" < > |"
        elif new != new.rstrip(". "):
            err = "名称不能以点或空格结尾"
        out.append((old, new + ext, err))
    # 批内重名检测（含大小写不敏感比较）
    seen = {}
    for i, (old, new, err) in enumerate(out):
        if err:
            continue
        k = new.lower()
        if k in seen:
            out[i] = (old, new, "与本批其它文件重名")
            continue
        seen[k] = old
    # 与目录内既有文件（未列入本批）撞车检测：仅大小写差异的重命名不算冲突
    if existing:
        exist_low = {str(x).lower() for x in existing}
        for i, (old, new, err) in enumerate(out):
            if err or new.lower() == old.lower():
                continue
            if new.lower() in exist_low:
                out[i] = (old, new, "目标名已被占用（未列入本批）")
    return out


def apply_rename(folder, pairs):
    """执行重命名。pairs = [(原名, 新名)]（仅含无错误的项）。
    返回 (成功数, 失败列表, 撤销记录)。改名两阶段：先改成临时名再改终名，
    避免"A→B 而 B 是批内另一个原名"的连环冲突。"""
    done, failed, record = 0, [], []
    temp_pairs = []
    for i, (old, new) in enumerate(pairs):
        src = os.path.join(folder, old)
        tmp = os.path.join(folder, f"__utb_tmp_{os.getpid()}_{i}__")
        try:
            if not os.path.exists(src):
                failed.append((old, "源文件不存在"))
                continue
            os.rename(src, tmp)
            temp_pairs.append((tmp, new, old))
        except OSError as e:
            failed.append((old, f"预处理失败：{e.strerror or e}"))
    for tmp, new, old in temp_pairs:
        dst = os.path.join(folder, new)
        try:
            if os.path.exists(dst):
                os.rename(tmp, os.path.join(folder, old))   # 还原，避免覆盖
                failed.append((old, "目标名已存在，已跳过"))
                continue
            os.rename(tmp, dst)
            record.append((new, old))
            done += 1
        except OSError as e:
            try:
                os.rename(tmp, os.path.join(folder, old))
            except OSError:
                pass
            failed.append((old, f"重命名失败：{e.strerror or e}"))
    return done, failed, record


def undo_rename(folder, record):
    """按撤销记录（新名，原名）两阶段还原，支持名称交换及循环改名。"""
    ok, failed, _ = apply_rename(folder, list(reversed(record)))
    return ok, failed


# ═══ 目录体积树图（v3.6 C 波）：递归统计 + squarified treemap 布局 ═══
def _dir_total(path, stop=None, deadline=None, depth=0, max_depth=12):
    """递归累加目录体积（带截止时间与中断回调，避免卡死大目录）"""
    total = 0
    if depth > max_depth:
        return 0
    try:
        with os.scandir(path) as it:
            for e in it:
                if stop and stop():
                    return total
                if deadline and time.time() > deadline:
                    return total
                try:
                    if e.is_dir(follow_symlinks=False):
                        total += _dir_total(e.path, stop, deadline, depth + 1, max_depth)
                    elif e.is_file(follow_symlinks=False):
                        total += e.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
    except OSError:
        return total
    return total


def scan_dir_sizes(path, stop=None, budget=8.0, top_n=60):
    """列出目录下各子项体积（目录递归累加），体积降序。
    budget：单次扫描的时间预算（秒），超时即截断并标记，保证界面不假死。
    返回 (items, total, truncated)。items = [{name, path, size, is_dir}]"""
    items, truncated = [], False
    deadline = time.time() + budget
    try:
        with os.scandir(path) as it:
            entries = list(it)
    except OSError as e:
        return [], 0, False
    for e in entries:
        if stop and stop():
            break
        if time.time() > deadline:
            truncated = True
            break
        try:
            if e.is_dir(follow_symlinks=False):
                sz = _dir_total(e.path, stop, deadline)
                items.append({"name": e.name, "path": e.path, "size": sz, "is_dir": True})
            elif e.is_file(follow_symlinks=False):
                items.append({"name": e.name, "path": e.path,
                              "size": e.stat(follow_symlinks=False).st_size,
                              "is_dir": False})
        except OSError:
            continue
    items.sort(key=lambda x: x["size"], reverse=True)
    total = sum(x["size"] for x in items)
    return items[:top_n], total, truncated


def squarify(values, x, y, w, h):
    """Squarified treemap 布局（Bruls 等算法）：values 为降序正数列表。
    返回 [(x, y, w, h)]，与 values 一一对应——矩形面积严格正比于数值，
    长宽比尽量接近 1（避免出现细长条）。
    注意：不要事后把"剩余空间"并进最后一块——那会让总面积超过容器。"""
    vals = [max(float(v), 0.0) for v in values]
    total = sum(vals)
    if not vals or total <= 0 or w <= 0 or h <= 0:
        return [(x, y, max(0.0, w), max(0.0, h)) for _ in vals]
    scaled = [v * (w * h) / total for v in vals]

    def _worst(row, side):
        s = sum(row)
        if s <= 0 or side <= 0:
            return float("inf")
        mx, mn = max(row), min(row)
        return max((side * side * mx) / (s * s), (s * s) / (side * side * mn))

    rects = []
    i, n = 0, len(scaled)
    while i < n:
        if w <= 1e-6 or h <= 1e-6:          # 空间耗尽：剩余项给零面积占位
            rects.extend([(x, y, max(0.0, w), max(0.0, h))] * (n - i))
            break
        vertical = w >= h                    # 容器更宽 → 横铺一行（行高 = 行面积和 / 宽）
        side = w if vertical else h
        row, j, s = [], i, 0.0
        while j < n:
            cand = row + [scaled[j]]
            if row and _worst(cand, side) > _worst(row, side):
                break
            row, s, j = cand, s + scaled[j], j + 1
        if vertical:
            row_h = min(s / w, h)
            cx = x
            for v in row:
                rw = v / row_h if row_h > 0 else 0.0
                rw = min(rw, max(0.0, x + w - cx))      # 不越出容器右边界
                rects.append((cx, y, rw, row_h))
                cx += rw
            y += row_h
            h -= row_h
        else:
            row_w = min(s / h, w)
            cy = y
            for v in row:
                rh = v / row_w if row_w > 0 else 0.0
                rh = min(rh, max(0.0, y + h - cy))      # 不越出容器下边界
                rects.append((x, cy, row_w, rh))
                cy += rh
            x += row_w
            w -= row_w
        i = j
    return rects


# ═══ 极速文件搜索（v3.6 C 波）：自建索引 + 磁盘缓存 ═══
# 走自有索引而非解析 NTFS MFT——读 MFT 需要管理员权限，与"双击即用"的定位冲突
INDEX_FILE = Path.home() / ".unified_toolbox_index.gz"


def _path_has_segments(low_path, skips):
    """low_path 里是否出现了任一片段序列（要求目录名连续出现）。

    片段用"目录名序列"而非裸前缀来匹配：_pick_roots 给的片段形如
    "\\Windows\\WinSxS"、`node_modules`，旧实现拿它去 startswith 整条绝对路径
    （"c:\\windows\\winsxs\\..."），永远匹配不上，等于完全没有跳过。
    """
    segs = [x for x in low_path.replace("/", "\\").split("\\") if x]
    for frag in skips:
        n = len(frag)
        if n > len(segs):
            continue
        for i in range(len(segs) - n + 1):
            if tuple(segs[i:i + n]) == frag:
                return True
    return False


def build_file_index(roots, progress=None, stop=None, skip_prefixes=None):
    """扫描指定根目录，收集文件与目录全路径。返回路径列表（'D\\t路径' / 'F\\t路径'）。
    progress(done, current) 用于汇报进度，stop() 返回 True 时提前结束。
    skip_prefixes：形如 "\\Windows\\WinSxS"、"node_modules" 的目录片段，
    命中即整棵子树不进入索引。"""
    out = []
    skips = []
    for frag in (skip_prefixes or ()):
        parts = [x for x in str(frag).replace("/", "\\").split("\\") if x]
        parts = [x.lower() for x in parts]
        if parts:
            skips.append(tuple(parts))
    for root in roots:
        if stop and stop():
            break
        stack = [str(root)]
        while stack:
            if stop and stop():
                break
            cur = stack.pop()
            try:
                with os.scandir(cur) as it:
                    for e in it:
                        p = e.path
                        try:
                            if e.is_dir(follow_symlinks=False):
                                # 跳过判断只在下钻时做一次，避免逐条路径重复计算
                                if skips and _path_has_segments(p.lower(), skips):
                                    continue
                                out.append("D\t" + p)
                                stack.append(p)
                            elif e.is_file(follow_symlinks=False):
                                out.append("F\t" + p)
                        except OSError:
                            continue
            except OSError:
                continue
            if progress and len(out) % 2000 < 40:
                progress(len(out), cur)
    if progress:
        progress(len(out), "")
    return out


def save_index(entries):
    """索引落盘（gzip 压缩，几十万条也只有几 MB）"""
    import gzip
    try:
        tmp = INDEX_FILE.with_suffix(".gz.tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            f.write("\n".join(entries))
        tmp.replace(INDEX_FILE)
        return True
    except Exception:
        return False


def load_index():
    """读回索引，返回 (条目列表, 生成时间戳)；缺失/损坏返回 ([], 0)"""
    import gzip
    try:
        with gzip.open(INDEX_FILE, "rt", encoding="utf-8") as f:
            data = f.read()
        return [ln for ln in data.split("\n") if ln], INDEX_FILE.stat().st_mtime
    except Exception:
        return [], 0.0


def search_index(entries, keyword, limit=400):
    """索引内搜索：空格分隔的多个关键词需全部命中（与逻辑），不区分大小写。
    返回 [(是否目录, 路径)]，目录优先、路径短的优先（更可能是用户想找的）。"""
    kws = [k.lower() for k in str(keyword).split() if k]
    if not kws:
        return []
    hit = []
    for e in entries:
        if not e:
            continue
        low = e.lower()
        if all(k in low for k in kws):
            hit.append((e[0] == "D", e[2:]))
            if len(hit) >= limit * 4:
                break
    hit.sort(key=lambda t: (not t[0], len(t[1])))
    return hit[:limit]


SNIPPETS_FILE = Path.home() / ".unified_toolbox_snippets.json"


def load_snippets():
    """片段库（收藏的常用文本）：[{id, name, group, text, uses, ts}]"""
    try:
        data = json.loads(SNIPPETS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_snippets(items):
    try:
        tmp = SNIPPETS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(SNIPPETS_FILE)
        return True
    except Exception:
        return False


def get_disks():
    disks = []
    for p in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(p.mountpoint)
            disks.append({"device": p.device, "mount": p.mountpoint,
                          "total": u.total, "used": u.used, "free": u.free,
                          "percent": u.percent})
        except: pass
    return disks


_PROC_FIRST_SCAN = True   # psutil cpu_percent 首扫返回自进程创建起的累计值（explorer 曾显示 398%）


def get_processes():
    global _PROC_FIRST_SCAN
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "create_time", "exe"]):
        try:
            info = p.info
            mem = (info["memory_info"].rss if info["memory_info"] else 0)
            ct = info["create_time"] or 0
            el = time.time() - ct if ct else 0
            h, m, s = int(el)//3600, (int(el)%3600)//60, int(el)%60
            cpu = info["cpu_percent"] or 0
            if _PROC_FIRST_SCAN:
                cpu = 0.0   # 首扫数值不可信（累计值而非速率），清零；下一轮（5s 后）即为真实速率
            procs.append({"pid": info["pid"], "name": info["name"] or "",
                          "cpu": cpu, "mem": mem,
                          "etime": f"{h:02d}:{m:02d}:{s:02d}",
                          "exe": info.get("exe") or ""})
        except: pass
    _PROC_FIRST_SCAN = False
    procs.sort(key=lambda x: x["mem"], reverse=True)
    return procs


def _same_proc_name(live, listed):
    """核对进程名是否仍是同一个进程（大小写不敏感）。
    任一侧没拿到名字时返回 True（不据此拦截），避免因信息缺失而误拒。"""
    a = (live or "").strip().casefold()
    b = (listed or "").strip().casefold()
    if a in ("", "?") or b in ("", "?"):
        return True
    return a == b


def get_port_usage(port=None):
    """端口占用查询：netstat -ano 解析 + PID→进程名映射。
    port 为空 → 返回全部 LISTENING 项；指定端口 → 该端口全部连接。"""
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    rows = []
    try:
        outs = []
        for args in (["netstat", "-ano", "-p", "TCP"], ["netstat", "-ano", "-p", "UDP"]):
            try:
                r = subprocess.run(args, capture_output=True, text=True, timeout=10,
                                   startupinfo=si, encoding="gbk", errors="ignore")
                outs.append(r.stdout or "")
            except Exception:
                pass
        names = {}
        for p in psutil.process_iter(["pid", "name"]):
            try: names[p.info["pid"]] = p.info["name"] or "?"
            except Exception: pass
        for out in outs:
            for line in out.splitlines():
                parts = line.split()
                if len(parts) < 4 or parts[0] not in ("TCP", "UDP"):
                    continue
                if parts[0] == "TCP" and len(parts) >= 5:
                    local, remote, state, pid = parts[1], parts[2], parts[3], parts[4]
                else:
                    local, remote, state, pid = parts[1], parts[2], "-", parts[3]
                try:
                    pid = int(pid)
                except ValueError:
                    continue
                if port is not None:
                    if local.rsplit(":", 1)[-1] != str(port):
                        continue
                elif state not in ("LISTENING", "-"):
                    continue   # 全览模式只看监听端口（避免几千条 TIME_WAIT 刷屏）
                rows.append({"proto": parts[0], "local": local, "remote": remote,
                             "state": state, "pid": pid, "pname": names.get(pid, "?")})
        rows.sort(key=lambda r: (int(r["local"].rsplit(":", 1)[-1] or 0), r["proto"]))
    except Exception:
        pass
    return rows


# ═══════════════════════════════════════════
# 激活检测（只读，全部走微软官方数据源：SoftwareLicensing WMI + slmgr）
# ═══════════════════════════════════════════

_WIN_APPID = "55c92734-d682-4d71-983e-d6ec3f16059f"    # Windows 平台 ApplicationID
_OFFICE_APPID = "59a52881-a989-479d-af46-f275c6370663"  # Office 家族 ApplicationID

_LICENSE_STATUS = {0: "未激活", 1: "已激活", 2: "OOB 宽限期", 3: "OOT 宽限期",
                   4: "非正版宽限期", 5: "通知模式", 6: "扩展宽限期"}


def ps_encode(script):
    """PowerShell -EncodedCommand（UTF-16LE base64），避免多层引号转义"""
    import base64
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _ps_query(script, timeout=30):
    """执行 PowerShell 查询并返回 stdout（查询类命令，不改动系统）。"""
    si = subprocess.STARTUPINFO()
    si.dwFlags = subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    r = subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", ps_encode(script)],
                       capture_output=True, text=True, timeout=timeout,
                       startupinfo=si, encoding="gbk", errors="ignore")
    return (r.stdout or "").strip()


def map_license_channel(desc):
    """Description 字段 → 授权渠道中文（官方渠道标识在 Description 里）。"""
    d = (desc or "").lower()
    if "oem_dm" in d: return "OEM 数字许可证"
    if "oem_slp" in d: return "OEM SLP"
    if "retail" in d: return "零售授权"
    if "kmsclient" in d or "volume_gvlk" in d: return "批量授权 GVLK"
    if "volume_mak" in d: return "批量授权 MAK"
    if "trace" in d: return "测试授权"
    return "未知渠道"


_ACT_LOCK = threading.Lock()     # SPP 授权查询必须串行：并发调用会拿到空结果
_ACT_CACHE = {"win": None, "office": None, "store": False, "ts": 0.0}
_ACT_CACHE_TTL = 300.0           # 授权状态分钟级变化，缓存 5 分钟足够


def query_windows_activation(force=False):
    """Windows 激活信息。返回 dict：edition/channel/status_code/status/partial/oem_key。
    注意：SPP 服务冷启动时 WMI 查询可达 60s+；且并发查询会返回空，必须持锁串行。"""
    with _ACT_LOCK:
        if (not force and _ACT_CACHE["win"] is not None
                and time.time() - _ACT_CACHE["ts"] < _ACT_CACHE_TTL):
            return dict(_ACT_CACHE["win"])
        info = {"edition": "-", "channel": "-", "status_code": -1, "status": "查询失败",
                "partial": "", "oem_key": "", "error": ""}
        rows = ""
        for attempt in (1, 2):   # 偶发空返回时重试一次
            try:
                rows = _ps_query(
                    "Get-CimInstance SoftwareLicensingProduct "
                    "-Filter \"ApplicationID='" + _WIN_APPID + "' AND PartialProductKey IS NOT NULL\" | "
                    "ForEach-Object { $_.Name + \"`t\" + $_.Description + \"`t\" + "
                    "$_.LicenseStatus + \"`t\" + $_.PartialProductKey }", timeout=90)
            except Exception as e:
                info["error"] = f"{type(e).__name__}: {e}"
                return info
            if rows:
                break
            time.sleep(2)
        if not rows:
            info["error"] = "WMI 无返回（SPP 服务可能正在初始化，稍后重试）"
            return info
        for line in rows.splitlines():
            parts = line.split("\t")
            if len(parts) >= 4 and "windows" in parts[0].lower():
                info["edition"] = (parts[0].replace("(R)", "").strip()
                                   .replace("  ", " "))[:48]
                info["channel"] = map_license_channel(parts[1])
                try:
                    info["status_code"] = int(parts[2])
                except ValueError:
                    info["status_code"] = -1
                info["status"] = _LICENSE_STATUS.get(info["status_code"], "未知")
                info["partial"] = parts[3].strip()
                info["error"] = ""
                break
        # 主板预埋 OEM 键（新机验收关键：有这颗键，重装联网即自动激活）
        try:
            key = _ps_query("Get-CimInstance SoftwareLicensingService | "
                            "Select-Object -ExpandProperty OA3xOriginalProductKey",
                            timeout=60)
            if key and "-" in key:
                info["oem_key"] = key.strip()
        except Exception:
            pass
        _ACT_CACHE["win"] = dict(info)
        _ACT_CACHE["ts"] = time.time()
        return info


def slmgr_xpr_text(timeout=40):
    """slmgr /xpr 原始输出（"计算机已永久激活" 或到期时间）。查询类，无需管理员。"""
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags = subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        r = subprocess.run(
            ["cscript", "//nologo",
             str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "slmgr.vbs"),
             "/xpr"],
            capture_output=True, text=True, timeout=timeout,
            startupinfo=si, encoding="gbk", errors="ignore")
        return " ".join((r.stdout or "").split())
    except Exception:
        return ""


def is_permanent_activated(xpr_text):
    """解析 /xpr 输出 → (是否永久, 说明)。"""
    t = xpr_text or ""
    if "永久" in t:
        return True, "永久激活"
    m = re.search(r"\d{4}/\d{1,2}/\d{1,2}", t)
    if m:
        return False, f"限期授权 · 至 {m.group(0)}"
    return None, (t[:40] or "未知")


def query_office_activation(force=False):
    """Office 各产品激活状态列表。返回 (rows, store_office)。与 Windows 查询共用
    串行锁与缓存（SPP 并发查询会返回空）。"""
    with _ACT_LOCK:
        if (not force and _ACT_CACHE["office"] is not None
                and time.time() - _ACT_CACHE["ts"] < _ACT_CACHE_TTL):
            return list(_ACT_CACHE["office"]), _ACT_CACHE["store"]
        rows = []
        raw = ""
        for attempt in (1, 2):
            try:
                raw = _ps_query(
                    "Get-CimInstance SoftwareLicensingProduct "
                    "-Filter \"ApplicationID='" + _OFFICE_APPID + "' AND PartialProductKey IS NOT NULL\" | "
                    "ForEach-Object { $_.Name + \"`t\" + $_.Description + \"`t\" + "
                    "$_.LicenseStatus + \"`t\" + $_.PartialProductKey }", timeout=90)
            except Exception:
                raw = ""
            if raw:
                break
            time.sleep(2)
        seen = {}
        for line in raw.splitlines():
            parts = line.split("\t")
            if len(parts) < 4 or not parts[0].strip():
                continue
            try:
                code = int(parts[2])
            except ValueError:
                code = -1
            item = {"name": pretty_office_name(parts[0]),
                    "channel": map_license_channel(parts[1]),
                    "status": _LICENSE_STATUS.get(code, "未知"),
                    "status_code": code, "partial": parts[3].strip()}
            old = seen.get(item["name"])
            # 同名产品取状态更优的一条（1=已激活优先）
            if old is None or (item["status_code"] == 1):
                seen[item["name"]] = item
        rows = list(seen.values())
        store_office = False
        try:
            store_office = bool(_ps_query(
                "Get-AppxPackage Microsoft.Office.Desktop | "
                "Select-Object -First 1 -ExpandProperty Name", timeout=20))
        except Exception:
            pass
        _ACT_CACHE["office"] = list(rows)
        _ACT_CACHE["store"] = store_office
        return rows, store_office


def pretty_office_name(raw):
    """SoftwareLicensingProduct 的 Name → 可读产品名。"""
    n = raw or ""
    low = n.lower()
    if "o365" in low or "365" in low:
        base = "Microsoft 365 应用"
    else:
        m = re.search(r"Office\s?\d{2,4}", n)
        base = m.group(0) if m else (n.split(",")[0].strip()[:20] or "Office")
    if "visio" in low:
        base = "Visio · " + base
    elif "project" in low:
        base = "Project · " + base
    if "proplus" in low:
        base += " 专业增强版"
    elif "standard" in low:
        base += " 标准版"
    elif "homebusiness" in low:
        base += " 小型企业版"
    elif "homestudent" in low:
        base += " 家庭学生版"
    elif "professional" in low:
        base += " 专业版"
    return base


# ═══════════════════════════════════════════
# 新机配置（预装体检 / winget 装机 / 隐私快设，均为官方渠道）
# ═══════════════════════════════════════════

# 试用/推广类预装关键词（只标明显推广件，不误伤厂商驱动工具）
_OEM_BLOAT_KEYWORDS = [
    ("mcafee", "McAfee 杀毒试用"),
    ("wildtangent", "WildTangent 游戏推广"),
    ("norton", "Norton 安全试用"),
    ("avast free", "Avast 免费版推广"),
    ("avg antivirus", "AVG 免费版推广"),
    ("microsoft teams 个人", "Teams 个人版预装"),
]


def match_oem_bloat(apps):
    """从已安装软件列表（_scan_reg 格式）筛出推广/试用类预装。"""
    out = []
    for a in apps:
        nl = str(a.get("name", "")).lower()
        for kw, why in _OEM_BLOAT_KEYWORDS:
            if kw in nl:
                out.append((a, why))
                break
    return out


WINGET_APPS = [
    ("7-Zip 压缩", "7zip.7zip"), ("Chrome 浏览器", "Google.Chrome"),
    ("微信", "Tencent.WeChat"), ("QQ", "Tencent.QQ"),
    ("Steam", "Valve.Steam"), ("VLC 播放器", "VideoLAN.VLC"),
    ("VS Code", "Microsoft.VisualStudioCode"), ("网易云音乐", "NetEase.CloudMusic"),
    ("百度网盘", "Baidu.BaiduNetdisk"), ("Everything 搜索", "voidtools.Everything"),
]


def parse_winget_upgrades(text):
    """解析 `winget upgrade` 表格输出 -> [{id,name,cur,avail}]。
    中英文表头均可（列名不参与解析，只按 2+ 空格分列 + Id 形态校验）。"""
    rows = []
    for line in (text or "").splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        if set(line.strip()) <= {"-", " ", "─", "—"}:
            continue   # 分隔线
        parts = [p.strip() for p in re.split(r"\s{2,}", line.strip()) if p.strip()]
        if len(parts) < 4:
            continue   # 表头/提示行通常不足 4 列
        joined = " ".join(parts).lower()
        if not re.search(r"\d+\.\d", joined) and any(
                h in joined for h in ("版本", "可用", "version", "available", "标识")):
            continue
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", parts[1]):
            continue
        rows.append({"name": parts[0], "id": parts[1],
                     "cur": parts[2] if len(parts) > 2 else "-",
                     "avail": parts[3] if len(parts) > 3 else "-"})
    return rows


def check_winget():
    """winget（应用安装器）可用性，返回版本串或空。"""
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags = subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        r = subprocess.run(["winget", "--version"], capture_output=True, text=True,
                           timeout=15, startupinfo=si, encoding="gbk", errors="ignore")
        return (r.stdout or "").strip()
    except Exception:
        return ""


# ═══════════════════════════════════════════
# 硬件验机（驱动异常检查 / 系统还原点）
# ═══════════════════════════════════════════

_CMC_ERRORS = {
    1: "设备配置异常", 3: "驱动损坏或资源不足", 10: "设备无法启动",
    12: "资源不足", 14: "需要重启", 18: "需重装驱动", 22: "设备已被禁用",
    24: "设备不存在（幽灵设备）", 28: "未安装驱动", 31: "驱动运行失败",
    37: "驱动初始化失败", 39: "驱动文件缺失或损坏", 43: "设备已停止",
    45: "设备未连接",
}


def scan_driver_issues():
    """驱动健康检查：问题设备枚举 + 显卡驱动信息（只读，无需管理员）。"""
    out = {"problems": [], "gpus": []}
    try:
        raw = _ps_query(
            "Get-CimInstance Win32_PnPEntity -Filter \"ConfigManagerErrorCode <> 0\" | "
            "ForEach-Object { $_.Name + \"`t\" + $_.ConfigManagerErrorCode }", timeout=60)
        for line in raw.splitlines():
            parts = line.rsplit("\t", 1)
            if len(parts) != 2:
                continue
            name, code = parts[0].strip(), parts[1].strip()
            try:
                code_i = int(code)
            except ValueError:
                continue
            if code_i == 0:
                continue
            out["problems"].append({
                "name": name[:70], "code": code_i,
                "why": _CMC_ERRORS.get(code_i, f"错误码 {code_i}")})
    except Exception:
        pass
    try:
        raw = _ps_query(
            "Get-CimInstance Win32_VideoController | "
            "ForEach-Object { $_.Name + \"`t\" + $_.DriverVersion + \"`t\" + "
            "$_.DriverDate }", timeout=45)
        for line in raw.splitlines():
            parts = line.split("\t")
            if not parts or not parts[0].strip():
                continue
            date = parts[2].strip() if len(parts) > 2 else "-"
            m = re.match(r"(\d{4}-\d{2}-\d{2})", date)
            out["gpus"].append({"name": parts[0].strip()[:60],
                                "ver": parts[1].strip() if len(parts) > 1 else "-",
                                "date": m.group(1) if m else date})
    except Exception:
        pass
    return out


def _read_elevated_log(log_path):
    """回读提权脚本写下的日志，按 BOM 自动判定编码。

    PowerShell 的 `Out-File -Encoding unicode` 写的是 **UTF-16LE + BOM**。
    早先这里固定按 gbk 读，而 gbk 会把 0x00 当成合法单字节保留下来，
    于是每行变成 '\\x00C\\x00R\\x00E\\x00A\\x00T\\x00E\\x00D\\x00=' 这种样子，
    startswith("CREATED=") / ("RP: ") / ("COUNT=") 永远匹配不上 ——
    还原点功能整体失效（列表恒空、创建恒报失败）。
    无 BOM 时退回 gbk，老日志仍可读。
    """
    path = Path(log_path)
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le", errors="ignore")
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", errors="ignore")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="ignore")
    return raw.decode("gbk", errors="ignore")


def _run_elevated_ps(ps_body, log_path, timeout=300):
    """管理员权限运行 PowerShell 脚本并回读日志。
    返回日志文本；UAC 被取消、脚本没跑起来或异常时返回 None。
    ps_body 必须纯 ASCII（写临时 .ps1 规避编码问题）；log_path 用正斜杠。"""
    script = Path(tempfile.gettempdir()) / "utb_elevated.ps1"
    script.write_text(ps_body, encoding="ascii", errors="ignore")
    try:
        Path(log_path).unlink(missing_ok=True)
    except Exception:
        pass
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             'Start-Process powershell -Verb RunAs -Wait -ArgumentList '
             '\'-NoProfile -ExecutionPolicy Bypass -File "' + str(script).replace("/", "/") + '"\''],
            capture_output=True, timeout=timeout)
    except Exception:
        return None
    # 日志文件没生成 = 提权脚本根本没执行（用户取消了 UAC），不能当成"执行成功"
    if not Path(log_path).exists():
        return None
    return _read_elevated_log(log_path)


def create_restore_point(desc_ascii):
    """创建系统还原点（官方 Checkpoint-Computer，需 UAC 管理员确认）。
    Win11 默认 24h 内会静默跳过——先用注册表把频率限制归零，再以前后数量差判定。"""
    log = Path(tempfile.gettempdir()) / "utb_rp.txt"
    log_ps = str(log).replace("\\", "/")
    body = (
        "$ErrorActionPreference='Continue'\n"
        "try { New-ItemProperty -Path 'HKLM:/SOFTWARE/Microsoft/Windows NT/CurrentVersion/SystemRestore' "
        "-Name 'SystemRestorePointCreationFrequency' -Value 0 -PropertyType DWord -Force | Out-Null } catch {}\n"
        "$before = (Get-ComputerRestorePoint -ErrorAction SilentlyContinue | Measure-Object).Count\n"
        "Checkpoint-Computer -Description '" + desc_ascii + "' -RestorePointType 'MODIFY_SETTINGS'\n"
        "Start-Sleep -Seconds 2\n"
        "$after = (Get-ComputerRestorePoint -ErrorAction SilentlyContinue | Measure-Object).Count\n"
        "'CREATED=' + $after + '-' + $before | Out-File -FilePath '" + log_ps + "' -Encoding unicode\n"
        "Get-ComputerRestorePoint -ErrorAction SilentlyContinue | "
        "Select-Object -Last 5 | ForEach-Object { "
        "'RP: ' + $_.CreationTime + '  ' + $_.Description } | "
        "Out-File -FilePath '" + log_ps + "' -Append -Encoding unicode\n"
    )
    out = _run_elevated_ps(body, log)
    if out is None:
        return False, "已取消或失败（需要管理员权限）"
    created = False
    for line in out.splitlines():
        if line.startswith("CREATED="):
            try:
                a, b = line.split("=", 1)[1].split("-")
                created = int(a) > int(b)
            except Exception:
                pass
    if created:
        return True, "还原点创建成功"
    return True, "命令已执行，但未新建还原点（系统策略限制或已存在）"


def list_restore_points():
    """列出最近还原点（需管理员；失败返回 (None, err)）。"""
    log = Path(tempfile.gettempdir()) / "utb_rp_list.txt"
    log_ps = str(log).replace("\\", "/")
    body = (
        "Get-ComputerRestorePoint -ErrorAction SilentlyContinue | "
        "Sort-Object CreationTime | Select-Object -Last 20 | ForEach-Object { "
        "'RP: ' + $_.CreationTime + '  ' + $_.Description } | "
        "Out-File -FilePath '" + log_ps + "' -Encoding unicode\n"
        "'COUNT=' + (Get-ComputerRestorePoint -ErrorAction SilentlyContinue | Measure-Object).Count | "
        "Out-File -FilePath '" + log_ps + "' -Append -Encoding unicode\n"
    )
    out = _run_elevated_ps(body, log)
    if out is None:
        return None, "已取消或失败（需要管理员权限）"
    points, total = [], "-"
    for line in out.splitlines():
        if line.startswith("RP: "):
            points.append(line[4:].strip())
        elif line.startswith("COUNT="):
            total = line.split("=", 1)[1]
    return points, total


# ═══════════════════════════════════════════
# 文件占用查询（Windows Restart Manager 官方 API）
# ═══════════════════════════════════════════

def find_file_locks(path):
    """查询哪些进程占用了文件 → (locks, err)。
    locks: [{"pid","name","type","status"}]。走系统 Restart Manager，
    与「文件被另一个程序占用」弹窗用的是同一套机制。"""
    import ctypes
    from ctypes import wintypes
    rtm = ctypes.WinDLL("rstrtmgr")

    class RM_UNIQUE_PROCESS(ctypes.Structure):
        _fields_ = [("dwProcessId", wintypes.DWORD),
                    ("ProcessStartTime", wintypes.FILETIME)]

    class RM_PROCESS_INFO(ctypes.Structure):
        _fields_ = [("Process", RM_UNIQUE_PROCESS),
                    ("strAppName", ctypes.c_wchar * 257),
                    ("strServiceShortName", ctypes.c_wchar * 63),
                    ("ApplicationType", ctypes.c_int),
                    ("AppStatus", ctypes.c_ulong),
                    ("TSSessionId", ctypes.c_ulong),
                    ("bRestartable", wintypes.BOOL)]

    out = []
    sess = ctypes.c_uint(0)
    key = ctypes.create_unicode_buffer(33)   # CCH_RM_SESSION_KEY+1
    if rtm.RmStartSession(ctypes.byref(sess), 0, key) != 0:
        return [], "RmStartSession 失败"
    try:
        arr = (ctypes.c_wchar_p * 1)(str(path))
        if rtm.RmRegisterResources(sess, 1,
                                   ctypes.cast(arr, ctypes.POINTER(ctypes.c_wchar_p)),
                                   0, None, 0, None) != 0:
            return [], "RmRegisterResources 失败"
        needed = ctypes.c_uint(0)
        count = ctypes.c_uint(0)
        reboot = ctypes.c_uint(0)
        rtm.RmGetList(sess, ctypes.byref(needed), ctypes.byref(count), None,
                      ctypes.byref(reboot))
        if needed.value == 0:
            return [], ""   # 无占用
        procs = (RM_PROCESS_INFO * needed.value)()
        count.value = needed.value
        if rtm.RmGetList(sess, ctypes.byref(count), ctypes.byref(needed), procs,
                         ctypes.byref(reboot)) != 0:
            return [], "RmGetList 失败"
        types = {0: "未知应用", 1: "主窗口应用", 2: "后台任务", 3: "Windows 服务",
                 1000: "普通应用"}
        for i in range(count.value):
            pi = procs[i]
            out.append({"pid": pi.Process.dwProcessId,
                        "name": pi.strAppName or "?",
                        "type": types.get(pi.ApplicationType, f"类型{pi.ApplicationType}"),
                        "status": "标记可重启" if pi.bRestartable else "运行中"})
        return out, ""
    finally:
        rtm.RmEndSession(sess)


# 隐私快设：全部为微软文档化的用户级设置（HKCU），可随时在系统设置里改回
_PRIVACY_TOGGLES = [
    {"id": "adid", "label": "关闭广告 ID（应用不得用广告标识跟踪）",
     "paths": [(r"Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo",
                "Enabled")]},
    {"id": "tailored", "label": "关闭定制体验（不用诊断数据做个性化推荐）",
     "paths": [(r"Software\Microsoft\Windows\CurrentVersion\Privacy",
                "TailoredExperiencesWithDiagnosticDataEnabled")]},
    {"id": "suggestions", "label": "关闭系统推广与建议内容（开始菜单/锁屏弹推荐）",
     "paths": [(r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager",
                "SystemPaneSuggestionsEnabled"),
               (r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager",
                "SilentInstalledAppsEnabled"),
               (r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager",
                "SubscribedContent-338388Enabled"),
               (r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager",
                "SubscribedContent-338389Enabled"),
               (r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager",
                "SubscribedContent-353698Enabled")]},
    {"id": "spotlight", "label": "关闭锁屏 Windows 聚焦",
     "paths": [(r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager",
                "RotatingLockScreenOverlayEnabled"),
               (r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager",
                "SubscribedContent-338387Enabled")]},
]


def privacy_toggle_state(tid):
    """读取某隐私项当前是否已按工具箱口径关闭。"""
    import winreg
    for t in _PRIVACY_TOGGLES:
        if t["id"] != tid:
            continue
        off_cnt = 0
        for sub, name in t["paths"]:
            if _reg_read(winreg.HKEY_CURRENT_USER, sub, name) == 0:
                off_cnt += 1
        return off_cnt == len(t["paths"]) and off_cnt > 0
    return False


def privacy_toggle_apply(tid, off):
    """应用/还原隐私项（off=True 关闭该功能；False 删除值回到系统默认）。"""
    import winreg
    for t in _PRIVACY_TOGGLES:
        if t["id"] != tid:
            continue
        for sub, name in t["paths"]:
            try:
                if off:
                    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, sub, 0,
                                            winreg.KEY_SET_VALUE) as k:
                        winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, 0)
                else:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub, 0,
                                        winreg.KEY_SET_VALUE) as k:
                        winreg.DeleteValue(k, name)
            except OSError:
                pass
        return True
    return False


# ═══════════════════════════════════════════
# 模块基类
# ═══════════════════════════════════════════

class BaseModule:
    name = "" ; label = "" ; icon = "" ; color = CYAN
    def __init__(self, app):
        self.app = app; self.root = app.root; self.body = None; self._q = queue.Queue()
    def build(self): pass
    def start(self): pass
    def stop(self): pass
    def on_show(self): pass

    def _mkbtn(self, parent, text, cmd, color=CYAN, side="left"):
        """统一次级按钮：PANEL2 底 + 主题色文字 + 悬停提亮（各模块共用，避免风格漂移）"""
        btn = tk.Button(parent, text=text, bg=PANEL2, fg=color,
                        font=(FONT_UI, 9), bd=0, relief="flat",
                        cursor="hand2", command=cmd)
        btn.pack(side=side, padx=(0, 6), pady=3)
        btn.bind("<Enter>", lambda e=None, b=btn: b.config(bg=PANEL3))
        btn.bind("<Leave>", lambda e=None, b=btn: b.config(bg=PANEL2))
        return btn


# ═══════════════════════════════════════════
# 通用动画工具（模块切换渐入 + 状态呼吸）
# ═══════════════════════════════════════════

def fade_in(widget, steps=8, delay=18, on_done=None):
    """模块内容渐入动画：从背景色插值到【原始】前景色。
    注意：必须在开始时快照原始颜色——若每步重读当前颜色再插值，
    颜色会累积漂移最终收敛到背景色（旧版 BUG）。"""
    try:
        children = widget.winfo_children()
    except Exception:
        return
    if not children:
        if on_done: on_done()
        return
    # 快照：只处理有 #rrggbb 前景色的直接子控件（Frame 等无 fg 的自动跳过）
    originals = []
    for w in children:
        try:
            fg = w.cget("fg")
            if isinstance(fg, str) and fg.startswith("#") and len(fg) == 7:
                originals.append((w, int(fg[1:3], 16), int(fg[3:5], 16), int(fg[5:7], 16)))
        except Exception:
            pass
    if not originals:
        if on_done: on_done()
        return
    total = steps
    def _step(n):
        if n > total:
            # 结束时精确还原原始颜色，杜绝累积误差
            for w, r, g, b in originals:
                try: w.config(fg="#%02x%02x%02x" % (r, g, b))
                except Exception: pass
            if on_done: on_done()
            return
        f = n / total
        for w, r, g, b in originals:
            try:
                w.config(fg="#%02x%02x%02x" % (
                    int(BG_R + (r - BG_R) * f),
                    int(BG_G + (g - BG_G) * f),
                    int(BG_B + (b - BG_B) * f)))
            except Exception:
                pass
        try:
            widget.update_idletasks()
            widget.after(delay, lambda: _step(n + 1))
        except Exception:
            if on_done: on_done()
    _step(1)


def pulse_label(label, base_colors=(GREEN, YELLOW), period_ms=1800):
    """状态标签呼吸动画（绿↔黄缓动，循环）"""
    state = {"t": 0.0}
    running = [True]
    def _tick():
        if not running[0] or not label.winfo_exists(): return
        import math
        state["t"] += 0.12
        f = (math.sin(state["t"]) + 1) / 2  # 0..1
        try:
            c1, c2 = base_colors
            r = int((int(c1[1:3], 16) + (int(c2[1:3], 16) - int(c1[1:3], 16)) * f))
            g = int((int(c1[3:5], 16) + (int(c2[3:5], 16) - int(c1[3:5], 16)) * f))
            b = int((int(c1[5:7], 16) + (int(c2[5:7], 16) - int(c1[5:7], 16)) * f))
            label.config(fg="#%02x%02x%02x" % (r, g, b))
            label.after(period_ms // 15, _tick)
        except Exception:
            running[0] = False
    _tick()
    def _stop():
        running[0] = False
    return _stop


# ═══════════════════════════════════════════
# 深色对话框（替代系统 messagebox——浅灰系统弹窗与深色 UI 割裂、观感生硬）
# ═══════════════════════════════════════════

_DIALOG_ICONS = {
    "info":     ("i", CYAN),
    "question": ("?", CYAN),
    "success":  ("✓", GREEN),
    "warn":     ("!", YELLOW),
    "error":    ("✕", RED),
}


class _ScrollArea:
    """弹窗用的纵向滚动容器：内容放进 `.inner`。

    行为要点：
    · 内容一屏放得下时自动隐藏滚动条，放不下才出现；
    · 滚轮只在指针位于本区域内时生效，且遇到 Treeview/Text/Listbox 等
      自带滚动的控件会主动让行，避免和它们的滚动打架；
    · 滚轮绑定挂在所属顶层窗口上，弹窗销毁即随之失效，不污染主窗口。
    """

    def __init__(self, parent, bg=None):
        bg = bg or BG
        self.outer = tk.Frame(parent, bg=bg)
        self.canvas = tk.Canvas(self.outer, bg=bg, highlightthickness=0, bd=0,
                                takefocus=0)
        self.vsb = ttk.Scrollbar(self.outer, orient="vertical",
                                 command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.inner,
                                                anchor="nw")
        self._pending = None
        self._active = True
        self._bar = False
        self.inner.bind("<Configure>", self._schedule, add="+")
        self.canvas.bind("<Configure>", self._schedule, add="+")
        try:
            self._owner = parent.winfo_toplevel()
            self._owner.bind("<MouseWheel>", self._wheel, add="+")
        except Exception:
            self._owner = None
        self._schedule()

    def pack(self, **kwargs):
        self.outer.pack(**kwargs)
        return self.outer

    def grid(self, **kwargs):
        self.outer.grid(**kwargs)
        return self.outer

    # ── 布局 ──
    def _schedule(self, event=None):
        if not self._active or self._pending is not None:
            return
        try:
            self._pending = self.canvas.after_idle(self._layout)
        except Exception:
            self._pending = None

    def _layout(self):
        self._pending = None
        if not self._active:
            return
        try:
            if not self.canvas.winfo_exists():
                return
            width = max(1, self.canvas.winfo_width())
            height = max(1, self.canvas.winfo_height())
            content = max(height, self.inner.winfo_reqheight())
            self.canvas.itemconfigure(self._window, width=width, height=content)
            self.canvas.configure(scrollregion=(0, 0, width, content))
        except Exception:
            return
        self._sync_bar(content, height)

    def _sync_bar(self, content, height):
        need = content > height + 1
        if need == self._bar:
            return
        self._bar = need
        try:
            if need:
                self.vsb.pack(side="right", fill="y", before=self.canvas)
            else:
                self.vsb.pack_forget()
        except Exception:
            pass

    # ── 滚轮 ──
    def _wheel(self, event):
        if not self._active or not getattr(event, "delta", 0):
            return
        try:
            node = self.canvas.winfo_containing(event.x_root, event.y_root)
        except Exception:
            return
        while node is not None and node not in (self.inner, self.canvas):
            if node.winfo_class() in ("Treeview", "Text", "Listbox", "Canvas"):
                return   # 自带滚动的控件优先，别抢它的滚轮
            node = node.master
        if node is None:
            return
        try:
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        except Exception:
            return
        return "break"


def _dark_dialog(parent, title, msg, kind, buttons, btn_colors=None, default=0):
    """统一深色模态弹窗。返回被点按钮下标（点 X / Esc 视为最后一个按钮）。"""
    try:
        cand = parent if parent is not None else getattr(tk, "_default_root", None)
        owner = cand if (cand is not None and cand.winfo_exists()) else None
    except Exception:
        owner = None
    if owner is None:   # 无窗口环境（自动化测试）兜底
        print(f"[{title}] {msg}")
        return len(buttons) - 1

    win = tk.Toplevel(owner)
    win.title(title)
    win.configure(bg=PANEL)
    win.resizable(False, False)
    try:
        win.transient(owner.winfo_toplevel())
    except Exception:
        pass

    result = {"idx": len(buttons) - 1}

    def _press(i):
        result["idx"] = i
        try:
            win.grab_release()
        except Exception:
            pass
        win.destroy()

    # 按钮行先 pack 到底部：消息再长也不会把按钮挤出可视区
    # （旧版按钮最后 pack，长消息把窗口顶到超出屏幕，按钮既看不到也滚不到）
    btn_row = tk.Frame(win, bg=PANEL)
    btn_row.pack(side="bottom", fill="x", padx=24, pady=(10, 18))
    specs = btn_colors or ([CYAN] + [TEXT2] * (len(buttons) - 1))
    for i, (txt, cl) in enumerate(zip(buttons, specs)):
        b = tk.Button(btn_row, text=txt, bg=PANEL3 if i == default else PANEL2,
                      fg=cl, font=(FONT_UI, 9, "bold"), bd=0, relief="flat",
                      cursor="hand2", width=10, takefocus=0,
                      command=lambda i=i: _press(i))
        b.pack(side="right", padx=(8, 0))
        b.bind("<Enter>", lambda e, bb=b, ii=i: bb.config(bg=PANEL3))
        b.bind("<Leave>", lambda e, bb=b, ii=i: bb.config(
            bg=PANEL3 if ii == default else PANEL2))
    win.bind("<Return>", lambda e: _press(default))
    win.bind("<Escape>", lambda e: _press(len(buttons) - 1))
    win.protocol("WM_DELETE_WINDOW", lambda: _press(len(buttons) - 1))

    sym, tint = _DIALOG_ICONS.get(kind, ("i", CYAN))
    body = tk.Frame(win, bg=PANEL)
    body.pack(fill="both", expand=True, padx=24, pady=(20, 4))
    ic = tk.Canvas(body, bg=PANEL, width=42, height=42, highlightthickness=0)
    ic.grid(row=0, column=0, padx=(0, 14), sticky="nw")
    ic.create_oval(4, 4, 38, 38, outline=tint, width=2)
    ic.create_text(21, 21, text=sym, fill=tint, font=(FONT_UI, 15, "bold"))
    # 消息放进可滚动区并限高：超长文本（报错堆栈等）不会顶出屏幕
    area = _ScrollArea(body, bg=PANEL)
    area.outer.grid(row=0, column=1, sticky="nsew")
    body.grid_columnconfigure(1, weight=1)
    tk.Label(area.inner, text=msg, bg=PANEL, fg=TEXT, font=(FONT_UI, 10),
             justify="left", wraplength=400, anchor="nw").pack(
        anchor="nw", fill="x")
    win.update_idletasks()
    try:
        msg_h = area.inner.winfo_reqheight()
        msg_w = max(240, min(area.inner.winfo_reqwidth(), 420))
        cap = max(140, win.winfo_screenheight() - 260)
        area.canvas.configure(width=msg_w, height=min(msg_h, cap))
    except Exception:
        pass

    win.update_idletasks()
    enable_dark_title_bar(win)
    # 居中于父窗口（越界收敛到屏幕内）
    try:
        px, py = owner.winfo_rootx(), owner.winfo_rooty()
        pw, ph = owner.winfo_width(), owner.winfo_height()
        ww, wh = win.winfo_width(), win.winfo_height()
        x = max(8, min(px + (pw - ww) // 2, win.winfo_screenwidth() - ww - 8))
        y = max(8, min(py + (ph - wh) // 3, win.winfo_screenheight() - wh - 8))
        win.geometry(f"+{x}+{y}")
    except Exception:
        pass
    try:
        # grab_set 对未映射窗口会抛 "grab failed: window not viewable"，
        # 必须先 deiconify+update 让窗口真实显示后再抓取模态
        win.deiconify()
        win.update()
        win.grab_set()
        win.wait_window()
    except Exception:
        pass
    return result["idx"]


def show_info(title, msg, parent=None):
    _dark_dialog(parent, title, msg, "info", ("确定",))


def show_success(title, msg, parent=None):
    _dark_dialog(parent, title, msg, "success", ("确定",))


def show_warning(title, msg, parent=None):
    _dark_dialog(parent, title, msg, "warn", ("确定",))


def show_error(title, msg, parent=None):
    _dark_dialog(parent, title, msg, "error", ("确定",))


def ask_yesno(title, msg, parent=None, danger=False):
    """是/否确认。danger=True 走红色警示样式（删除/卸载类确认）。"""
    if danger:
        return _dark_dialog(parent, title, msg, "warn", ("确认", "取消"),
                            btn_colors=[RED, TEXT2]) == 0
    return _dark_dialog(parent, title, msg, "question", ("确定", "取消")) == 0


# ═══════════════════════════════════════════
# 模块：首页
# ═══════════════════════════════════════════

class HomeModule(BaseModule):
    name = "home"; label = "首页"; icon = "🏠"; color = CYAN

    def build(self):
        body = self.body
        # 欢迎
        banner = tk.Frame(body, bg=PANEL)
        banner.pack(fill="x", padx=20, pady=(18, 10))
        tk.Label(banner, text="👋 欢迎回来", bg=PANEL, fg=CYAN,
                 font=(FONT_UI, 18, "bold")).pack(anchor="w", pady=(8, 2))
        tk.Label(banner, text=f"{APP_NAME}  {APP_VERSION}  ·  {platform.node()}",
                 bg=PANEL, fg=TEXT2, font=(FONT_UI, 8)).pack(anchor="w")

        # 系统概况
        info = get_sys_info()
        stat_frame = tk.Frame(body, bg=PANEL2)
        stat_frame.pack(fill="x", padx=20, pady=(0, 12))
        labels = [("💻 CPU", info["CPU"]), ("🧠 内存", info["内存"]),
                  ("💿 系统", info["操作系统"]), ("⚡ 内核", info["内核"])]
        for i, (lb, val) in enumerate(labels):
            row = tk.Frame(stat_frame, bg=PANEL2)
            row.pack(fill="x", pady=(1, 0))
            tk.Label(row, text=lb, bg=PANEL2, fg=CYAN,
                     font=(FONT_UI, 10, "bold"), anchor="w").pack(side="left", padx=(12, 0))
            tk.Label(row, text=val[:50], bg=PANEL2, fg=TEXT,
                     font=(FONT_MONO, 9), anchor="w").pack(side="left", padx=(8, 0), fill="x", expand=True)

        # 功能导航
        tk.Label(body, text="◈ 功能导航", bg=BG, fg=CYAN,
                 font=(FONT_UI, 12, "bold")).pack(anchor="w", padx=(20, 0), pady=(4, 8))
        grid = tk.Frame(body, bg=BG)
        grid.pack(fill="both", expand=True, padx=20, pady=(0, 14))
        grid.grid_columnconfigure((0,1), weight=1)
        grid.grid_rowconfigure((0,1,2), weight=1)
        navs = [("🔧 硬件诊断", "hardware", CYAN,
                 "CPU / 内存 / GPU / 磁盘健康 / 进程 / 端口"),
                ("📋 剪贴板历史", "clipboard", GREEN,
                 "全局历史 · 搜索置顶 · 图片 OCR · 片段库"),
                ("🧹 空间清理", "space", PURPLE,
                 "垃圾扫描 · 空目录 · 大文件 · 文件占用"),
                ("📦 软件管家", "software", ORANGE,
                 "卸载 · winget 升级 · 预装体检 · 残留扫描"),
                ("🚀 快速启动", "launch", GREEN,
                 "常用程序 / 文件夹 / 网址一键直达"),
                ("🧾 新机验机", "verify", GREEN,
                 "整机配置 · 亮暗点 · 键盘 · 驱动 · 激活")]
        for i, (title, mod_name, clr, desc) in enumerate(navs):
            r, c = divmod(i, 2)
            card = tk.Frame(grid, bg=PANEL, highlightthickness=1,
                            highlightbackground=BORDER)
            card.grid(row=r, column=c, padx=6, pady=4, sticky="nsew")
            # 标题 + 一行说明：只有标题的卡片对第一次用的人等于没有信息
            title_lbl = tk.Label(card, text=title, bg=PANEL, fg=clr,
                                 font=(FONT_UI, 15, "bold"), cursor="hand2")
            title_lbl.pack(pady=(16, 2))
            desc_lbl = tk.Label(card, text=desc, bg=PANEL, fg=MUTED,
                                font=(FONT_UI, 8), cursor="hand2")
            desc_lbl.pack(pady=(0, 14))

            def _enter(_e=None, cd=card, cl=clr):
                cd.config(highlightbackground=cl)
                for w in (title_lbl, desc_lbl):
                    w.config(bg=PANEL2)

            def _leave(_e=None, cd=card):
                cd.config(highlightbackground=BORDER)
                for w in (title_lbl, desc_lbl):
                    w.config(bg=PANEL)

            # 整张卡片都可点（不只标题那一行）
            for w in (card, title_lbl, desc_lbl):
                w.bind("<Button-1>", lambda e, n=mod_name: self.app._switch(n))
                w.bind("<Enter>", _enter)
                w.bind("<Leave>", _leave)

    def start(self): pass
    def stop(self): pass
    def on_show(self): pass


# ═══════════════════════════════════════════
# 模块：硬件诊断
# ═══════════════════════════════════════════

class HardwareModule(BaseModule):
    name = "hardware"; label = "硬件诊断"; icon = "🔧"; color = YELLOW

    def build(self):
        body = self.body

        # ═══ 顶部状态栏 ═══
        top = tk.Frame(body, bg=PANEL)
        top.pack(fill="x", padx=20, pady=(12, 8))
        top.pack_propagate(False)
        tk.Label(top, text="◈ 硬件诊断", bg=PANEL, fg=CYAN,
                 font=(FONT_UI, 14, "bold")).pack(side="left", padx=(4, 12))
        self.status_icon = tk.Label(top, text="◐", bg=PANEL,
                                    fg=GREEN, font=(FONT_MONO, 14, "bold"))
        self.status_icon.pack(side="left", padx=(0, 12))
        # 状态图标呼吸动画（绿↔金缓动循环）
        try:
            pulse_label(self.status_icon, (GREEN, CYAN), 2000)
        except Exception:
            pass
        self.up_lbl = tk.Label(top, text="", bg=PANEL, fg=TEXT2,
                               font=(FONT_MONO, 8), anchor="e")
        self.up_lbl.pack(side="right")
        # 开机时长：此前这个标签建好后再没被赋过值，顶栏永远空着一块
        try:
            up = int(time.time() - psutil.boot_time())
            self.up_lbl.config(text=f"开机 {up // 3600}h{(up % 3600) // 60}m")
        except Exception:
            pass
        port_btn = tk.Button(top, text="🔌 端口", bg=PANEL2, fg=CYAN,
                             font=(FONT_UI, 8), bd=0, relief="flat", cursor="hand2",
                             command=self._port_dialog)
        port_btn.pack(side="right", padx=(0, 8))
        exp_btn = tk.Button(top, text="⬇ 报告", bg=PANEL2, fg=CYAN,
                            font=(FONT_UI, 8), bd=0, relief="flat", cursor="hand2",
                            command=self._export_report)
        exp_btn.pack(side="right", padx=(0, 8))

        # ═══ 仪表盘行：CPU 环 / 内存 环 / 网络流速 / 温度·频率（AIDA64 传感器面板风） ═══
        gauge_row = tk.Frame(body, bg=BG)
        gauge_row.pack(fill="x", padx=20, pady=(0, 8))
        gauge_row.grid_columnconfigure((0, 1, 2, 3), weight=1)

        def _card(parent, title):
            card = tk.Frame(parent, bg=PANEL)
            card.grid(row=0, column=0, sticky="nsew")
            tk.Label(card, text=title, bg=PANEL, fg=TEXT2,
                     font=(FONT_UI, 9, "bold")).pack(anchor="w", padx=12, pady=(8, 0))
            return card

        # CPU 环形仪表
        cpu_card = _card(gauge_row, "🖥 CPU 负载")
        cpu_card.grid(row=0, column=0, padx=3, sticky="nsew")
        self.cpu_ring = tk.Canvas(cpu_card, bg=PANEL, height=120, highlightthickness=0)
        self.cpu_ring.pack(fill="x", padx=6, pady=(0, 6))

        # 内存环形仪表
        mem_card = _card(gauge_row, "💾 内存")
        mem_card.grid(row=0, column=1, padx=3, sticky="nsew")
        self.mem_ring = tk.Canvas(mem_card, bg=PANEL, height=120, highlightthickness=0)
        self.mem_ring.pack(fill="x", padx=6, pady=(0, 6))

        # 网络流速卡（大数字 + 迷你双曲线）
        net_card = _card(gauge_row, "📡 网络流速")
        net_card.grid(row=0, column=2, padx=3, sticky="nsew")
        self.net_canvas = tk.Canvas(net_card, bg=PANEL, height=120, highlightthickness=0)
        self.net_canvas.pack(fill="x", padx=6, pady=(0, 6))

        # 温度·频率双迷你环
        tf_card = _card(gauge_row, "🌡 温度 · ⚡ 频率")
        tf_card.grid(row=0, column=3, padx=3, sticky="nsew")
        self.tf_canvas = tk.Canvas(tf_card, bg=PANEL, height=120, highlightthickness=0)
        self.tf_canvas.pack(fill="x", padx=6, pady=(0, 6))

        # 仪表动画状态（显示值平滑追踪目标值）
        self._cpu_t = 0; self._cpu_d = 0.0
        self._mem_t = 0; self._mem_d = 0.0
        self._cores_t = []; self._cores_d = []; self._cores_peak = []
        self._mem_gb = (0, 0)
        self._temp_str = "--"; self._freq_str = "--"
        self._temp_pct = 0; self._freq_pct = 0

        # ═══ 12 格硬件参数（2 行 × 6 列，每格 ≥160px 可读） ═══
        param_frame = tk.Frame(body, bg=PANEL)
        param_frame.pack(fill="x", padx=20, pady=(0, 8))
        self.param_grid = tk.Frame(param_frame, bg=PANEL)
        self.param_grid.pack(fill="x", padx=12, pady=(8, 8))
        self.param_grid.grid_columnconfigure(list(range(6)), weight=1)
        self.param_grid.grid_rowconfigure((0, 1), weight=1)
        self._sys_cells = {}
        self._extra_cells = {}
        param_items = [
            ("🎮", "GPU", PURPLE, "extra", "-"),
            ("💾", "显存", GREEN, "extra", "-"),
            ("⚡", "CPU频率", YELLOW, "extra", "-"),
            ("🌡", "CPU温度", RED, "extra", "-"),
            ("🌐", "IPv4", CYAN, "extra", "-"),
            ("🔒", "安全启动", ORANGE, "extra", "-"),
            ("🔧", "BIOS", CYAN, "extra", "-"),
            ("💿", "磁盘型号", PURPLE, "extra", "-"),
            ("🖥", "CPU", CYAN, "sys", "-"),
            ("💵", "内存", GREEN, "sys", "-"),
            ("📡", "操作系统", YELLOW, "sys", "-"),
            ("⚙", "内核", PURPLE, "sys", "-"),
        ]
        sys_info = get_sys_info()
        for i, (ic, lb, co, stype, default) in enumerate(param_items):
            r, c = divmod(i, 6)
            cell = tk.Frame(self.param_grid, bg=PANEL2)
            cell.grid(row=r, column=c, padx=1, pady=1, sticky="nsew")
            tk.Label(cell, text=f"{ic} {lb}", bg=PANEL2, font=(FONT_UI, 9),
                     fg=TEXT2).pack(anchor="w", padx=8, pady=(6, 1))
            val_text = default
            if stype == "sys":
                val_text = str(sys_info.get(lb, "-"))[:28]
            val = tk.Label(cell, text=val_text, bg=PANEL2, fg=TEXT,
                           font=(FONT_MONO, 9, "bold"), anchor="w")
            val.pack(anchor="w", fill="x", padx=8, pady=(0, 6))
            if stype == "sys":
                self._sys_cells[lb] = val
            else:
                self._extra_cells[lb] = val

        # ═══ 主视觉：全宽 CPU/内存 渐变波形（大图表，占页面上半主视觉） ═══
        hero = tk.Frame(body, bg=PANEL)
        hero.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(hero, text="◈ CPU / 内存 实时曲线", bg=PANEL, fg=CYAN,
                 font=(FONT_UI, 10, "bold")).pack(anchor="w", padx=12, pady=(8, 2))
        self._chart_h = 150
        self._chart_c = tk.Canvas(hero, bg=PANEL2, height=self._chart_h,
                                  highlightthickness=0)
        self._chart_c.pack(fill="x", padx=12, pady=(2, 4))
        # 图例
        legend = tk.Frame(hero, bg=PANEL)
        legend.pack(anchor="w", padx=12, pady=(0, 8))
        tk.Label(legend, text="── CPU", bg=PANEL, fg=CYAN,
                 font=(FONT_MONO, 8, "bold")).pack(side="left", padx=(0, 16))
        tk.Label(legend, text="── 内存", bg=PANEL, fg=GREEN,
                 font=(FONT_MONO, 8, "bold")).pack(side="left")

        # ═══ 图表区：各核 VU + 磁盘使用（两栏） ═══
        chart_frame = tk.Frame(body, bg=BG)
        chart_frame.pack(fill="x", padx=20, pady=(0, 8))
        chart_frame.grid_columnconfigure((0,), weight=3)
        chart_frame.grid_columnconfigure((1,), weight=2)

        # 左：各核 VU 表
        left = tk.Frame(chart_frame, bg=PANEL)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 2))
        li = tk.Frame(left, bg=PANEL)
        li.pack(fill="both", expand=True, padx=12, pady=(8, 8))
        tk.Label(li, text="◈ 各核负载（VU 表 · 峰值保持）", bg=PANEL, fg=CYAN,
                 font=(FONT_UI, 10, "bold")).pack(anchor="w", pady=(0, 3))
        self._core_labels = []
        nc = psutil.cpu_count() or 4
        cores_grid = tk.Frame(li, bg=PANEL2)
        cores_grid.pack(fill="x")
        cores_grid.grid_columnconfigure(list(range(nc)), weight=1)
        for i in range(nc):
            lb = tk.Label(cores_grid, text=f"C{i}", bg=PANEL2, fg=TEXT2,
                          font=(FONT_MONO, 7), anchor="center")
            lb.grid(row=0, column=i, padx=0, pady=1, sticky="nsew")
            self._core_labels.append(lb)
        self.cores_canvas = tk.Canvas(li, bg=PANEL2, height=44, highlightthickness=0)
        self.cores_canvas.pack(fill="x", pady=(2, 4))
        # 网络展示已上移至仪表盘行的网络卡（net_canvas）

        # 右：磁盘使用
        right = tk.Frame(chart_frame, bg=PANEL)
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        ri = tk.Frame(right, bg=PANEL)
        ri.pack(fill="both", expand=True, padx=12, pady=(8, 8))
        tk.Label(ri, text="◈ 磁盘使用", bg=PANEL, fg=CYAN,
                 font=(FONT_UI, 10, "bold")).pack(anchor="w", pady=(0, 6))
        self.disk_list = tk.Frame(ri, bg=PANEL)
        self.disk_list.pack(fill="x")

        # ═══ 进程表（带 CPU 热力条，负载一眼可见） ═══
        proc_box = tk.Frame(body, bg=BG)
        proc_box.pack(fill="both", expand=True, padx=20, pady=(0, 8))
        proc_head = tk.Frame(proc_box, bg=BG)
        proc_head.pack(fill="x", pady=(0, 3))
        tk.Label(proc_head, text="◈ 进程监控", bg=BG, fg=CYAN,
                 font=(FONT_UI, 11, "bold")).pack(side="left")
        self.proc_count_lbl = tk.Label(proc_head, text="", bg=BG, fg=TEXT2,
                                       font=(FONT_MONO, 8))
        self.proc_count_lbl.pack(side="right")
        proc_cols = [("名称", 240), ("PID", 55), ("CPU%", 60), ("CPU 负载", 130),
                     ("内存", 80), ("运行时间", 90), ("描述", 330)]
        self.procs_tree = ttk.Treeview(proc_box, columns=[c[0] for c in proc_cols],
                                       show="headings", height=8)
        self.procs_tree.pack(side="left", fill="both", expand=True)
        for lb, w in proc_cols:
            self.procs_tree.heading(lb, text=lb,
                command=lambda c=lb: self._sort_procs(c))
            self.procs_tree.column(lb, width=w, minwidth=40,
                                   anchor="w" if lb in ("名称", "描述") else "e")
        # 右键结束进程（之前只能看不能管）
        self.procs_tree.bind("<Button-3>", self._proc_menu)

        # ═══ 开机自启：卡片流（🚀 + 来源徽章，替代表格） ═══
        star_box = tk.Frame(body, bg=BG)
        star_box.pack(fill="both", expand=True, padx=20, pady=(0, 8))
        star_head = tk.Frame(star_box, bg=BG)
        star_head.pack(fill="x", pady=(0, 3))
        tk.Label(star_head, text="◈ 开机自启", bg=BG, fg=CYAN,
                 font=(FONT_UI, 11, "bold")).pack(side="left")
        self.star_count_lbl = tk.Label(star_head, text="", bg=BG, fg=TEXT2,
                                       font=(FONT_MONO, 8))
        self.star_count_lbl.pack(side="right")
        self.star_area = tk.Canvas(star_box, bg=PANEL, highlightthickness=0)
        self.star_vs = ttk.Scrollbar(star_box, orient="vertical",
                                      command=self.star_area.yview)
        self.star_area.configure(yscrollcommand=self.star_vs.set)
        self.star_vs.pack(side="right", fill="y")
        self.star_area.pack(side="left", fill="both", expand=True)
        # 窗口拉宽/缩窄后卡片按旧宽度绘制会让徽章与开关错位（v2.3 起的陈年表现级 bug）
        # → 宽度变化时防抖重绘
        self._star_last_w = 0

        def _on_star_resize(event=None):
            w = self.star_area.winfo_width()
            if w and w > 80 and abs(w - getattr(self, "_star_last_w", 0)) > 4 \
                    and self._cached_star:
                self._star_last_w = w
                self._render_star(self._cached_star)
        self.star_area.bind("<Configure>", _on_star_resize)

        self._ui_ready = False
        self._cached_hw = self._cached_extra = self._cached_disk = self._cached_proc = self._cached_star = None
        self._cached_health = None
    def _make_btn(self, parent, text, cmd, color=CYAN):
        btn = tk.Button(parent, text=text, bg=PANEL2, fg=color, font=(FONT_UI, 9),
                        bd=0, relief="flat", cursor="hand2", command=cmd)
        btn.pack(side="left", padx=(0, 6), pady=4)
        btn.bind("<Enter>", lambda e=None, b=btn: b.config(bg=PANEL3))
        btn.bind("<Leave>", lambda e=None, b=btn: b.config(bg=PANEL2))

    def start(self):
        self._stop_flag = threading.Event()
        self._stop_flag.clear()
        self._progress = 0
        self._cpu_hist = []
        self._mem_hist = []
        self._net_hist_down = []
        self._net_hist_up = []
        # 线程常驻不退出（stop 只让它休眠）：旧版用一次性标志 + stop 里 set 事件，
        # 导致切走页签后线程永久死亡、回来也不再恢复（监控冻结 BUG）
        if not (hasattr(self, "_live_thread") and self._live_thread.is_alive()):
            self._live_thread = threading.Thread(target=self._live_worker, daemon=True)
            self._live_thread.start()
        if not (hasattr(self, "_scan_thread") and self._scan_thread.is_alive()):
            self._scan_thread = threading.Thread(target=self._scan_loop, daemon=True)
            self._scan_thread.start()
        # 仪表动画帧循环（主线程 after，30fps 平滑追踪）
        if not getattr(self, "_gauge_started", False):
            self._gauge_started = True
            self._gauge_job = self.root.after(33, self._gauge_tick)
        # 全部扫描异步化（PowerShell 取硬件信息串行执行曾是 4.8s 卡顿源），
        # 结果经队列由 _run_in_queue 在 UI 线程渲染，缓存机制不变
        def _bg_scan():
            try: self._q.put(("info", get_sys_info()))
            except: pass
            try: self._q.put(("star", get_startup()))
            except: pass
            try: self._q.put(("proc", get_processes()))
            except: pass
            try: self._q.put(("disk", get_disks()))
            except: pass
            try: self._q.put(("extra", get_extra_info()))
            except: pass
            try: self._q.put(("health", get_disk_health()))
            except: pass
        threading.Thread(target=_bg_scan, daemon=True).start()

    def _scan_loop(self):
        """后台定期刷新数据（只在当前 Tab 时运行；stop 时休眠不退出）。"""
        tick = 0
        while True:
            time.sleep(5)
            if self._stop_flag.is_set() or self.app.current != self: continue
            try:
                self._q.put(("proc", get_processes()))
                self._q.put(("disk", get_disks()))
            except: pass
            # GPU 状态每 10s 查一次（通用计数器路径要起 PowerShell，5s 太频）
            tick += 1
            if tick % 2:
                continue
            try:
                gpu_txt = query_gpu_status()
                if gpu_txt:
                    self._q.put(("gpu", gpu_txt))
            except: pass

    def stop(self):
        if hasattr(self, "_stop_flag"):
            self._stop_flag.set()
        # 结束仪表帧循环：否则切走后仍有一条 30fps 的空转定时器跑到退出，
        # 与"退出更干净/切页签就停"的既定行为不符
        job = getattr(self, "_gauge_job", None)
        if job is not None:
            try: self.root.after_cancel(job)
            except Exception: pass
            self._gauge_job = None
        self._gauge_started = False

    def on_show(self):
        # 重置停止标志，让后台线程重新工作
        if hasattr(self, "_stop_flag"):
            self._stop_flag.clear()
        if self._cached_hw: self._render_info(self._cached_hw)
        if hasattr(self, "_cached_extra") and self._cached_extra:
            self._render_extra(self._cached_extra)
        if self._cached_disk: self._render_disks(self._cached_disk)
        if self._cached_proc: self._render_proc(self._cached_proc)
        if self._cached_star: self._render_star(self._cached_star)
        # 切换到本 Tab 时启动队列消费
        self._start_queue()
        self._after_id = self.root.after(30, self._run_in_queue)

    def _live_worker(self):
        while True:
            if self._stop_flag.is_set() or self.app.current != self:
                time.sleep(0.5)
                continue
            try:
                cpu = psutil.cpu_percent(interval=0) or 0
                cores = psutil.cpu_percent(percpu=True, interval=0)
                vm = psutil.virtual_memory()
                mem = vm.percent or 0
                n = psutil.net_io_counters()
                mem_info = (round(vm.used / 1024**3, 1), round(vm.total / 1024**3, 1))
                self._cpu_hist.append(cpu)
                self._mem_hist.append(mem)
                if len(self._cpu_hist) > 40: self._cpu_hist.pop(0)
                if len(self._mem_hist) > 40: self._mem_hist.pop(0)
                self._net_hist_down.append(n.bytes_recv)
                self._net_hist_up.append(n.bytes_sent)
                if len(self._net_hist_down) > 30: self._net_hist_down.pop(0)
                if len(self._net_hist_up) > 30: self._net_hist_up.pop(0)
                self._q.put(("live", {"cpu": cpu, "mem": mem, "cores": cores,
                                       "down": n.bytes_recv, "up": n.bytes_sent,
                                       "mem_info": mem_info}))
            except: pass
            time.sleep(0.5)

    def _start_queue(self):
        """启动队列消费循环（安全版本，切 Tab 后自动停止）。"""
        if hasattr(self, "_after_id") and self._after_id is not None:
            self.root.after_cancel(self._after_id)
        self._after_id = None
        self._ui_ready = True

    def _run_in_queue(self):
        if not hasattr(self, "_after_id") or self._after_id is None:
            return
        if self.app.current != self:
            return
        if not hasattr(self, "procs_tree") or self.procs_tree is None:
            return
        consumed = False
        while not self._q.empty():
            try:
                item = self._q.get_nowait()
            except: break
            typ, data = item
            if typ == "info":
                self._cached_hw = data
                self._render_info(data); consumed = True
            elif typ == "extra":
                self._cached_extra = data
                self._render_extra(data); consumed = True
            elif typ == "disk":
                self._cached_disk = data
                self._render_disks(data); consumed = True
            elif typ == "proc":
                self._cached_proc = data
                self._render_proc(data); consumed = True
            elif typ == "star":
                self._cached_star = data
                self._render_star(data); consumed = True
            elif typ == "health":
                # 修复：此前只采集不消费，_cached_health 永远 None，
                # 导致磁盘卡片的 SMART 健康副行从未渲染（整条链路静默死亡）
                self._cached_health = data
                if self._cached_disk:
                    self._render_disks(self._cached_disk)
                consumed = True
            elif typ == "gpu":
                cell = self._extra_cells.get("GPU")
                if cell:
                    cell.config(text=str(data)[:26], fg=GREEN)
                consumed = True
            elif typ == "live":
                self._render_live(data); consumed = True
        self._after_id = self.root.after(200, self._run_in_queue)

    def _render_info(self, info):
        for lb, cell in self._sys_cells.items():
            cell.config(text=str(info.get(lb, "-"))[:25])

    def _render_extra(self, info):
        mapping = {
            "GPU": "GPU", "显存": "显存", "频率": "CPU频率", "温度": "CPU温度",
            "IPv4": "IPv4", "安全启动": "安全启动", "BIOS": "BIOS", "磁盘": "磁盘型号",
        }
        for info_key, lb in mapping.items():
            cell = self._extra_cells.get(lb)
            if cell:
                cell.config(text=str(info.get(info_key, "-"))[:20])
        # 温度/频率 → 迷你仪表卡
        try:
            t = str(info.get("温度", "--"))
            f = str(info.get("频率", "--"))
            self._temp_str = t if t != "未知" else "--"
            self._freq_str = f if f != "未知" else "--"
            import re as _re
            m = _re.search(r"(\d+(?:\.\d+)?)", self._temp_str)
            self._temp_pct = max(0.0, min(100.0, float(m.group(1)) if m else 0))
            m = _re.search(r"(\d+(?:\.\d+)?)", self._freq_str)
            if m:
                ghz = float(m.group(1))
                self._freq_pct = max(0.0, min(100.0, ghz / 4.5 * 100))  # 4.5GHz 满量程
        except Exception:
            pass

    def _render_live(self, data):
        cpu = data.get("cpu", 0)
        mem = data.get("mem", 0)
        cores = data.get("cores", [])
        mem_info = data.get("mem_info", (0, 0))
        down = data.get("down", 0)
        up = data.get("up", 0)

        # 目标值更新（动画帧里平滑追踪）
        self._cpu_d = float(cpu)
        self._mem_d = float(mem)
        self._mem_gb = mem_info
        if cores:
            if len(self._cores_d) != len(cores):
                self._cores_d = [0.0] * len(cores)
                self._cores_t = [0.0] * len(cores)
                self._cores_peak = [0.0] * len(cores)
            for i, v in enumerate(cores):
                self._cores_d[i] = float(v)
                self._cores_peak[i] = max(self._cores_peak[i], float(v))
        if len(self._net_hist_down) >= 2:
            self._net_ds = abs((down - self._net_hist_down[-2]) / 1024 / 1024)
            self._net_us = abs((up - self._net_hist_up[-2]) / 1024 / 1024)
        # 曲线
        self._draw_wave(self._chart_c, self._cpu_hist, self._mem_hist)
        # 网络卡
        self._draw_net_card()

    # ─── 仪表动画帧（主线程 after 驱动，33ms≈30fps） ───
    def _gauge_tick(self):
        if self._stop_flag.is_set():
            self._gauge_started = False   # 页签已切走：结束帧循环，回来时由 start() 重启
            return
        try:
            if self.app.current == self:
                self._cpu_t += (self._cpu_d - self._cpu_t) * 0.18
                self._mem_t += (self._mem_d - self._mem_t) * 0.18
                for i in range(len(self._cores_t)):
                    self._cores_t[i] += (self._cores_d[i] - self._cores_t[i]) * 0.22
                    # 峰值保持线缓慢回落
                    self._cores_peak[i] = max(self._cores_d[i],
                                             self._cores_peak[i] * 0.985)
                self._draw_ring(self.cpu_ring, self._cpu_t, "CPU", CYAN,
                                sub=f"平均 {sum(self._cpu_hist[-10:])/max(len(self._cpu_hist[-10:]),1):.0f}%")
                self._draw_ring(self.mem_ring, self._mem_t, "内存", GREEN,
                                sub=f"{self._mem_gb[0]} / {self._mem_gb[1]} GB")
                self._draw_vu()
                self._draw_tf_card()
        except Exception:
            pass
        try:
            self._gauge_job = self.root.after(33, self._gauge_tick)
        except Exception:
            pass

    def _draw_ring(self, canvas, pct, title, color, sub=""):
        """环形仪表：暗轨 + 渐亮弧 + 刻度 + 中心大数字（AIDA64 风）"""
        canvas.delete("all")
        w = canvas.winfo_width() or 220
        h = canvas.winfo_height() or 120
        if w < 40 or h < 40: return
        cx = w / 2
        cy = h / 2 + 4
        r = min(h, w) / 2 - 14
        # 背景轨
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                           outline=PANEL3, width=9)
        # 12 刻度点
        import math
        for a in range(0, 360, 30):
            rad = math.radians(a - 90)
            x1 = cx + (r + 8) * math.cos(rad); y1 = cy + (r + 8) * math.sin(rad)
            x2 = cx + (r + 11) * math.cos(rad); y2 = cy + (r + 11) * math.sin(rad)
            canvas.create_line(x1, y1, x2, y2, fill=BORDER)
        # 值弧（颜色随负载渐变）
        frac = max(0.0, min(1.0, pct / 100))
        vcolor = GREEN if pct < 50 else YELLOW if pct < 80 else RED
        if frac > 0.005:
            canvas.create_arc(cx - r, cy - r, cx + r, cy + r,
                              start=90, extent=-360 * frac, style="arc",
                              outline=vcolor, width=9)
        # 中心数字
        canvas.create_text(cx, cy - 4, text=f"{pct:.0f}%",
                            fill=TEXT, font=(FONT_MONO, 17, "bold"))
        canvas.create_text(cx, cy + 16, text=sub, fill=TEXT2, font=(FONT_MONO, 7))

    def _draw_vu(self):
        """各核 VU 表：竖条 + 峰值保持横线（音频电平表风）"""
        c = self.cores_canvas
        if not c or not self._cores_t: return
        c.delete("all")
        w = c.winfo_width() or 400
        h = c.winfo_height() or 44
        n = max(1, len(self._cores_t))
        bw = w / n
        for i, v in enumerate(self._cores_t):
            x = i * bw
            frac = max(0.0, min(1.0, v / 100))
            # 分段变色（下绿上红）
            bar_h = (h - 10) * frac
            segs = 5
            for s in range(segs):
                f0 = s / segs; f1 = (s + 1) / segs
                if frac <= f0: break
                top = h - 5 - (h - 10) * f1
                bot = h - 5 - (h - 10) * f0
                color = GREEN if f1 < 0.55 else YELLOW if f1 < 0.8 else RED
                c.create_rectangle(x + 2, top, x + bw - 2, bot,
                                   fill=color, outline="")
            # 峰值保持线
            pk = max(0.0, min(1.0, self._cores_peak[i] / 100))
            py = h - 5 - (h - 10) * pk
            c.create_line(x + 2, py, x + bw - 2, py, fill=TEXT, width=1)
            if i < len(self._core_labels):
                self._core_labels[i].config(
                    text=f"C{i} {v:.0f}",
                    fg=TEXT if v > 3 else TEXT2)

    def _draw_tf_card(self):
        """温度·频率卡：两个半环形迷你仪表"""
        c = self.tf_canvas
        c.delete("all")
        w = c.winfo_width() or 220
        h = c.winfo_height() or 120
        if w < 40: return
        def mini(cx, pct, label, val, color):
            r = 30
            c.create_arc(cx - r, h/2 - r, cx + r, h/2 + r,
                         start=180, extent=-180, style="arc",
                         outline=PANEL3, width=7)
            f = max(0.0, min(1.0, pct / 100))
            if f > 0.01:
                c.create_arc(cx - r, h/2 - r, cx + r, h/2 + r,
                             start=180, extent=-180 * f, style="arc",
                             outline=color, width=7)
            c.create_text(cx, h/2 - 4, text=val, fill=TEXT,
                          font=(FONT_MONO, 11, "bold"))
            c.create_text(cx, h/2 + 12, text=label, fill=TEXT2, font=(FONT_UI, 8))
        mini(w * 0.28, self._temp_pct, "温度", self._temp_str,
             GREEN if self._temp_pct < 60 else YELLOW if self._temp_pct < 80 else RED)
        mini(w * 0.72, self._freq_pct, "频率", self._freq_str, PURPLE)

    def _draw_net_card(self):
        """网络卡：大数字 ↓↑ + 迷你双曲线"""
        c = self.net_canvas
        c.delete("all")
        w = c.winfo_width() or 220
        h = c.winfo_height() or 120
        ds = getattr(self, "_net_ds", 0.0)
        us = getattr(self, "_net_us", 0.0)
        txt = "KB/s"
        d_t = f"{ds*1024:.0f}" if ds < 1 else f"{ds:.1f}"
        u_t = f"{us*1024:.0f}" if us < 1 else f"{us:.1f}"
        c.create_text(w/2, 22, text=f"↓ {d_t}  {txt}", fill=CYAN,
                      font=(FONT_MONO, 13, "bold"))
        c.create_text(w/2, 42, text=f"↑ {u_t}  {txt}", fill=ORANGE,
                      font=(FONT_MONO, 10, "bold"))
        # 迷你曲线区
        down = self._net_hist_down; up = self._net_hist_up
        if len(down) >= 3:
            max_v = 0.01
            for i in range(1, len(down)):
                max_v = max(max_v, abs(down[i]-down[i-1])/1048576,
                            abs(up[i]-up[i-1])/1048576)
            cy_base = h - 8; avail = h - 70
            def curve(hist, color):
                pts = []
                for i in range(1, len(hist)):
                    v = abs(hist[i]-hist[i-1])/1048576
                    x = 4 + (i-1) * (w - 8) / max(len(hist)-2, 1)
                    y = cy_base - (avail * v / max_v)
                    pts.extend([x, y])
                if len(pts) >= 4:
                    c.create_line(pts, fill=color, width=1.5, smooth=True)
            curve(down, CYAN); curve(up, ORANGE)

    def _draw_wave(self, canvas, cpu_hist, mem_hist):
        """全宽主视觉波形：垂直渐变面积 + 平滑曲线 + 网格 + 当前值标注
        （对标 Ryzen Master 主图表的沉浸感）"""
        canvas.delete("all")
        w = canvas.winfo_width() or 900
        h = self._chart_h
        if not cpu_hist or w < 20: return
        # 背景横向网格（25/50/75%）+ 左侧刻度
        for i in range(1, 5):
            y = h - 6 - (h - 16) * i / 4
            canvas.create_line(2, y, w - 2, y, fill=PANEL3, dash=(2, 4))
            canvas.create_text(4, y - 6, text=f"{i*25}", fill=MUTED,
                               font=(FONT_MONO, 7), anchor="nw")
        def series_points(hist):
            n = len(hist)
            if n < 2: return None
            step = (w - 10) / max(n - 1, 1)
            pts = []
            for i, v in enumerate(hist):
                x = 5 + i * step
                y = h - 6 - (h - 16) * max(0, min(100, v)) / 100
                pts.extend([x, y])
            return pts
        def draw_series(hist, line_color, grad_top):
            pts = series_points(hist)
            if not pts: return
            # 垂直渐变面积：分 8 层多边形，颜色从 line_color 渐隐到背景
            r0, g0, b0 = (int(line_color[1:3],16), int(line_color[3:5],16), int(line_color[5:7],16))
            base_y = h - 6
            layers = 8
            for L in range(layers, 0, -1):
                f_top = (L - 1) / layers
                f_bot = L / layers
                # 找当前曲线在 f_top/f_bot 高度之间的采样段，构造裁剪面积
                poly = []
                n2 = len(pts) // 2
                for i in range(n2):
                    x, y = pts[2*i], pts[2*i+1]
                    yv = base_y - (base_y - y)  # 曲线 y
                    if (base_y - yv) <= f_bot * (h - 16):
                        yy = max(y, base_y - f_bot * (h - 16))
                    else:
                        continue
                    poly.extend([x, yy])
                if not poly: continue
                alpha = f_top  # 越低越透明→用更暗色
                rr = int(BG_R + (r0 - BG_R) * alpha * 0.45)
                gg = int(BG_G + (g0 - BG_G) * alpha * 0.45)
                bb = int(BG_B + (b0 - BG_B) * alpha * 0.45)
                fillc = "#%02x%02x%02x" % (rr, gg, bb)
                poly_full = poly + [pts[-2], base_y, pts[0], base_y]
                canvas.create_polygon(poly_full, fill=fillc, outline="")
            # 平滑主曲线
            canvas.create_line(pts, fill=line_color, width=2, smooth=True)
            # 端点光点
            canvas.create_oval(pts[-2]-3, pts[-1]-3, pts[-2]+3, pts[-1]+3,
                               fill=line_color, outline="")
            # 端点光晕（同心两圈）
            canvas.create_oval(pts[-2]-6, pts[-1]-6, pts[-2]+6, pts[-1]+6,
                               outline=line_color, width=1)
        draw_series(cpu_hist, CYAN, True)
        if mem_hist and len(mem_hist) >= 2:
            draw_series(mem_hist, GREEN, True)
        # 右上角当前值大字
        canvas.create_text(w - 10, 14, text=f"CPU {cpu_hist[-1]:.0f}%",
                            fill=CYAN, font=(FONT_MONO, 10, "bold"), anchor="ne")
        if mem_hist:
            canvas.create_text(w - 10, 32, text=f"内存 {mem_hist[-1]:.0f}%",
                               fill=GREEN, font=(FONT_MONO, 9, "bold"), anchor="ne")

    def _render_disks(self, disks):
        for w in self.disk_list.winfo_children():
            w.destroy()
        if not disks: return
        health = getattr(self, "_cached_health", None) or []
        for idx, d in enumerate(disks):
            pct = d["percent"]
            color = GREEN if pct < 50 else YELLOW if pct < 80 else RED
            row = tk.Frame(self.disk_list, bg=PANEL)
            row.pack(fill="x", pady=(0, 4))
            head = tk.Frame(row, bg=PANEL)
            head.pack(fill="x", pady=(0, 2))
            tk.Label(head, text=f"  {d['mount']}", bg=PANEL, fg=TEXT,
                     font=(FONT_MONO, 9, "bold"), anchor="w").pack(side="left")
            tk.Label(head, text=f"{kb(d['used'])} / {kb(d['total'])}  {pct}%",
                     bg=PANEL, fg=color, font=(FONT_MONO, 8), anchor="e").pack(side="right")
            bar_bg = tk.Frame(row, bg=PANEL3, height=5)
            bar_bg.pack(fill="x")
            bar_bg.pack_propagate(False)
            bar_fg = tk.Frame(bar_bg, bg=color, height=5)
            bar_fg.pack(side="left", fill="y")
            bar_bg.update_idletasks()
            bar_w = bar_bg.winfo_width() or 200
            bar_fg.configure(width=max(1, int(bar_w * pct / 100)))
            # ── SMART 健康副行（无权限拿到通电时长时如实显示"需管理员"）──
            h = _health_for_mount(health, d.get("mount"), idx, len(disks))
            if h:
                hs = str(h.get("health", "")).lower()
                hcol = GREEN if hs in ("healthy", "正常") else (
                    YELLOW if hs in ("warning", "警告") else RED)
                bits = [f"🩺 {h['health']}", h.get("media", "-"), h.get("bus", "-")]
                if h.get("size"):
                    bits.append(kb(h["size"]))
                bits.append(f"通电 {h['hours']}h" if h.get("hours") is not None
                            else "通电需管理员")
                if h.get("temp") is not None:
                    bits.append(f"{h['temp']}°C")
                tk.Label(row, text="   " + " · ".join(bits), bg=PANEL,
                         fg=hcol, font=(FONT_MONO, 7), anchor="w").pack(fill="x", pady=(2, 0))

    def _render_proc(self, procs):
        for iid in self.procs_tree.get_children():
            self.procs_tree.delete(iid)
        shown = 0
        for p in procs[:100]:
            cpu_v = float(p["cpu"] or 0)
            # CPU 热力条（负载一眼可见，替代纯数字列）
            filled = int(min(cpu_v, 100) / 100 * 12)
            bar = "█" * filled + "░" * (12 - filled)
            self.procs_tree.insert("", "end", values=(
                p["name"][:36], p["pid"], f"{cpu_v:.1f}%", bar,
                kb(p["mem"]), p["etime"], p["exe"][:48]))
            shown += 1
        self.proc_count_lbl.config(text=f"共 {len(procs)} 个")

    def _sort_procs(self, col):
        """进程表头点击排序（CPU%/内存/PID 数值，其余文本）"""
        tree = self.procs_tree
        items = [(tree.set(k, col), k) for k in tree.get_children()]
        if col == "CPU%":
            items.sort(key=lambda t: float(str(t[0]).replace("%", "") or 0), reverse=True)
        elif col == "PID":
            items.sort(key=lambda t: int(t[0]), reverse=True)
        elif col == "内存":
            # 按真实字节数排（旧版按字符串排，"900.0M" 会排在 "1.2G" 前面）
            items.sort(key=lambda t: parse_size(t[0]), reverse=True)
        else:
            items.sort()
        for i, (val, k) in enumerate(items):
            tree.move(k, "", i)

    def _render_star(self, items):
        """启动项卡片流（参照电脑管家样式）：应用图标 + 名称 + 命令副标题
        + 来源徽章 + 开/关胶囊开关（点击即切换，StartupApproved 机制）"""
        c = self.star_area
        c.delete("all")
        self._star_rows = []
        if not items:
            c.create_text(60, 30, text="无开机自启项", fill=TEXT2, font=(FONT_UI, 10))
            self.star_count_lbl.config(text="共 0 项")
            return
        row_h = 52
        visible = min(len(items), 40)
        c.configure(scrollregion=(0, 0, 0, visible * row_h + 8))
        W = c.winfo_width()
        for i, it in enumerate(items[:40]):
            name = str(it.get("name", "")) if isinstance(it, dict) else str(it[0])
            val = str(it.get("val", "")) if isinstance(it, dict) else str(it[1])
            disabled = bool(it.get("disabled")) if isinstance(it, dict) else False
            y = i * row_h + 4
            cy = y + row_h / 2 - 2
            # 来源
            v = val.lower()
            if it.get("kind") == "task":
                src, src_col = "计划任务", YELLOW
            elif "currentversion\\run" in v or "registry" in v:
                src, src_col = "注册表", PURPLE
            elif v.startswith("c:\\users") or v.startswith(str(Path.home()).lower()):
                src, src_col = "用户", CYAN
            elif "startup" in v or v.endswith(".lnk"):
                src, src_col = "启动文件夹", GREEN
            else:
                src, src_col = "系统", ORANGE
            # 卡片底
            c.create_rectangle(2, y, W - 2, y + row_h - 4,
                               fill=PANEL2 if i % 2 == 0 else PANEL, outline="")
            # ── 应用图标（真实 exe/lnk 图标，失败回退 🚀）──
            exe = val if str(val).lower().endswith(".lnk") else _exe_path_from_cmd(val)
            photo = None
            if exe:
                pkey = (exe.lower(), 28)
                photo = _PHOTO_CACHE.get(pkey)
                if photo is None:
                    pil = get_file_icon_img(exe, 28)
                    if pil is not None:
                        try:
                            photo = _PILImageTk.PhotoImage(pil)
                            _PHOTO_CACHE[pkey] = photo   # 持有引用防 GC
                        except Exception:
                            photo = None
            if photo is not None:
                c.create_image(20, cy, image=photo, anchor="w")
            else:
                c.create_text(30, cy, text="🚀", font=(FONT_UI, 13))
            # ── 名称 + 命令副标题（两行，参照管家面板）──
            c.create_text(56, y + 14, text=name[:34],
                          fill=TEXT, font=(FONT_UI, 10, "bold"), anchor="w")
            c.create_text(56, y + 35, text=val[:78] + ("…" if len(val) > 78 else ""),
                          fill=MUTED, font=(FONT_MONO, 7), anchor="w")
            # ── 来源徽章 ──
            bw = 62
            c.create_rectangle(W - bw - 78, y + 16, W - 78, y + row_h - 20,
                               fill="", outline=src_col)
            c.create_text(W - 78 - bw / 2, y + row_h / 2 - 3,
                          text=src, fill=src_col, font=(FONT_UI, 7))
            # ── 开/关 + 胶囊开关（tag 绑定点击切换）──
            sw_w, sw_h = 40, 20
            sw_x, sw_y = W - sw_w - 12, cy - sw_h / 2
            st_col = CYAN if not disabled else PANEL3
            r = sw_h // 2
            c.create_oval(sw_x, sw_y, sw_x + sw_h, sw_y + sw_h,
                          fill=st_col, outline=st_col, tags=f"sw{i}")
            c.create_oval(sw_x + sw_w - sw_h, sw_y, sw_x + sw_w, sw_y + sw_h,
                          fill=st_col, outline=st_col, tags=f"sw{i}")
            c.create_rectangle(sw_x + r, sw_y, sw_x + sw_w - r, sw_y + sw_h,
                               fill=st_col, outline=st_col, tags=f"sw{i}")
            kx = sw_x + sw_w - sw_h + 3 if not disabled else sw_x + 3
            c.create_oval(kx, sw_y + 3, kx + sw_h - 6, sw_y + sw_h - 3,
                          fill=TEXT, outline="", tags=f"sw{i}")
            c.create_text(sw_x - 14, cy, text="关" if disabled else "开",
                          fill=TEXT2 if disabled else GREEN,
                          font=(FONT_UI, 9, "bold"), tags=f"sw{i}")
            c.tag_bind(f"sw{i}", "<Button-1>",
                       lambda e, idx=i: self._star_toggle(idx))
            c.tag_bind(f"sw{i}", "<Enter>",
                       lambda e=None: self.star_area.config(cursor="hand2"))
            self._star_rows.append({"y0": y, "y1": y + row_h - 4, "item": it})
        n_task = sum(1 for x in items if x.get("kind") == "task")
        txt = f"共 {len(items)} 项"
        if n_task:
            txt += f" · 计划任务 {n_task}"
        self.star_count_lbl.config(text=txt)

    def _star_toggle(self, idx):
        """点击开关 → 启用/禁用该自启项（StartupApproved，与任务管理器一致）"""
        rows = getattr(self, "_star_rows", [])
        if idx >= len(rows):
            return
        it = rows[idx]["item"]
        ok, new_state, msg = toggle_startup_item(it)
        if ok:
            it["disabled"] = not new_state
            self._render_star(self._cached_star or [])
        else:
            show_warning("操作失败", msg)

    def _export_report(self):
        """导出硬件快照报告（系统信息 + 磁盘 + 自启项 + GPU 实时）"""
        try:
            lines = [f"{APP_NAME} 硬件报告  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                     "=" * 56, ""]
            for k, v in get_sys_info().items():
                lines.append(f"{k}: {v}")
            up = time.time() - psutil.boot_time()
            lines.append(f"开机时长: {int(up)//3600} 小时 {(int(up)%3600)//60} 分钟")
            extra = self._cached_extra or {}
            for k in ("GPU", "显存", "BIOS", "主板", "磁盘", "安全启动"):
                v = extra.get(k) if isinstance(extra, dict) else None
                if v and v not in ("未知", "-"):
                    lines.append(f"{k}: {v}")
            gpu_now = query_gpu_status()
            if gpu_now:
                lines.append(f"GPU 实时: {gpu_now}")
            lines.append("")
            lines.append("[磁盘]")
            for d in (self._cached_disk or get_disks()):
                lines.append(f"  {d['mount']}  {kb(d['used'])} / {kb(d['total'])}  ({d['percent']}%)")
            star = self._cached_star or get_startup()
            lines.append("")
            lines.append(f"[开机自启] 共 {len(star)} 项")
            for it in star[:20]:
                # v2.4 起自启项是字典（旧版元组解包 dict 会抛 too many values）
                nm = it.get("name", "") if isinstance(it, dict) else str(it[0])
                lines.append(f"  · {nm}")
            lines.append("")
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            lines.append(f"[当前负载] CPU {cpu}% · 内存 {mem.percent}% "
                         f"({mem.used/1024**3:.1f}/{mem.total/1024**3:.1f}GB)")
            path = Path.home() / f"硬件报告_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            path.write_text("\n".join(lines), encoding="utf-8")
            show_info("已导出", f"报告已保存到:\n{path}")
        except Exception as e:
            show_error("导出失败", str(e))

    def _refresh_procs(self):
        self._q.put(("proc", get_processes()))
    def _load_star(self):
        self._q.put(("star", get_startup()))

    def _port_dialog(self):
        """端口占用查询：输入端口号精确查，或留空看全部监听端口；可直接结束占用进程"""
        win = tk.Toplevel(self.root)
        win.title("端口占用查询")
        win.configure(bg=BG)
        win.geometry("880x520")
        win.transient(self.root)
        enable_dark_title_bar(win)
        bar = tk.Frame(win, bg=BG)
        bar.pack(fill="x", padx=14, pady=(12, 6))
        tk.Label(bar, text="端口号（留空 = 全部监听端口）", bg=BG, fg=TEXT2,
                 font=(FONT_UI, 9)).pack(side="left")
        ent = tk.Entry(bar, bg=PANEL2, fg=TEXT, insertbackground=TEXT,
                       font=(FONT_MONO, 10), width=10, relief="flat",
                       highlightthickness=1, highlightbackground=BORDER,
                       highlightcolor=CYAN)
        ent.pack(side="left", padx=(8, 4))
        ent.focus_set()

        def _query(e=None):
            self._port_query(win, ent.get().strip(), tree, count_lbl)
        qbtn = tk.Button(bar, text="🔍 查询", bg=PANEL2, fg=CYAN, font=(FONT_UI, 9),
                         bd=0, relief="flat", cursor="hand2", command=_query)
        qbtn.pack(side="left", padx=4)
        ent.bind("<Return>", _query)

        def _kill():
            sel = tree.selection()
            if not sel:
                show_info("未选择", "请先在列表中选中一个端口条目", parent=win)
                return
            v = tree.set(sel[0])
            self._kill_pid(int(v["PID"]), v["进程"])
            if win.winfo_exists():
                self._port_query(win, ent.get().strip(), tree, count_lbl)
        kbtn = tk.Button(bar, text="❌ 结束进程", bg=PANEL2, fg=RED, font=(FONT_UI, 9),
                         bd=0, relief="flat", cursor="hand2", command=_kill)
        kbtn.pack(side="left", padx=4)
        count_lbl = tk.Label(bar, text="", bg=BG, fg=TEXT2, font=(FONT_MONO, 8))
        count_lbl.pack(side="right")

        holder = tk.Frame(win, bg=BG)
        holder.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        cols = [("协议", 50), ("本地地址", 200), ("远程地址", 200), ("状态", 110),
                ("PID", 70), ("进程", 190)]
        tree = ttk.Treeview(holder, columns=[c[0] for c in cols], show="headings")
        vs = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vs.set)
        for lb, w in cols:
            tree.heading(lb, text=lb)
            tree.column(lb, width=w, minwidth=40,
                        anchor="w" if lb in ("本地地址", "远程地址", "进程") else "center")
        tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        _query()

    def _port_query(self, win, txt, tree, count_lbl):
        """后台 netstat 查询 → 主线程填充表格。
        注意：线程内不能直接调 root.after（非主循环环境会抛
        "main thread is not in main loop"），改用队列 + 主线程 after 轮询。"""
        port = int(txt) if txt.isdigit() else None
        if not win.winfo_exists():
            return
        count_lbl.config(text="查询中…")
        q = queue.Queue()

        def work():
            q.put(get_port_usage(port))
        threading.Thread(target=work, daemon=True).start()

        def fill():
            if not win.winfo_exists():
                return
            try:
                rows = q.get_nowait()
            except queue.Empty:
                win.after(100, fill)
                return
            tree.delete(*tree.get_children())
            for r in rows:
                tree.insert("", "end", values=(r["proto"], r["local"], r["remote"],
                                               r["state"], r["pid"], r["pname"]))
            count_lbl.config(text=f"共 {len(rows)} 条")
        win.after(100, fill)

    def _proc_menu(self, event):
        """进程表右键菜单：结束进程"""
        iid = self.procs_tree.identify_row(event.y)
        if not iid: return
        self.procs_tree.selection_set(iid)
        pid = int(self.procs_tree.set(iid, "PID"))
        name = self.procs_tree.set(iid, "名称")
        menu = tk.Menu(self.root, tearoff=0, bg=PANEL2, fg=TEXT,
                       activebackground=PANEL3, activeforeground=RED)
        menu.add_command(label=f"❌ 结束进程 [{name}]", command=lambda: self._kill_pid(pid, name))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _kill_pid(self, pid, name):
        if pid in (0, 4):  # System Idle / System 不可杀
            show_warning("无法结束", "系统关键进程不能结束")
            return
        if pid == os.getpid():
            show_warning("无法结束", "这是统一工具箱自己")
            return
        if not ask_yesno("结束进程",
                f"确定结束进程 [{name}] (PID {pid})？\n未保存的数据可能丢失。", danger=True):
            return
        try:
            p = psutil.Process(pid)
        except psutil.NoSuchProcess:
            show_info("已结束", "进程已不存在")
            return
        except Exception as e:
            show_error("结束失败", str(e))
            return
        # PID 会被系统回收：列表是快照，点确认时可能已经换成别的进程。
        # 先核对进程名，避免"想杀 A 结果杀了 B"（名字不符一律不动手）。
        try:
            live = p.name() or ""
        except Exception:
            live = ""
        if name and live and not _same_proc_name(live, name):
            show_warning("进程已变化",
                         f"PID {pid} 现在属于 [{live}]，不是列表里的 [{name}]。\n"
                         "为避免误杀已取消操作，请刷新列表后重试。")
            return
        try:
            p.terminate()
            try: p.wait(timeout=3)
            except psutil.TimeoutExpired: p.kill()
            self._refresh_procs()
        except psutil.NoSuchProcess:
            show_info("已结束", "进程已不存在")
        except Exception as e:
            show_error("结束失败", str(e))


# ═══════════════════════════════════════════
# 模块：剪贴板历史
# ═══════════════════════════════════════════

class ClipboardModule(BaseModule):
    name = "clipboard"; label = "剪贴板"; icon = "📋"; color = GREEN

    def build(self):
        body = self.body
        top = tk.Frame(body, bg=PANEL)
        top.pack(fill="x", padx=20, pady=(12, 8))
        tk.Label(top, text="◈ 剪贴板历史", bg=PANEL, fg=GREEN,
                 font=(FONT_UI, 13, "bold")).pack(anchor="w", pady=(4, 0))
        self._status = tk.Label(top, text="◐ 监听中 · 共 0 条", bg=PANEL,
                                fg=TEXT2, font=(FONT_MONO, 8))
        self._status.pack(anchor="e")
        # 筛选
        filter_frame = tk.Frame(body, bg=BG)
        filter_frame.pack(fill="x", padx=20, pady=(0, 6))
        self.search_var = tk.StringVar()
        # trace 只在 start() 里挂一次（stop() 会摘掉）。这里再挂一条会导致
        # 每敲一个字都触发两次 _render_hist，而且那条永远摘不掉（泄漏）。
        self._search_trace = None
        tk.Label(filter_frame, text="🔍 ", bg=BG, fg=CYAN, font=(FONT_UI, 9)).pack(side="left")
        self.search_box = tk.Entry(filter_frame, textvariable=self.search_var,
                                   bg=PANEL2, fg=TEXT, font=(FONT_MONO, 9),
                                   relief="flat", insertbackground=GREEN, bd=0,
                                   highlightthickness=1, highlightbackground=BORDER,
                                   highlightcolor=GREEN)
        self.search_box.pack(side="left", ipadx=80, pady=2)
        self._filter_type = tk.StringVar(value="all")
        # v2.4 起支持图片捕获，恢复 img 筛选
        for typ, label in [("all", "全部"), ("txt", "文本"), ("url", "链接"),
                            ("code", "代码"), ("num", "数字"), ("img", "图片")]:
            btn = tk.Radiobutton(filter_frame, text=label, variable=self._filter_type,
                                 value=typ, bg=BG, fg=TEXT2, font=(FONT_UI, 8),
                                 activebackground=PANEL2, selectcolor=PANEL3,
                                 indicatoron=0, highlightthickness=0, bd=0,
                                 command=self._render_hist)
            btn.pack(side="left", padx=(4, 0), ipadx=8)
            btn.bind("<Enter>", lambda e=None, b=btn: b.config(bg=PANEL2))
            btn.bind("<Leave>", lambda e=None, b=btn: b.config(bg=BG))

        # 操作按钮
        op_frame = tk.Frame(body, bg=PANEL3)
        op_frame.pack(fill="x", padx=20, pady=(4, 6))
        ops = [("📋 复制", self._copy_selected), ("⭐ 置顶", self._pin),
               ("🔗 打开链接", self._open_url), ("🗑 删除", self._delete_selected),
               ("🔄 清空", self._clear_all), ("⬇ 导出", self._export),
               ("🧹 纯文本化", self._plain_paste),
               ("🔍 文字识别", self._ocr_selected),
               ("🔧 文本工具", self._text_tools_dialog),
               ("📚 片段库", self._snippets_dialog),
               ("⚡ 快速面板", self.app.show_quick_panel)]
        for txt, cmd in ops:
            btn = tk.Button(op_frame, text=txt, bg=PANEL2, fg=CYAN,
                            font=(FONT_UI, 8), bd=0, relief="flat",
                            cursor="hand2", command=cmd)
            btn.pack(side="left", padx=4, pady=3)
            btn.bind("<Enter>", lambda e=None, b=btn: b.config(bg=PANEL3))
            btn.bind("<Leave>", lambda e=None, b=btn: b.config(bg=PANEL2))

        # 列表
        cols = ("时间", "类型", "内容", "使用", "次数")
        self.hist_tree = ttk.Treeview(body, columns=cols, show="headings", height=9)
        for lb, w in zip(cols, [80, 70, 560, 60, 70]):
            self.hist_tree.heading(lb, text=lb)
            self.hist_tree.column(lb, width=w, minwidth=40)
        # 先 pack 滚动条再 pack 表格（旧顺序把预览区挤到 116px 窄缝）
        vs = ttk.Scrollbar(body, orient="vertical", command=self.hist_tree.yview)
        vs.pack(side="right", fill="y", padx=(0, 20))
        self.hist_tree.pack(fill="both", expand=True, padx=(20, 0), pady=(4, 6))
        self.hist_tree.configure(yscrollcommand=vs.set)
        self.hist_tree.bind("<Double-1>", self._on_double_click)
        self.hist_tree.bind("<Delete>", lambda e: self._delete_selected())
        # Ctrl+A 全选（Tk 绑定区分大小写：<Control-A> 只匹配 Ctrl+Shift+A，
        # 真实键盘 Ctrl+A 的 keysym 是小写 a——两个形态都绑）
        for _seq in ("<Control-a>", "<Control-A>"):
            self.hist_tree.bind(_seq, lambda e: self._select_all())
        # 单击即更新预览（不用等双击）
        self.hist_tree.bind("<<TreeviewSelect>>", self._on_select_preview)
        self._tag_setup()
        # 表格右键菜单（复制/置顶/打开/删除）
        self.hist_tree.bind("<Button-3>", self._ctx_menu)

        # 预览（3 行高，长内容可读）
        preview = tk.Frame(body, bg=PANEL2)
        preview.pack(fill="x", padx=20, pady=(6, 12))
        tk.Label(preview, text="◈ 预览", bg=PANEL2, fg=CYAN,
                 font=(FONT_UI, 9, "bold")).pack(anchor="w", pady=(4, 2))
        self.preview_var = tk.StringVar(value="双击条目查看完整内容")
        self.preview_lbl = tk.Label(preview, textvariable=self.preview_var, bg=PANEL2,
                                    fg=TEXT2, font=(FONT_MONO, 8), anchor="nw",
                                    justify="left", wraplength=980)
        self.preview_lbl.pack(anchor="w", fill="x", pady=(0, 6))
        # 图片条目预览（v2.4 图片捕获）
        self._img_lbl = tk.Label(preview, bg=PANEL2)
        self._img_lbl.pack(anchor="w", pady=(0, 6))
        self._img_ref = None
        # 双击时更新预览（原有逻辑只复制，这里补上预览联动）
        self._preview_hist = None

        self._init_service()
        self._id_by_iid = {}

    def _tag_setup(self):
        self.hist_tree.tag_configure("pinned", background=PANEL3)
        self.hist_tree.tag_configure("pinned_fg", foreground=YELLOW)
        self.hist_tree.tag_configure("url_fg", foreground=CYAN)
        self.hist_tree.tag_configure("code_fg", foreground=PURPLE)
        self.hist_tree.tag_configure("num_fg", foreground=GREEN)
        self.hist_tree.tag_configure("img_fg", foreground=ORANGE)
        self.hist_tree.tag_configure("email_fg", foreground=YELLOW)
        self.hist_tree.tag_configure("phone_fg", foreground=ORANGE)

    def _classify(self, text):
        if not text: return "txt"
        t = text.strip(); tl = t.lower()
        if tl.startswith("http://") or tl.startswith("https://") or tl.startswith("www."):
            return "url"
        if "@" in t and "." in t.split("@")[-1]: return "email"
        if len(t) >= 11 and t.isdigit() and t.startswith("1"): return "phone"
        if any(kw in tl for kw in ["def ", "class ", "function", "import ", "#include", "{", "var ", "let "]):
            return "code"
        try: float(t.replace(",", "").replace(" ", "")); return "num"
        except: pass
        return "txt"

    def _type_icon(self, typ):
        return {"txt": "📝", "url": "🔗", "code": "💻", "num": "🔢",
                "img": "🖼", "email": "📧", "phone": "📱"}.get(typ, "📝")

    def _type_label(self, typ):
        return {"txt": "文本", "url": "链接", "code": "代码", "num": "数字",
                "img": "图片", "email": "邮箱", "phone": "手机"}.get(typ, typ)

    def _rel_time(self, t):
        try:
            if len(t) == 8 and t[2] == ":" and t[5] == ":":
                return t + " (日期未知)"
            dt = datetime.datetime.fromisoformat(t)
            now = datetime.datetime.now(dt.tzinfo)
            secs = int((now - dt).total_seconds())
            if secs < 0: return t
            if secs < 60: return f"{secs}s前"
            if secs < 3600: return f"{secs//60}分钟前"
            if secs < 86400: return f"{secs//3600}小时前"
            return t
        except: return t

    def _init_service(self):
        """Main-thread only. History and disk writes belong to this thread."""
        if hasattr(self, "_capture_q"):
            return
        self._owner_thread = threading.get_ident()
        self.history = []
        self._history_loaded = False
        self._capture_q = queue.Queue(maxsize=64)
        self._stop_event = threading.Event()
        self._service_after = None
        self._render_after = None
        self._page_active = False
        self._dirty = False
        self._closed = False

    def _assert_owner(self):
        self._init_service()
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("Clipboard history must be accessed on the Tk thread")

    def _ensure_watcher(self):
        """Start global capture without requiring build(); call on Tk thread."""
        self._assert_owner()
        if self._closed:
            return
        self._load_history()
        if not (hasattr(self, "_clip_thread") and self._clip_thread.is_alive()):
            self._clip_thread = threading.Thread(target=self._watch_clipboard, daemon=True)
            self._clip_thread.start()
        if self._service_after is None:
            self._service_after = self.root.after(200, self._drain_captures)

    _SECRET_RE = re.compile(
        r"(?i)(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key"
        r"|private[_-]?key|auth|密码|口令|密钥|令牌)\s*[:：=]\s*\S"
        r"|\bsk-[A-Za-z0-9]{16,}\b|\bgh[pousr]_[A-Za-z0-9]{20,}\b"
        r"|\bAKIA[0-9A-Z]{16,}\b|\bxox[baprs]-[A-Za-z0-9-]{15,}\b"
        r"|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
        r"|\b[0-9a-fA-F]{32,64}\b")

    @classmethod
    def _looks_secret(cls, text):
        """疑似密码/令牌/密钥：启发式判断（键值对、常见平台前缀、JWT、长十六进制）。"""
        if not text:
            return False
        return bool(cls._SECRET_RE.search(text))

    def _drain_captures(self):
        self._assert_owner()
        self._service_after = None
        if self._closed:
            return
        try:
            for _ in range(16):
                try:
                    kind, value, digest, stamp = self._capture_q.get_nowait()
                except queue.Empty:
                    break
                if kind == "txt":
                    text = value[:100000]
                    if SETTINGS.get("clip_skip_secrets") and self._looks_secret(text):
                        continue   # 疑似密码/令牌：跳过记录（隐私保护）
                    if not any(h["type"] != "img" and h["text"] == text for h in self.history):
                        self.history.insert(0, {"id": uuid4_str(), "time": stamp,
                            "text": text, "type": self._classify(text), "pinned": False, "uses": 0})
                        self._save_history()
                        self._request_render()
                else:
                    self._add_img_item(value, digest, stamp)
        finally:
            if not self._closed:
                self._service_after = self.root.after(200, self._drain_captures)

    def shutdown(self):
        """Optional App exit hook (Tk thread). Return whether worker has exited."""
        self._assert_owner()
        if SETTINGS.get("clip_clear_on_exit"):
            # 退出清空历史（隐私）：内存、历史文件、图片缓存一起清。
            # 旧版只清了内存和 JSON，截图 PNG 仍留在磁盘上，"清空"名不副实。
            self.history = []
            try: HISTORY_FILE.unlink(missing_ok=True)
            except Exception: pass
            purge_clip_image_cache()
        self.stop()
        self._closed = True
        self._stop_event.set()
        if self._service_after is not None:
            try: self.root.after_cancel(self._service_after)
            except Exception: pass
            self._service_after = None
        worker = getattr(self, "_clip_thread", None)
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=2.0)
        while True:
            try: self._capture_q.get_nowait()
            except queue.Empty: break
        return worker is None or not worker.is_alive()

    def start(self):
        self._init_service()
        if self._closed:
            return
        self.stop()
        self._page_active = True
        self._search_trace = self.search_var.trace_add("write", lambda *a: self._render_hist())
        if getattr(self, "_keys_tree", None) is not self.hist_tree:
            for i in range(1, 10):
                self.hist_tree.bind(str(i), lambda e, n=i: self._quick_copy(n))
            self._keys_tree = self.hist_tree
        self._ensure_watcher()
        self._render_hist()
        self._drain_render()

    def stop(self):
        self._init_service()
        self._page_active = False
        if self._render_after is not None:
            try: self.root.after_cancel(self._render_after)
            except Exception: pass
            self._render_after = None
        if getattr(self, "_search_trace", None):
            try: self.search_var.trace_remove("write", self._search_trace)
            except Exception: pass
            self._search_trace = None
        self._img_ref = None

    def on_show(self):
        self._render_hist()
        self.hist_tree.focus_set()

    def _load_history(self):
        self._assert_owner()
        if self._history_loaded:
            return
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = []
        self.history = self._normalize_history(data)
        self._history_loaded = True

    def _normalize_history(self, data):
        result, ids = [], set()
        for raw in data if isinstance(data, list) else []:
            if not isinstance(raw, dict) or not isinstance(raw.get("text"), str):
                continue
            item = {"text": raw["text"][:100000]}
            typ = raw.get("type")
            item["type"] = typ if typ in ("txt", "url", "code", "num", "img", "email", "phone") else self._classify(item["text"])
            rid = raw.get("id")
            if not isinstance(rid, str) or not rid or len(rid) > 128 or rid in ids:
                rid = uuid4_str()
            ids.add(rid)
            item["id"] = rid
            item["pinned"] = raw.get("pinned") is True
            uses = raw.get("uses", 0)
            item["uses"] = min(uses, 1000000000) if type(uses) is int and uses >= 0 else 0
            stamp = raw.get("time", "")
            item["time"] = stamp[:80] if isinstance(stamp, str) else ""
            if item["type"] == "img":
                for key in ("img", "hash"):
                    value = raw.get(key, "")
                    item[key] = value[:4096] if isinstance(value, str) else ""
            result.append(item)
        # Never evict pinned entries. The 300-entry budget is soft for all-pinned history.
        pinned = sum(h["pinned"] for h in result)
        budget = max(0, 300 - pinned)
        kept = []
        for h in result:
            if h["pinned"]:
                kept.append(h)
            elif budget:
                kept.append(h)
                budget -= 1
        return kept

    def _save_history(self):
        self._assert_owner()
        self.history = self._normalize_history(self.history)
        try:
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = HISTORY_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.history, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(HISTORY_FILE)
            self._last_save_error = None
        except Exception as exc:
            self._last_save_error = str(exc)
            return False
        self._prune_img_cache()
        return True

    def _prune_img_cache(self):
        """Only unreferenced owned PNGs; disk references protect failed saves too."""
        try:
            persisted = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            if not isinstance(persisted, list):
                return
            refs = {str(Path(h["img"]).resolve()).casefold()
                    for h in self.history + persisted
                    if isinstance(h, dict) and isinstance(h.get("img"), str) and h["img"]}
            import re
            paths = [p for p in CLIP_IMG_DIR.glob("clip_*.png")
                     if _CLIP_IMG_RE.fullmatch(p.name)
                     and not p.is_symlink()
                     and str(p.resolve()).casefold() not in refs]
            paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for path in paths[40:]:
                try: path.unlink()
                except OSError: pass
        except (OSError, ValueError, TypeError):
            return

    def _watch_clipboard(self):
        """Worker reads native clipboard only; never touches Tk/history/files."""
        import hashlib
        last = None
        while not self._stop_event.is_set():
            try:
                text = clip_get_text()
                stamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
                event, key = None, None
                if text:
                    text = text[:100000]
                    key = ("txt", text)
                    event = ("txt", text, "", stamp)
                else:
                    dib = clip_get_dib()
                    if dib and len(dib) <= 8 * 1024 * 1024:
                        digest = hashlib.sha256(dib).hexdigest()
                        key = ("img", digest)
                        event = ("img", dib, digest, stamp)
                if event is not None and key != last:
                    try:
                        self._capture_q.put_nowait(event)
                    except queue.Full:
                        pass  # Retry current value next poll; never block shutdown.
                    else:
                        last = key
                elif event is None:
                    last = None
            except Exception:
                pass
            self._stop_event.wait(1.5)

    def _add_img_item(self, dib, digest, stamp=None):
        """Main-thread conversion and persistence; cache eviction is reference-aware."""
        self._assert_owner()
        import re
        if not re.fullmatch(r"[0-9a-f]{16,64}", digest):
            return
        try:
            img = dib_to_pil(dib)
            if img is None:
                return
            CLIP_IMG_DIR.mkdir(parents=True, exist_ok=True)
            path = CLIP_IMG_DIR / f"clip_{digest}.png"
            try:
                if not path.exists():
                    img.save(path, "PNG")
                width, height = img.width, img.height
            finally:
                img.close()
            if not any(h.get("hash") == digest for h in self.history):
                item = {"id": uuid4_str(),
                        "time": stamp or datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                        "text": f"[图片] {width}×{height}",
                        "type": "img", "pinned": False, "uses": 0,
                        "img": str(path), "hash": digest}
                self.history.insert(0, item)
                self._save_history()
            self._request_render()
        except Exception:
            pass

    def _request_render(self):
        """后台线程请求重绘列表——跨线程直调 root.after 在 Tcl 非主循环时会抛
        RuntimeError 且被吞掉，改为投递脏队列、由主线程轮询消费。"""
        self._dirty = True

    def _drain_render(self):
        """主线程轮询：页面存续期间把脏队列里的重绘请求消费掉。"""
        self._render_after = None
        if not self._page_active or self._closed:
            return
        try:
            if not self.hist_tree.winfo_exists():
                self.stop()
                return
        except Exception:
            self.stop()
            return
        if self._dirty:
            self._dirty = False
            self._render_hist()
        self._render_after = self.root.after(800, self._drain_render)

    def _render_hist(self):
        # 全局监听后，后台线程会在其它页签时触发本方法——
        # 此时表格控件已被销毁，必须安静返回而不是抛 TclError
        try:
            if not hasattr(self, "hist_tree") or not self.hist_tree.winfo_exists():
                return
            selected = set(self._sel_ids())
            focus = getattr(self, "_id_by_iid", {}).get(self.hist_tree.focus())
            view = self.hist_tree.yview()
            for iid in self.hist_tree.get_children():
                self.hist_tree.delete(iid)
            kw = self.search_var.get().strip().lower()
            ft = self._filter_type.get()
        except Exception:
            return
        filtered = []
        for h in self.history:
            if kw and kw not in h.get("text", "").lower(): continue
            if ft != "all" and h.get("type") != ft: continue
            filtered.append(h)
        pinned = [h for h in filtered if h.get("pinned")]
        others = [h for h in filtered if not h.get("pinned")]
        display = pinned + others
        # id → 条目映射随渲染重建（替代"前60字符匹配"的脆弱方案）
        self._id_by_iid = {}
        for i, item in enumerate(display):
            icon = self._type_icon(item.get("type", "txt"))
            typ = item.get("type", "txt")
            text = item.get("text", "")[:60]
            if item.get("pinned"):
                tags = ("pinned", "pinned_fg")
            else:
                tag_map = {"url": "url_fg", "code": "code_fg", "num": "num_fg",
                           "img": "img_fg", "email": "email_fg", "phone": "phone_fg"}
                t = tag_map.get(typ)
                tags = (t,) if t else ()
            iid = self.hist_tree.insert("", "end", values=(
                self._rel_time(item.get("time", "")), icon, str(text),
                self._type_label(typ), item.get("uses", 0)), tags=tags)
            self._id_by_iid[iid] = item.get("id")
            if item.get("id") in selected:
                self.hist_tree.selection_add(iid)
            if item.get("id") == focus:
                self.hist_tree.focus(iid)
        if view:
            self.hist_tree.yview_moveto(view[0])
        self._on_select_preview()
        try:
            self._status.config(text=f"◐ 监听中 · 共 {len(self.history)} 条 (显示 {len(display)})")
        except Exception:
            pass  # 状态栏可能随页签销毁

    def _ctx_menu(self, event):
        """剪贴板历史右键菜单"""
        iid = self.hist_tree.identify_row(event.y)
        if not iid: return
        self.hist_tree.selection_set(iid)
        menu = tk.Menu(self.root, tearoff=0, bg=PANEL2, fg=TEXT,
                       activebackground=PANEL3, activeforeground=CYAN)
        menu.add_command(label="📋 复制", command=self._copy_selected)
        menu.add_command(label="⭐ 置顶/取消置顶", command=self._pin)
        menu.add_command(label="🔗 打开链接", command=self._open_url)
        menu.add_command(label="🔧 文本工具", command=self._text_tools_dialog)
        menu.add_command(label="📚 收藏为片段", command=self._save_as_snippet)
        menu.add_separator()
        menu.add_command(label="🗑 删除", command=self._delete_selected)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try: menu.grab_release()
            finally: menu.destroy()

    def _sel_ids(self):
        """当前选中行对应的记录 id 列表"""
        try:
            mapping = getattr(self, "_id_by_iid", {})
            return [mapping[i] for i in self.hist_tree.selection() if mapping.get(i)]
        except (AttributeError, tk.TclError):
            return []

    def _by_id(self, rid):
        for h in self.history:
            if h.get("id") == rid: return h
        return None

    def _on_select_preview(self, event=None):
        """单击条目 → 预览区显示完整内容（图片条目显示缩略图）"""
        try:
            self._img_ref = None
            self._img_lbl.config(image="", text="")
            self.preview_var.set("")
        except (AttributeError, tk.TclError):
            return
        ids = self._sel_ids()
        if not ids:
            return
        h = self._by_id(ids[0])
        if not h:
            return
        if h.get("type") == "img" and TRAY_OK:
            p = h.get("img", "")
            self.preview_var.set(f"[图片] {os.path.basename(p)}（双击复制回剪贴板）" if p else "[图片]")
            try:
                if p and os.path.exists(p):
                    with _PILImage.open(p) as img:
                        img.thumbnail((520, 104))
                        self._img_ref = _PILImageTk.PhotoImage(img)
                    self._img_lbl.config(image=self._img_ref, text="")
                else:
                    self._img_ref = None
                    self._img_lbl.config(image="", text="(缓存图片已被清理)")
            except Exception:
                self._img_ref = None
                self._img_lbl.config(image="", text="(预览失败)")
            return
        self._img_ref = None
        self._img_lbl.config(image="")
        text = str(h.get("text", ""))
        # 最多展示 500 字，避免超长内容撑爆界面
        shown = text[:500] + ("…(共 %d 字)" % len(text) if len(text) > 500 else "")
        self.preview_var.set(shown)

    def _on_double_click(self, event):
        ids = self._sel_ids()
        if not ids: return
        h = self._by_id(ids[0])
        if not h: return
        if h.get("type") == "img":
            self._copy_img(h)
        elif h.get("type") == "url":
            self._open_url()
        else:
            self._copy_text(h["text"])

    def _copy_img(self, h):
        self._assert_owner()
        """图片条目复制：DIB 写回剪贴板，目标程序可直接粘贴。返回是否成功。"""
        p = h.get("img", "")
        if not p or not os.path.exists(p):
            show_warning("图片缺失", "缓存图片已被清理，无法复制")
            return False
        try:
            with _PILImage.open(p) as img:
                copied = put_image_to_clipboard(img)
        except Exception as e:
            show_error("复制失败", str(e))
            return False
        if copied:
            h["uses"] = h.get("uses", 0) + 1
            self._save_history()
            try: self._status.config(text=f"◐ 图片已复制（{h.get('text','')}）· 可直接粘贴")
            except Exception: pass
            return True
        show_error("复制失败", "写入剪贴板失败")
        return False

    def _copy_text(self, text):
        self._assert_owner()
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        for h in self.history:
            if h.get("text") == text:
                h["uses"] = h.get("uses", 0) + 1; break
        self._save_history()
        self._render_hist()

    def _copy_selected(self):
        ids = self._sel_ids()
        if not ids: return
        h = self._by_id(ids[0])
        if not h: return
        if h.get("type") == "img":
            self._copy_img(h)
        else:
            self._copy_text(h["text"])

    # ═══ 文本工具箱（v3.5）═══
    _TEXT_OPS = [
        ("大写", "upper"), ("小写", "lower"), ("首字母大写", "title"),
        ("去首尾空白", "trim"), ("去行尾空格", "strip"), ("去空行", "no_blank"),
        ("合并空格", "collapse"), ("行去重", "dedupe"), ("行排序", "sort"),
        ("行反转", "reverse"), ("加引号", "quote"), ("逗号连接", "comma"),
        ("Base64 编码", "b64e"), ("Base64 解码", "b64d"),
        ("URL 编码", "url_e"), ("URL 解码", "url_d"),
        ("MD5", "md5"), ("SHA1", "sha1"), ("SHA256", "sha256"),
        ("JSON 美化", "json"), ("JSON 压缩", "json_min"), ("统计字数", "count"),
        ("修复乱码(UTF8当GBK)", "fix_utf8_as_gbk"),
        ("修复乱码(GBK当UTF8)", "fix_gbk_as_utf8"),
        ("转 \\uXXXX", "uni_escape"), ("\\uXXXX 还原", "uni_unescape"),
        ("UTF-8 HEX", "hex_view"),
    ]

    def _selected_text(self):
        """当前选中条目的文本；无选中则取系统剪贴板当前文本"""
        ids = self._sel_ids()
        if ids:
            h = self._by_id(ids[0])
            if h and h.get("type") != "img":
                return str(h.get("text", ""))
        try:
            return clip_get_text() or ""
        except Exception:
            return ""

    def _ocr_selected(self):
        """对选中图片条目做 OCR 文字识别（Windows 自带离线 OCR）。"""
        ids = self._sel_ids()
        h = self._by_id(ids[0]) if ids else None
        path = h.get("img", "") if h and h.get("type") == "img" else ""
        if not path or not os.path.isfile(path):
            show_info("无图片", "请先选中一个图片条目\n（截屏或复制图片后会出现在历史里）")
            return
        self._assert_owner()
        win = tk.Toplevel(self.root)
        win.title("文字识别")
        win.configure(bg=BG)
        win.geometry("560x460")
        win.transient(self.root)
        enable_dark_title_bar(win)
        tk.Label(win, text="◈ OCR 文字识别（Windows 离线 OCR）", bg=BG, fg=CYAN,
                 font=(FONT_UI, 11, "bold")).pack(anchor="w", padx=14, pady=(10, 2))
        status = tk.Label(win, text="识别中…（首次可能较慢）", bg=BG, fg=TEXT2,
                          font=(FONT_UI, 9))
        status.pack(anchor="w", padx=14)
        out = tk.Text(win, bg=PANEL2, fg=TEXT, font=(FONT_MONO, 9),
                      relief="flat", wrap="word", insertbackground=CYAN, state="disabled")
        out.pack(fill="both", expand=True, padx=14, pady=(6, 4))

        def copy_result():
            text = out.get("1.0", "end-1c")
            if text:
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
                show_info("已复制", "识别文字已复制到剪贴板", parent=win)

        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", padx=14, pady=(0, 10))
        tk.Button(btns, text="📋 复制结果", bg=PANEL2, fg=CYAN, font=(FONT_UI, 9),
                  bd=0, relief="flat", cursor="hand2", command=copy_result,
                  state="disabled").pack(side="left")
        tk.Button(btns, text="✖ 关闭", bg=PANEL2, fg=TEXT2, font=(FONT_UI, 9),
                  bd=0, relief="flat", cursor="hand2", command=win.destroy).pack(side="left", padx=(8, 0))
        copy_btn = btns.winfo_children()[0]
        q = queue.Queue()

        def _do():
            q.put(ocr_image_text(path))

        def _poll():
            if not win.winfo_exists():
                return
            try:
                text, err = q.get_nowait()
            except queue.Empty:
                win.after(250, _poll)
                return
            out.config(state="normal")
            if err:
                status.config(text="识别失败", fg=RED)
                out.insert("1.0", err)
            else:
                status.config(text=f"完成（{len(text)} 字符）", fg=GREEN)
                out.insert("1.0", text or "（未识别到文字）")
                copy_btn.config(state="normal")
        threading.Thread(target=_do, daemon=True).start()
        win.after(250, _poll)

    def _text_tools_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("文本工具箱")
        win.configure(bg=BG)
        win.geometry("720x580")
        win.transient(self.root)
        tk.Label(win, text="◈ 文本工具箱", bg=BG, fg=CYAN,
                 font=(FONT_UI, 12, "bold")).pack(anchor="w", padx=14, pady=(10, 2))
        tk.Label(win, text="对选中条目做转换（未选中则取剪贴板），结果可一键复用",
                 bg=BG, fg=TEXT2, font=(FONT_UI, 8)).pack(anchor="w", padx=14)
        tk.Label(win, text="原文", bg=BG, fg=TEXT2,
                 font=(FONT_UI, 9)).pack(anchor="w", padx=14, pady=(8, 2))
        src = tk.Text(win, height=6, bg=PANEL2, fg=TEXT, font=(FONT_MONO, 9),
                      relief="flat", wrap="none", insertbackground=CYAN)
        src.pack(fill="x", padx=14)
        src.insert("1.0", self._selected_text())

        ops_f = tk.Frame(win, bg=BG)
        ops_f.pack(fill="x", padx=14, pady=8)
        tk.Label(win, text="结果", bg=BG, fg=TEXT2,
                 font=(FONT_UI, 9)).pack(anchor="w", padx=14)
        out = tk.Text(win, height=8, bg=PANEL2, fg=GREEN, font=(FONT_MONO, 9),
                      relief="flat", wrap="none", insertbackground=GREEN)
        out.pack(fill="both", expand=True, padx=14, pady=(2, 4))
        status = tk.Label(win, text="", bg=BG, fg=TEXT2, font=(FONT_MONO, 8))
        status.pack(anchor="w", padx=14)

        def _run(op):
            res, err = text_transform(src.get("1.0", "end-1c"), op)
            out.delete("1.0", "end")
            if err:
                status.config(text=err, fg=RED)
                return
            out.insert("1.0", res)
            status.config(text=f"完成 · 结果 {len(res)} 字符", fg=GREEN)

        for i, (label, op) in enumerate(self._TEXT_OPS):
            b = tk.Button(ops_f, text=label, bg=PANEL2, fg=CYAN, font=(FONT_UI, 8),
                          bd=0, relief="flat", cursor="hand2",
                          command=lambda o=op: _run(o))
            b.grid(row=i // 8, column=i % 8, padx=2, pady=2, sticky="ew")
            b.bind("<Enter>", lambda e=None, x=b: x.config(bg=PANEL3))
            b.bind("<Leave>", lambda e=None, x=b: x.config(bg=PANEL2))
        for c in range(8):
            ops_f.grid_columnconfigure(c, weight=1)

        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", padx=14, pady=(0, 12))

        def _copy_result():
            t = out.get("1.0", "end-1c")
            if not t:
                return
            self.root.clipboard_clear()
            self.root.clipboard_append(t)
            status.config(text="结果已复制到剪贴板（可直接粘贴）", fg=CYAN)
        tk.Button(btns, text="📋 复制结果", bg=CYAN, fg=BG, font=(FONT_UI, 9, "bold"),
                  bd=0, relief="flat", cursor="hand2", padx=14,
                  command=_copy_result).pack(side="right")

        def _to_source():
            src.delete("1.0", "end")
            src.insert("1.0", out.get("1.0", "end-1c"))
            status.config(text="已用结果替换原文，可继续链式转换", fg=PURPLE)
        tk.Button(btns, text="替换原文", bg=PANEL2, fg=TEXT2, font=(FONT_UI, 9),
                  bd=0, relief="flat", cursor="hand2", padx=10,
                  command=_to_source).pack(side="right", padx=6)
        tk.Button(btns, text="关闭", bg=PANEL2, fg=TEXT2, font=(FONT_UI, 9),
                  bd=0, relief="flat", cursor="hand2", padx=10,
                  command=win.destroy).pack(side="right", padx=6)
        # 挂到实例上便于测试
        win._src, win._out = src, out

    # ═══ 片段库 / 收藏夹（v3.5）═══
    def _save_as_snippet(self):
        text = self._selected_text()
        if not text:
            show_info("无内容", "请先选中一条文本条目")
            return
        self._snippet_edit_dialog(None, preset_text=text)

    def _snippets_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("片段库")
        win.configure(bg=BG)
        win.geometry("760x480")
        win.transient(self.root)
        tk.Label(win, text="◈ 片段库", bg=BG, fg=CYAN,
                 font=(FONT_UI, 12, "bold")).pack(anchor="w", padx=14, pady=(10, 2))
        tk.Label(win, text="常用文本收藏（话术 / 命令 / 地址）· 双击即复制到剪贴板",
                 bg=BG, fg=TEXT2, font=(FONT_UI, 8)).pack(anchor="w", padx=14)
        bar = tk.Frame(win, bg=BG)
        bar.pack(fill="x", padx=14, pady=(8, 4))
        holder = tk.Frame(win, bg=BG)
        holder.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        cols = ("分组", "名称", "内容预览", "使用")
        tree = ttk.Treeview(holder, columns=cols, show="headings")
        vs = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vs.set)
        for lb, w in zip(cols, [110, 170, 380, 60]):
            tree.heading(lb, text=lb)
            tree.column(lb, width=w, anchor="w" if lb != "使用" else "center")
        vs.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        status = tk.Label(win, text="", bg=BG, fg=TEXT2, font=(FONT_MONO, 8))
        status.pack(anchor="w", padx=14, pady=(0, 8))
        state = {"items": []}

        def refresh():
            if not win.winfo_exists() or not tree.winfo_exists():
                return
            state["items"] = self._read_snippets()
            children = tree.get_children()
            if children:
                tree.delete(*children)
            for it in sorted(state["items"], key=lambda x: (x.get("group", ""), x.get("name", ""))):
                prev = str(it.get("text", "")).replace("\n", " ")[:52]
                tree.insert("", "end", iid=it.get("id") or uuid4_str(),
                            values=(it.get("group", "") or "未分组", it.get("name", ""),
                                    prev, it.get("uses", 0)))
            status.config(text=f"共 {len(state['items'])} 条片段")

        def _sel():
            sel = tree.selection()
            if not sel:
                return None
            state["items"] = self._read_snippets()
            return next((x for x in state["items"] if x.get("id") == sel[0]), None)

        def _copy(e=None):
            it = _sel()
            if not it:
                return
            self.root.clipboard_clear()
            self.root.clipboard_append(str(it.get("text", "")))
            if not self._mutate_snippet("use", it):
                return
            refresh(); tree.selection_set(it["id"])
            status.config(text=f"已复制「{it.get('name','')}」到剪贴板 · 可直接粘贴", fg=CYAN)
        tree.bind("<Double-Button-1>", _copy)

        def _add():
            self._snippet_edit_dialog(None, on_done=refresh)
        def _edit():
            it = _sel()
            if not it:
                show_info("未选择", "请先选中一条片段", parent=win); return
            self._snippet_edit_dialog(it, on_done=refresh)
        def _del():
            it = _sel()
            if not it:
                show_info("未选择", "请先选中一条片段", parent=win); return
            if not ask_yesno("确认删除", f"删除片段「{it.get('name','')}」？", parent=win, danger=True):
                return
            if not self._mutate_snippet("delete", it):
                return
            refresh(); status.config(text="已删除", fg=ORANGE)

        for txt, cmd, col in (("➕ 新增", _add, GREEN), ("✏ 编辑", _edit, CYAN),
                              ("📋 复制", _copy, CYAN), ("🗑 删除", _del, RED)):
            b = tk.Button(bar, text=txt, bg=PANEL2, fg=col, font=(FONT_UI, 9),
                          bd=0, relief="flat", cursor="hand2", command=cmd)
            b.pack(side="left", padx=4, pady=2)
            b.bind("<Enter>", lambda e=None, x=b: x.config(bg=PANEL3))
            b.bind("<Leave>", lambda e=None, x=b: x.config(bg=PANEL2))
        refresh()

    def _read_snippets(self):
        data = load_snippets()
        result, seen = [], set()
        for raw in data if isinstance(data, list) else []:
            if not isinstance(raw, dict):
                continue
            rid = raw.get("id")
            if not isinstance(rid, str) or not rid or rid in seen:
                continue
            seen.add(rid)
            item = dict(raw)
            for key in ("name", "group", "text"):
                item[key] = item.get(key) if isinstance(item.get(key), str) else ""
            uses = item.get("uses", 0)
            item["uses"] = uses if type(uses) is int and uses >= 0 else 0
            result.append(item)
        return result

    def _mutate_snippet(self, action, original=None, changes=None):
        """Re-read on every write; optimistic content check across editor windows."""
        self._assert_owner()
        items = self._read_snippets()
        current = next((x for x in items if original and x["id"] == original["id"]), None)
        if action != "add":
            if current is None or (action in ("edit", "delete") and any(
                    current.get(k, "") != original.get(k, "") for k in ("name", "group", "text"))):
                show_warning("片段已更改", "另一窗口已修改或删除此片段，请重新打开后操作")
                return False
        if action == "use":
            current["uses"] += 1
        elif action == "delete":
            items.remove(current)
        elif action == "edit":
            current.update(changes)
        elif action == "add":
            items.append(dict(changes, id=uuid4_str(), uses=0,
                ts=datetime.datetime.now().astimezone().isoformat(timespec="seconds")))
        else:
            raise ValueError("Unknown snippet action")
        if not save_snippets(items):
            show_error("保存失败", "片段库未保存，请检查磁盘和权限")
            return False
        return True

    def _snippet_edit_dialog(self, item, preset_text="", on_done=None):
        """新增/编辑片段。item=None 表示新增"""
        win = tk.Toplevel(self.root)
        win.title("编辑片段" if item else "新增片段")
        win.configure(bg=BG)
        win.geometry("560x400")
        win.transient(self.root)
        tk.Label(win, text="◈ 片段名称", bg=BG, fg=TEXT2,
                 font=(FONT_UI, 9)).pack(anchor="w", padx=14, pady=(12, 2))
        name_v = tk.StringVar(value=(item or {}).get("name", ""))
        tk.Entry(win, textvariable=name_v, bg=PANEL2, fg=TEXT, font=(FONT_UI, 10),
                 relief="flat", insertbackground=CYAN, highlightthickness=1,
                 highlightbackground=BORDER).pack(fill="x", padx=14, ipady=3)
        tk.Label(win, text="分组（可留空，用于归类，如：客服话术 / 常用命令）", bg=BG,
                 fg=TEXT2, font=(FONT_UI, 9)).pack(anchor="w", padx=14, pady=(10, 2))
        groups = sorted({x.get("group", "") for x in self._read_snippets() if x.get("group")})
        group_v = tk.StringVar(value=(item or {}).get("group", ""))
        ttk.Combobox(win, textvariable=group_v, values=groups).pack(fill="x", padx=14)
        tk.Label(win, text="片段内容", bg=BG, fg=TEXT2,
                 font=(FONT_UI, 9)).pack(anchor="w", padx=14, pady=(10, 2))
        txt = tk.Text(win, height=8, bg=PANEL2, fg=TEXT, font=(FONT_MONO, 9),
                      relief="flat", wrap="word", insertbackground=CYAN)
        txt.pack(fill="both", expand=True, padx=14)
        txt.insert("1.0", (item or {}).get("text", "") or preset_text)
        status = tk.Label(win, text="", bg=BG, fg=ORANGE, font=(FONT_MONO, 8))
        status.pack(anchor="w", padx=14)

        def _save():
            name = name_v.get().strip()
            body = txt.get("1.0", "end-1c")
            if not name:
                status.config(text="请填写片段名称"); return
            if not body.strip():
                status.config(text="片段内容不能为空"); return
            if not self._mutate_snippet("edit" if item else "add", item,
                    {"name": name, "group": group_v.get().strip(), "text": body}):
                return
            win.destroy()
            if on_done:
                try: on_done()
                except tk.TclError: pass  # Parent library may have been destroyed.

        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", padx=14, pady=(6, 12))
        tk.Button(btns, text="✔ 保存", bg=CYAN, fg=BG, font=(FONT_UI, 9, "bold"),
                  bd=0, relief="flat", cursor="hand2", padx=16, pady=2,
                  command=_save).pack(side="right")
        tk.Button(btns, text="取消", bg=PANEL2, fg=TEXT2, font=(FONT_UI, 9),
                  bd=0, relief="flat", cursor="hand2", padx=12, pady=2,
                  command=win.destroy).pack(side="right", padx=6)

    def _pin(self):
        self._assert_owner()
        ids = self._sel_ids()
        if not ids: return
        h = self._by_id(ids[0])
        if h:
            h["pinned"] = not h.get("pinned", False)
            self._save_history(); self._render_hist()

    def _open_url(self):
        ids = self._sel_ids()
        if not ids: return
        h = self._by_id(ids[0])
        if not h: return
        from urllib.parse import urlsplit
        import webbrowser
        text = str(h.get("text", "")).strip()
        if text.lower().startswith("www."):
            text = "https://" + text
        try:
            url = urlsplit(text)
            if (url.scheme.lower() not in ("http", "https") or not url.hostname
                    or url.username is not None or url.password is not None
                    or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in text)
                    or "\\" in text):
                raise ValueError("Only HTTP(S) URLs without credentials are supported")
            url.port  # Validate malformed/out-of-range ports before opening.
        except ValueError:
            show_warning("不是链接", "选中的内容不是有效的 HTTP(S) URL")
            return
        try:
            if not webbrowser.open(text):
                show_warning("打开失败", "未能启动默认浏览器")
        except Exception as exc:
            show_error("打开失败", str(exc))

    def _delete_selected(self):
        self._assert_owner()
        ids = set(self._sel_ids())
        if not ids: return
        self.history = [h for h in self.history if h.get("id") not in ids]
        self._save_history(); self._render_hist()

    def _clear_all(self):
        self._assert_owner()
        if ask_yesno("确认清空", "确定清空全部剪贴板历史？", danger=True):
            self.history = []
            self._save_history(); self._render_hist()

    def _export(self):
        if not self.history:
            show_info("空", "无数据可导出")
            return
        from tkinter import filedialog
        name = "clipboard_history_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".txt"
        try:
            path = filedialog.asksaveasfilename(parent=self.root, title="导出剪贴板历史",
                initialfile=name, defaultextension=".txt", filetypes=[("Text", "*.txt")])
            if not path:
                return
            rows = []
            for h in self.history:
                stamp = h.get("time", "")
                if len(stamp) == 8 and stamp[2] == ":":
                    stamp += " (日期未知)"
                line = "[" + (stamp or "日期未知") + "] " + h.get("text", "")
                if h.get("type") == "img":
                    line += "\n图片缓存路径（不嵌入图片）: " + h.get("img", "")
                rows.append(line)
            # Exclusive creation: never silently overwrite an existing export or app data.
            with Path(path).open("x", encoding="utf-8") as stream:
                stream.write("\n\n".join(rows))
        except Exception as exc:
            show_error("导出失败", str(exc))
            return
        show_info("已导出", str(path))

    def _select_all(self):
        for iid in self.hist_tree.get_children():
            self.hist_tree.selection_add(iid)

    def _plain_paste(self):
        """PowerToys Advanced Paste 同款功能：把剪贴板内容重写为纯文本，
        去掉网页复制携带的富文本格式"""
        text = clip_get_text()
        if not text:
            show_info("无文本", "当前剪贴板没有可纯文本化的文本内容")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._status.config(text=f"◐ 已转为纯文本（{len(text)} 字符）· 直接 Ctrl+V 粘贴")

    def _quick_copy(self, n):
        children = list(self.hist_tree.get_children())
        if 0 <= n - 1 < len(children):
            self.hist_tree.selection_set(children[n - 1])
            self._copy_selected()


# ═══════════════════════════════════════════
# 模块：磁盘清理
# ═══════════════════════════════════════════

class CleanupModule(BaseModule):
    name = "cleanup"; label = "磁盘清理"; icon = "🧹"; color = GREEN

    def build(self):
        body = self.body
        scan = tk.Frame(body, bg=PANEL)
        scan.pack(fill="x", padx=20, pady=(14, 8))
        tk.Label(scan, text="① 垃圾扫描清理（一键清理系统缓存目录）", bg=PANEL, fg=GREEN,
                 font=(FONT_UI, 13, "bold")).pack(anchor="w", pady=(6, 2))
        tk.Label(scan, text="扫描常见垃圾目录，预估可释放空间", bg=PANEL,
                 fg=TEXT2, font=(FONT_UI, 8)).pack(anchor="w")
        self.total_var = tk.StringVar(value="0.0KB")
        tot = tk.Frame(scan, bg=PANEL)
        tot.pack(fill="x", pady=(6, 4))
        tk.Label(tot, text="预估可释放：", bg=PANEL, fg=TEXT2,
                 font=(FONT_MONO, 9)).pack(side="left")
        tk.Label(tot, textvariable=self.total_var, bg=PANEL,
                 fg=GREEN, font=(FONT_MONO, 12, "bold")).pack(side="left", padx=(4, 0))

        self.list_frame = tk.Frame(body, bg=BG)
        self.list_frame.pack(fill="both", expand=True, padx=20, pady=(2, 8))
        btn_row = tk.Frame(body, bg=BG)
        btn_row.pack(fill="x", padx=20, pady=(0, 14))
        self._mkbtn(btn_row, "🔍 扫描垃圾", self._scan)
        self._mkbtn(btn_row, "🗑 清理选中", self._clean_selected)
        self._mkbtn(btn_row, "☑ 全选/全不选", self._toggle_all, color=YELLOW)
        self._mkbtn(btn_row, "🚿 刷新DNS缓存", self._flush_dns, color=PURPLE)
        self._checks = {}    # iid → 是否勾选
        self._scan_map = {}  # iid → (类别, 路径, pattern)
        self._scan_results = []

    def _mkbtn(self, parent, text, cmd, color=CYAN):
        btn = tk.Button(parent, text=text, bg=PANEL2, fg=color,
                        font=(FONT_UI, 10), bd=0, relief="flat",
                        cursor="hand2", command=cmd)
        btn.pack(side="left", padx=(0, 6), pady=4)
        btn.bind("<Enter>", lambda e=None, b=btn: b.config(bg=PANEL3))
        btn.bind("<Leave>", lambda e=None, b=btn: b.config(bg=PANEL2))

    def _junk_dirs(self):
        """垃圾目录清单：(类别, 路径, 通配pattern, 说明)。
        pattern 仅对扫描计数与删除生效（Explorer 目录只删 thumbcache，保留 iconcache）。"""
        temp = os.environ.get("TEMP", "")
        local = os.environ.get("LOCALAPPDATA", "")
        prog = os.environ.get("PROGRAMDATA", "")
        appdata = os.environ.get("APPDATA", "")
        return [
            ("临时文件", temp, "*", "系统/应用临时文件"),
            ("Chrome缓存", os.path.join(local, "Google\\Chrome\\User Data\\Default\\Cache"),
             "*", "浏览器网页缓存"),
            ("Edge缓存", os.path.join(local, "Microsoft\\Edge\\User Data\\Default\\Cache"),
             "*", "浏览器网页缓存"),
            ("错误报告", os.path.join(prog, "Microsoft\\Windows\\WER\\ReportArchive"),
             "*", "应用崩溃报告归档"),
            ("更新缓存", "C:\\Windows\\SoftwareDistribution\\Download", "*", "Windows 更新安装包"),
            # 只删缩略图缓存（thumbcache_*），保留 iconcache 图标缓存避免桌面图标白屏
            ("缩略图", os.path.join(local, "Microsoft\\Windows\\Explorer"),
             "thumbcache_*.db", "资源管理器缩略图缓存"),
            ("预读取", "C:\\Windows\\Prefetch", "*.pf", "应用预读取（清后首次启动变慢）"),
            ("崩溃转储", os.path.join(local, "CrashDumps"), "*", "应用崩溃内存转储"),
            ("系统转储", r"C:\Windows\Minidump", "*.dmp", "蓝屏小转储文件"),
            ("着色器缓存", os.path.join(local, "D3DSCache"), "*", "DirectX 着色器缓存"),
            ("腾讯日志", os.path.join(appdata, "Tencent\\Logs"), "*", "微信/QQ 日志"),
        ]

    def _safe_roots(self):
        # Environment variables select candidates, never define the allowlist.
        home = str(Path.home())
        local = os.path.join(home, 'AppData', 'Local')
        trusted = [os.path.join(local, *parts) for parts in (
            ('Temp',), ('Google', 'Chrome', 'User Data', 'Default', 'Cache'),
            ('Microsoft', 'Edge', 'User Data', 'Default', 'Cache'),
            ('Microsoft', 'Windows', 'Explorer'), ('CrashDumps',), ('D3DSCache',))]
        trusted += [os.path.join(home, 'AppData', 'Roaming', 'Tencent', 'Logs'),
                    r'C:\ProgramData\Microsoft\Windows\WER\ReportArchive',
                    r'C:\Windows\SoftwareDistribution\Download',
                    r'C:\Windows\Prefetch', r'C:\Windows\Minidump', r'C:\Windows\Temp']
        allowed = {os.path.normcase(os.path.abspath(p)) for p in trusted}
        return [p for _c, p, _pat, _d in self._junk_dirs()
                if p and os.path.isabs(p)
                and os.path.normcase(os.path.abspath(p)) in allowed
                and self._plain_path(p)]

    @staticmethod
    def _plain_path(path):
        # lstat every ancestor: islink alone misses Windows junctions.
        import stat
        try:
            if not path or not os.path.isabs(path) or str(path).startswith(('\\\\', '//')):
                return False
            current = os.path.abspath(path)
            if os.path.normcase(current) != os.path.normcase(os.path.realpath(current)):
                return False
            while True:
                info = os.lstat(current)
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    return False
                parent = os.path.dirname(current)
                if parent == current:
                    return True
                current = parent
        except (OSError, ValueError, TypeError):
            return False

    @staticmethod
    def _contained(path, root):
        """path 是否位于 root 之内（含相等）。

        跨盘（不同盘符）的两个路径没有公共父目录，os.path.commonpath 会直接抛
        ValueError —— 原先这会被外层 except 吞掉后当成"不安全"，导致装在
        D 盘的缓存/软件让磁盘清理与残留扫描静默失效。跨盘一律按"不在其中"。
        """
        try:
            return os.path.commonpath((path, root)) == root
        except (TypeError, ValueError):
            return False

    def _is_safe_clean_path(self, path):
        try:
            if not self._plain_path(path):
                return False, 'Missing, redirected or reparse path'
            rp = os.path.normcase(os.path.realpath(path))
            home = os.path.normcase(os.path.realpath(Path.home()))
            if rp == home or os.path.dirname(rp) == rp or self._contained(home, rp):
                # ^ home 在 rp 里面 = rp 是用户主目录或其祖先（C:\Users、C:\ 这类），保护
                return False, 'Root/home/ancestor is protected'
            for safe in self._safe_roots():
                sp = os.path.normcase(os.path.realpath(safe))
                if self._contained(rp, sp):
                    return True, ''
        except (OSError, ValueError, TypeError):
            pass
        return False, 'Outside trusted cache roots'

    def _clean_file_ok(self, path, base):
        import stat
        try:
            bp = os.path.normcase(os.path.realpath(base))
            fp = os.path.normcase(os.path.realpath(path))
            return (fp != bp and self._contained(fp, bp)
                    and self._is_safe_clean_path(path)[0]
                    and stat.S_ISREG(os.lstat(path).st_mode))
        except (OSError, ValueError):
            return False

    def _walk_clean_files(self, base, pattern, totals):
        if not self._is_safe_clean_path(base)[0]:
            totals['failed'] += 1
            return
        def error(_exc):
            totals['failed'] += 1
        for root, dirs, files in os.walk(base, topdown=True, followlinks=False, onerror=error):
            if not self._is_safe_clean_path(root)[0]:
                totals['skipped'] += len(dirs) + len(files)
                dirs[:] = []
                continue
            keep = [d for d in dirs if self._is_safe_clean_path(os.path.join(root, d))[0]]
            totals['skipped'] += len(dirs) - len(keep)
            dirs[:] = keep
            for name in files:
                if not fnmatch.fnmatch(name, pattern or '*'):
                    continue
                path = os.path.join(root, name)
                if self._clean_file_ok(path, base):
                    yield path
                else:
                    totals['skipped'] += 1

    def _delete_clean_jobs(self, jobs):
        totals = dict(count=0, bytes=0, skipped=0, failed=0)
        for cat, base, pattern in jobs:
            before = totals.copy()
            try:
                allowed = [(c, p, pat) for c, p, pat, _d in self._junk_dirs()]
                if (cat, base, pattern) not in allowed:
                    totals['failed'] += 1
                    continue
                for path in self._walk_clean_files(base, pattern, totals):
                    if self._is_active_file(path) or not self._clean_file_ok(path, base):
                        totals['skipped'] += 1
                        continue
                    try:
                        size = os.lstat(path).st_size
                        os.remove(path)
                    except OSError:
                        totals['failed'] += 1
                    else:
                        totals['count'] += 1
                        totals['bytes'] += size
            except Exception:
                totals['failed'] += 1
            finally:
                self._log_clean(cat, base, totals['count'] - before['count'],
                                totals['skipped'] - before['skipped'],
                                totals['bytes'] - before['bytes'], totals['failed'] - before['failed'])
        return totals

    def _run_clean_jobs(self, jobs):
        if getattr(self, '_clean_busy', False):
            return
        self._clean_busy = True
        q = queue.Queue()
        def work():
            q.put(self._delete_clean_jobs(jobs))
        def poll():
            try:
                result = q.get_nowait()
            except queue.Empty:
                self.root.after(200, poll)
                return
            self._clean_busy = False
            show_info('完成', '已删除 {count} 个文件 ({bytes} 字节); 跳过 {skipped}; 失败 {failed}'.format(**result))
            if self.list_frame.winfo_exists():
                self._scan()
        threading.Thread(target=work, daemon=True).start()
        self.root.after(200, poll)

    def _is_active_file(self, fp):
        """活跃文件豁免：最近 1 小时内修改过的文件视为使用中，跳过不删
        （保护 Office 崩溃恢复文件、进行中的下载等）"""
        try:
            return (time.time() - os.path.getmtime(fp)) < 3600
        except Exception:
            return True  # 拿不到时间戳就当活跃，保守处理

    _CLEAN_LOG = Path.home() / ".unified_toolbox_clean_log.txt"

    def _log_clean(self, cat, path, count, skipped, deleted_bytes=0, failed=0):
        try:
            with open(self._CLEAN_LOG, 'a', encoding='utf-8') as stream:
                stream.write(f'{datetime.datetime.now():%Y-%m-%d %H:%M:%S} [{cat}] {path!r} '
                             f'deleted={count} bytes={deleted_bytes} skipped={skipped} failed={failed}\n')
        except OSError:
            pass

    def _scan(self):
        token = self._clean_scan_token = object()
        self._scan_results = ()
        for w in self.list_frame.winfo_children():
            w.destroy()
        self.total_var.set('扫描中...')
        q = queue.Queue()
        def work():
            results = []
            total = 0
            stats = dict(skipped=0, failed=0)
            try:
                for cat, base, pattern, desc in self._junk_dirs():
                    size = count = 0
                    for path in self._walk_clean_files(base, pattern, stats):
                        try:
                            size += os.lstat(path).st_size
                            count += 1
                        except OSError:
                            stats['failed'] += 1
                    results.append((cat, base, size / 1024, count, pattern, desc))
                    total += size / 1024
            except Exception:
                stats['failed'] += 1
            q.put((tuple(results), total, stats))
        def poll():
            if self._clean_scan_token is not token or not self.list_frame.winfo_exists():
                return
            try:
                results, total, stats = q.get_nowait()
            except queue.Empty:
                self.root.after(200, poll)
                return
            self._scan_results = results
            self._render(total)
            if stats['failed'] or stats['skipped']:
                self.total_var.set(f"{total:.0f}KB (跳过 {stats['skipped']}; 失败 {stats['failed']})")
        threading.Thread(target=work, daemon=True).start()
        self.root.after(200, poll)

    def _render(self, total_kb):
        for w in self.list_frame.winfo_children(): w.destroy()
        total_str = f"{total_kb/1024:.1f}MB" if total_kb > 1024 else f"{total_kb:.0f}KB"
        self.total_var.set(total_str)
        self._checks = {}
        self._scan_map = {}
        if not self._scan_results:
            tk.Label(self.list_frame, text="未发现垃圾文件", bg=PANEL, fg=TEXT2,
                     font=(FONT_UI, 10)).pack(pady=20)
            return
        # 勾选清单（借鉴 CCleaner/Wise 的"逐类勾选"体验）：点"选"列切换 ☑/☐
        cols = [("选", 40), ("类别", 100), ("路径", 380), ("大小", 90), ("文件数", 60), ("说明", 170)]
        tree = ttk.Treeview(self.list_frame, columns=[c[0] for c in cols],
                            show="headings", height=max(4, len(self._scan_results)))
        for lb, w in cols:
            tree.heading(lb, text=lb)
            tree.column(lb, width=w, minwidth=40,
                        anchor="w" if lb in ("类别", "路径", "说明") else "e")
        tree.pack(fill="both", expand=True)
        tree.bind("<Button-1>", self._on_tree_click)
        tree.bind("<Button-3>", self._ctx_clean)
        max_kb = max((r[2] for r in self._scan_results), default=1) or 1
        for cat, path, kb_val, count, pattern, desc in self._scan_results:
            sz = f"{kb_val/1024:.1f}MB" if kb_val > 1024 else f"{kb_val:.0f}KB"
            iid = tree.insert("", "end", values=(
                "☑", cat, path if len(path) <= 46 else path[:43] + "...",
                sz, count, desc))
            self._checks[iid] = True
            self._scan_map[iid] = (cat, path, pattern)
        self._results_tree = tree

    def _on_tree_click(self, event):
        """点击"选"列切换勾选状态"""
        try:
            col = self._results_tree.identify_column(event.x)
            iid = self._results_tree.identify_row(event.y)
        except Exception:
            return
        if col != "#1" or not iid or iid not in self._checks:
            return
        self._checks[iid] = not self._checks.get(iid, True)
        self._results_tree.set(iid, "选", "☑" if self._checks[iid] else "☐")

    def _toggle_all(self):
        if not self._checks:
            show_info("提示", "请先扫描垃圾")
            return
        new_val = not all(self._checks.values())
        for iid in self._checks:
            self._checks[iid] = new_val
            self._results_tree.set(iid, "选", "☑" if new_val else "☐")

    def _checked_jobs(self):
        return [self._scan_map[i] for i, ck in self._checks.items() if ck and i in self._scan_map]

    def _flush_dns(self):
        """ipconfig /flushdns：清除 DNS 解析缓存（借鉴 PC Manager 清理项）"""
        q = queue.Queue()
        def _do():
            try:
                si = subprocess.STARTUPINFO()
                si.dwFlags = subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = 0
                r = subprocess.run("ipconfig /flushdns", capture_output=True, text=True,
                                   timeout=10, startupinfo=si, shell=True,
                                   encoding="gbk", errors="ignore")
                out = (r.stdout or "").strip() or "已刷新"
            except Exception as e:
                out = f"执行失败：{e}"
            q.put(out)
        threading.Thread(target=_do, daemon=True).start()

        def _poll():
            try:
                out = q.get_nowait()
            except queue.Empty:
                self.root.after(200, _poll)
                return
            show_info("刷新DNS缓存", out[:200])
        self.root.after(200, _poll)

    def _sort_results(self, tree, col):
        """点击表头排序（大小按真实字节数——旧版 KB/MB 去掉单位后裸数字比较
        会把 900KB 排到 1.5MB 前面；其余按字母）"""
        items = [(tree.set(k, col), k) for k in tree.get_children()]
        if col == "大小":
            items.sort(key=lambda t: parse_size(t[0]), reverse=True)
        elif col == "文件数":
            items.sort(key=lambda t: int(t[0]), reverse=True)
        else:
            items.sort()
        for i, (val, k) in enumerate(items):
            tree.move(k, "", i)

    def _ctx_clean(self, event):
        """右键菜单：清理选中类别（不依赖勾选状态）"""
        sel = self._results_tree.identify_row(event.y)
        if not sel: return
        self._results_tree.selection_set(sel)
        cat = self._results_tree.set(sel, "类别")
        for c, p, kb_v, n, pat, ds in self._scan_results:
            if c == cat:
                self._clean_one(c, p, pat)
                break

    def _clean_one(self, cat, path, pattern="*"):
        ok, why = self._is_safe_clean_path(path)
        if not ok:
            show_error("安全拦截", f"已拒绝清理 [{cat}]\n{why}")
            return
        if not ask_yesno("确认清理", f"确认清理 [{cat}]？\n{path}\n\n（最近 1 小时内活跃的文件会自动跳过）", danger=True): return
        self._run_clean_jobs(((cat, path, pattern),))

    def _clean_selected(self):
        """只清理勾选的类别（逐类勾选清单模式）"""
        jobs = self._checked_jobs()
        if not self._scan_results:
            self._scan(); return
        if not jobs:
            show_info("未选择", "请先勾选要清理的类别（点击行首 ☑/☐ 切换）")
            return
        # 清理前全量路径安全校验
        for cat, path, pat in jobs:
            ok, why = self._is_safe_clean_path(path)
            if not ok:
                show_error("安全拦截", f"已中止批量清理\n[{cat}] {why}")
                return
        kb_total = sum(r[2] for r in self._scan_results
                       if any(j[1] == r[1] for j in jobs))
        ts = f"{kb_total/1024:.1f}MB" if kb_total > 1024 else f"{kb_total:.0f}KB"
        names = "、".join(j[0] for j in jobs)
        if not ask_yesno("确认清理",
                f"确认清理 {len(jobs)} 个类别？共 {ts}\n[{names}]\n\n"
                f"仅删除系统缓存白名单内文件\n最近 1 小时活跃文件自动跳过", danger=True):
            return
        self._run_clean_jobs(tuple(jobs))

    def start(self): pass
    def stop(self): pass
    def on_show(self): pass


# ═══════════════════════════════════════════
# 模块：软件卸载
# ═══════════════════════════════════════════

def _safe_uninstall_cmd(cmd):
    """规整 UninstallString：只去首尾空白，保留内部引号。
    旧版 strip('"') 会把 "C:\\Program Files\\...\\unins000.exe" /S 的引号剥掉，
    CreateProcess 对无引号带空格路径解析不可靠，导致大量软件卸载失败。
    「引号包 exe + 参数」本就是 CreateProcess 期望的标准格式，原样传即可。"""
    return (cmd or "").strip()


def _make_silent_uninstall(uninstall):
    """批量卸载用：按卸载器类型自动追加静默参数（借鉴 Geek/BCUninstaller）。
    · Inno Setup（unins000.exe 系）→ /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
    · NSIS（uninst*.exe）→ /S
    · MSI → MsiExec /X{GUID} /QN
    识别不了就原样返回（退化为交互向导，无害）。
    返回 (命令, 是否静默)。"""
    cmd = (uninstall or "").strip()
    if not cmd:
        return cmd, False
    low = cmd.lower()
    if "msiexec" in low:
        m = re.search(r"\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\}",
                      cmd, re.I)
        if m:
            return f"MsiExec.exe /X{m.group(0)} /QN", True
        return cmd, False
    if low.startswith('"') and '"' in low[1:]:
        exe_part = low[1:low.index('"', 1)]
    else:
        exe_part = low.split(" ")[0]
    if re.search(r"unins\d+\.exe$", exe_part):
        return cmd + " /VERYSILENT /SUPPRESSMSGBOXES /NORESTART", True
    if "uninst" in exe_part:
        return cmd + " /S", True
    return cmd, False


def _reg_delete_tree(hive, keypath):
    """递归删除注册表键（先清子键再删自身）。仅由残留扫描的
    「Software 根下且命中关键词」校验后的键调用。"""
    import winreg
    try:
        h = winreg.OpenKey(hive, keypath)
    except OSError:
        return False
    try:
        while True:
            try:
                sk = winreg.EnumKey(h, 0)
            except OSError:
                break
            if not _reg_delete_tree(hive, keypath + "\\" + sk):
                break
        winreg.DeleteKey(hive, keypath)
        return True
    except OSError:
        return False
    finally:
        try: winreg.CloseKey(h)
        except Exception: pass


class UninstallModule(BaseModule):
    name = "uninstall"; label = "软件卸载"; icon = "📦"; color = PURPLE

    def build(self):
        body = self.body
        top = tk.Frame(body, bg=PANEL)
        top.pack(fill="x", padx=20, pady=(14, 8))
        tk.Label(top, text="① 已安装软件（卸载 / 残留扫描 / UWP）", bg=PANEL, fg=PURPLE,
                 font=(FONT_UI, 13, "bold")).pack(anchor="w", pady=(6, 0))
        self._cnt = tk.StringVar(value="扫描中...")
        tk.Label(top, textvariable=self._cnt, bg=PANEL, fg=TEXT2,
                 font=(FONT_MONO, 8)).pack(anchor="w")
        btns = tk.Frame(top, bg=PANEL)
        btns.pack(side="right")
        for txt, cmd, clr in (("⬆ 软件更新", self._upgrade_dialog, GREEN),
                              ("📱 UWP 应用", self._uwp_dialog, CYAN),
                              ("📄 导出清单", self._export_inventory, YELLOW)):
            b = tk.Button(btns, text=txt, bg=PANEL2, fg=clr, font=(FONT_UI, 9),
                          bd=0, relief="flat", cursor="hand2", command=cmd)
            b.pack(side="left", padx=(6, 0), pady=(6, 0))
            b.bind("<Enter>", lambda e=None, bb=b: bb.config(bg=PANEL3))
            b.bind("<Leave>", lambda e=None, bb=b: bb.config(bg=PANEL2))

        search = tk.Frame(body, bg=BG)
        search.pack(fill="x", padx=20, pady=(0, 6))
        self.search_var = tk.StringVar()
        self._search_job = None
        # 输入防抖：停手 250ms 才过滤（旧实现每个按键全量重建几百控件，必卡）
        self.search_var.trace_add("write", self._on_search_type)
        self.search_box = tk.Entry(search, textvariable=self.search_var,
                                   bg=PANEL2, fg=TEXT, font=(FONT_MONO, 9),
                                   relief="flat", insertbackground=CYAN, bd=0,
                                   highlightthickness=1, highlightbackground=BORDER,
                                   highlightcolor=CYAN)
        self.search_box.pack(side="left", ipadx=100)
        tk.Label(search, text="  🔍 搜索软件名 / 发布者", bg=BG, fg=MUTED,
                 font=(FONT_UI, 8)).pack(side="left")

        # ── Treeview 列表：原生虚拟化行列（对标控制面板），千行不卡；
        #    真图标由后台线程提取、主线程渐进贴上 ──
        holder = tk.Frame(body, bg=BG)
        holder.pack(fill="both", expand=True, padx=20, pady=(4, 4))
        cols = ("发布者", "安装时间", "大小", "版本")
        self.list_tree = ttk.Treeview(holder, columns=cols, show="tree headings",
                                      height=13, selectmode="extended")
        vs = ttk.Scrollbar(holder, orient="vertical", command=self.list_tree.yview)
        self.list_tree.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.list_tree.pack(side="left", fill="both", expand=True)
        self.list_tree.column("#0", width=390, anchor="w")
        self.list_tree.heading("#0", text="名称", command=lambda: self._sort_by("名称"))
        for lb, w, a in (("发布者", 200, "w"), ("安装时间", 92, "center"),
                         ("大小", 82, "e"), ("版本", 112, "w")):
            self.list_tree.column(lb, width=w, anchor=a)
            self.list_tree.heading(lb, text=lb, command=lambda c=lb: self._sort_by(c))
        self.list_tree.tag_configure("sys", foreground=RED)
        self.list_tree.tag_configure("odd", background=PANEL2)
        self.list_tree.tag_configure("even", background=PANEL)
        self.list_tree.bind("<Button-3>", self._row_menu)
        self.list_tree.bind("<Double-1>", self._on_double)
        self.list_tree.bind("<<TreeviewSelect>>", self._sync_batch_btn)

        btn_row = tk.Frame(body, bg=BG)
        btn_row.pack(fill="x", padx=20, pady=(0, 14))
        self._mkbtn(btn_row, "🔄 刷新列表", self._scan)
        self._batch_btn = self._mkbtn(btn_row, "🗑 卸载选中(0)", self._batch_uninstall, color=RED)
        self._batch_btn.config(state="disabled")
        tk.Label(btn_row, text="Ctrl/Shift 多选批量卸载 · 双击=打开安装目录 · 右键=残留扫描等",
                 bg=BG, fg=MUTED, font=(FONT_UI, 8)).pack(side="left", padx=10)

        self._all_apps = []
        self._apps = []
        self._iid_app = {}
        self._iid_exe = {}
        self._icon_refs = {}
        self._icon_photo = {}   # exe路径 → PhotoImage（跨渲染复用，避免重复创建）
        self._icon_q = queue.Queue()
        self._icon_gen = 0
        self._sort_col = "名称"
        self._sort_desc = False
        self._last_kw = ""
        # 空态提示（筛没时浮在列表中央）
        self._empty_lbl = tk.Label(holder, text="未找到匹配的软件，换个关键词试试", bg=BG,
                                   fg=TEXT2, font=(FONT_UI, 10))
        # 页内快捷键：Delete=卸载选中 · Ctrl+F=定位搜索 · Esc=清空搜索
        self.list_tree.bind("<Delete>", lambda e: self._batch_uninstall() or "break")
        self.list_tree.bind("<Control-f>", lambda e: (self.search_box.focus_set(),
                                                      self.search_box.icursor("end")) or "break")
        self.search_box.bind("<Return>", lambda e: self._filter())
        self.search_box.bind("<Escape>", lambda e: (self.search_var.set("")))
        self._drain_icons()   # 图标渐进加载轮询（页面存续期间）

    def _mkbtn(self, parent, text, cmd, color=PURPLE):
        btn = tk.Button(parent, text=text, bg=PANEL2, fg=color, font=(FONT_UI, 10),
                        bd=0, relief="flat", cursor="hand2", command=cmd)
        btn.pack(side="left", padx=(0, 6), pady=4)
        btn.bind("<Enter>", lambda e=None, b=btn: b.config(bg=PANEL3))
        btn.bind("<Leave>", lambda e=None, b=btn: b.config(bg=PANEL2))
        return btn

    def _scan(self):
        token = self._app_scan_token = object()
        q = queue.Queue()
        def work():
            try:
                q.put(('ok', self._scan_reg()))
            except Exception as exc:
                q.put(('error', str(exc)))
        def poll():
            if self._app_scan_token is not token:
                return
            try:
                kind, result = q.get_nowait()
            except queue.Empty:
                self.root.after(200, poll)
                return
            if kind == 'ok':
                self._all_apps = result
            try:
                if self.list_tree.winfo_exists():
                    if kind == 'ok':
                        self._filter()
                    else:
                        self._cnt.set('扫描失败: ' + result)
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()
        self.root.after(200, poll)

    def _scan_reg(self):
        import winreg
        import math
        from types import MappingProxyType
        paths = [
            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'),
            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'),
            (winreg.HKEY_CURRENT_USER, r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'),
        ]
        apps, seen = [], set()
        for hive, subkey in paths:
            try:
                h = winreg.OpenKey(hive, subkey)
            except OSError:
                continue
            try:
                for i in range(winreg.QueryInfoKey(h)[0]):
                    try:
                        sk = winreg.EnumKey(h, i)
                        hk = winreg.OpenKey(h, sk)
                    except OSError:
                        continue
                    try:
                        def qv(key, default=''):
                            try:
                                return winreg.QueryValueEx(hk, key)[0]
                            except OSError:
                                return default
                        name, uninstall = qv('DisplayName'), qv('UninstallString')
                        if not isinstance(name, str) or not name or name in seen or not uninstall:
                            continue
                        # All fields, especially EstimatedSize, read BEFORE CloseKey.
                        date = qv('InstallDate')
                        size = qv('EstimatedSize', 0)
                        try:
                            size = float(size or 0)
                            if not math.isfinite(size) or size < 0:
                                size = 0
                        except (ValueError, TypeError, OverflowError):
                            size = 0
                        record = dict(name=name, version=qv('DisplayVersion') or '-',
                                      date=self._fmt_date(date) if date else '-', size=size,
                                      uninstall=uninstall, install_dir=qv('InstallLocation') or '',
                                      publisher=qv('Publisher') or qv('DisplayPublisher') or '-',
                                      registry_hive=hive, registry_key=subkey + '\\' + sk)
                        apps.append(MappingProxyType(record))
                        seen.add(name)
                    finally:
                        winreg.CloseKey(hk)
            finally:
                winreg.CloseKey(h)
        return tuple(apps)

    def _fmt_date(self, d):
        if not d: return "-"
        try: return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        except: return "-"

    def _on_search_type(self, *_a):
        # 输入防抖：停手 250ms 才过滤（旧实现每个按键全量重建几百控件，必卡）
        if self._search_job:
            try: self.root.after_cancel(self._search_job)
            except Exception: pass
        self._search_job = self.root.after(250, self._filter)

    def _filter(self, kw=None):
        if kw is not None:
            self.search_var.set(kw)
        kw = self.search_var.get().strip().lower()
        self._last_kw = kw
        self._apps = [dict(a) for a in self._all_apps] if not kw else [
            dict(a) for a in self._all_apps
            if kw in a["name"].lower() or kw in str(a.get("publisher", "")).lower()]
        self._render()

    def _sorted_apps(self):
        col, desc = self._sort_col, self._sort_desc
        def key(a):
            if col == "大小": return a.get("size", 0)
            if col == "安装时间": return str(a.get("date", ""))
            if col == "版本": return str(a.get("version", ""))
            if col == "发布者": return str(a.get("publisher", "")).lower()
            return a["name"].lower()
        return sorted(self._apps, key=key, reverse=desc)

    def _sort_by(self, col):
        if self._sort_col == col:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_col = col
            self._sort_desc = (col == "大小")   # 大小默认从大到小更有用
        self._render()

    # 系统运行库/组件关键词：误卸会导致大量软件无法启动，列表标红警示
    _SYS_COMPONENT_KEYWORDS = [
        "visual c++", "microsoft visual c", " redistributable", "runtime",
        ".net", "directx", "physx", "银光", "sliverlight", "silverlight",
        "windows driver", "intel", "nvidia", "amd ", "realtek",
        "microsoft edge webview", "windows sdk", "建库",
    ]

    def _is_sys_component(self, name):
        nl = str(name).lower()
        return any(k in nl for k in self._SYS_COMPONENT_KEYWORDS)

    def _render(self):
        """Treeview 版渲染：62 项毫秒级，搜索/排序即时响应。
        保留滚动位置与选中行；图标命中缓存直接贴，未命中的才后台提取。"""
        try:
            if not self.list_tree.winfo_exists():
                return
        except Exception:
            return
        tree = self.list_tree
        sel_apps = {id(a) for a in self._selected_apps()}   # 按应用对象身份保持选中
        yv = tree.yview()
        tree.delete(*tree.get_children())
        self._iid_app = {}
        self._iid_exe = {}
        self._icon_refs = {}
        apps = self._sorted_apps()
        pending = []
        for i, a in enumerate(apps):
            sz = (f"{a['size']/1024:.1f}MB" if a["size"] > 1024
                  else (f"{a['size']:.0f}KB" if a["size"] else "-"))
            tags = []
            if self._is_sys_component(a["name"]):
                tags.append("sys")
            tags.append("odd" if i % 2 else "even")
            iid = tree.insert("", "end", text="  " + a["name"][:46],
                              values=(str(a.get("publisher", "-"))[:32],
                                      a.get("date", "-"), sz,
                                      str(a.get("version", "-"))[:18]),
                              tags=tuple(tags))
            self._iid_app[iid] = a
            exe = _exe_path_from_cmd(a.get("uninstall", ""))
            self._iid_exe[iid] = exe
            cached = self._icon_photo.get(exe.lower()) if exe else None
            if cached is not None:
                tree.item(iid, image=cached)
            elif exe:
                pending.append((iid, exe))
            if id(a) in sel_apps:
                tree.selection_add(iid)
        tree.yview_moveto(yv[0])
        # 空态提示（有数据但被筛没）
        if not apps and self._all_apps:
            self._empty_lbl.place(relx=0.5, rely=0.4, anchor="center")
        else:
            self._empty_lbl.place_forget()
        sys_cnt = sum(1 for a in apps if self._is_sys_component(a["name"]))
        total_gb = sum(a.get("size", 0) for a in self._all_apps) / 1024 / 1024
        txt = f"共 {len(self._all_apps)} 个 · 约 {total_gb:.1f} GB"
        if self._last_kw:
            txt += f" · 筛出 {len(apps)} 个"
        if sys_cnt:
            txt += f" · {sys_cnt} 个系统组件标红（误卸会导致软件无法启动）"
        self._cnt.set(txt)
        self._sync_batch_btn()
        # 图标渐进加载：只提取缓存未命中的；带代数戳防跨渲染交错
        if pending:
            self._icon_gen += 1
            gen = self._icon_gen
            threading.Thread(target=self._load_icons_async,
                             args=(gen, pending), daemon=True).start()

    # ── 渐进加载：真图标 + 发布者兜底（GDI/版本资源提取可后台跑；
    #    PhotoImage 必须主线程建 → 队列交主线程逐个贴上。
    #    gen 代数戳：搜索/排序会开启新一轮提取，旧轮结果作废跳过防交错）──
    def _load_icons_async(self, gen, pending):
        for iid, exe in pending:
            if str(self._iid_app.get(iid, {}).get("publisher", "-")) in ("", "-"):
                pub = get_exe_company(exe)
                if pub:
                    self._icon_q.put(("pub", gen, iid, pub))
            pil = get_file_icon_img(exe, 16)
            if pil is not None:
                self._icon_q.put(("icon", gen, iid, (exe, pil)))
        self._icon_q.put(("end", gen, None, None))

    def _drain_icons(self):
        try:
            if not self.list_tree.winfo_exists():
                return   # 页签已切走；回到本页时 build 重启轮询
        except Exception:
            return
        try:
            while True:
                typ, gen, iid, data = self._icon_q.get_nowait()
                if typ == "end":
                    if gen == self._icon_gen:
                        return   # 当前轮提取结束
                    continue   # 旧轮结束标记，继续消费
                if gen != self._icon_gen:
                    continue   # 过期轮次的结果作废
                if typ == "pub":
                    # 发布者兜底回写：数据与界面同步更新（导出/排序可见）
                    a = self._iid_app.get(iid)
                    if a is not None:
                        a["publisher"] = data
                    try:
                        self.list_tree.set(iid, "发布者", str(data)[:32])
                    except Exception:
                        pass
                    continue
                exe_key, pil = data
                try:
                    photo = _PILImageTk.PhotoImage(pil)
                except Exception:
                    continue
                self._icon_refs[iid] = photo       # 按 iid 持引用防 GC
                self._icon_photo[exe_key.lower()] = photo   # 按路径缓存跨渲染复用
                try:
                    self.list_tree.item(iid, image=photo)
                except Exception:
                    pass
        except queue.Empty:
            pass
        self.root.after(120, self._drain_icons)

    # ── 选择 / 批量 ──
    def _selected_apps(self):
        try:
            return [self._iid_app[i] for i in self.list_tree.selection()
                    if i in self._iid_app]
        except Exception:
            return []

    def _sync_batch_btn(self, e=None):
        try:
            n = len(self.list_tree.selection())
        except Exception:
            return
        if hasattr(self, "_batch_btn"):
            self._batch_btn.config(state="normal" if n else "disabled",
                                   text=f"🗑 卸载选中({n})" if n else "🗑 卸载选中(0)")

    def _on_double(self, e):
        apps = self._selected_apps()
        if apps:
            self._open_dir(apps[0])

    def _open_dir(self, app):
        d = app.get("install_dir", "")
        if d and os.path.isdir(d):
            os.startfile(d)
            return
        exe = _exe_path_from_cmd(app.get("uninstall", ""))
        if exe and Path(exe).exists():
            os.startfile(str(Path(exe).parent))
        else:
            show_info("无目录信息", f"[{app['name']}] 没有可用的安装目录记录")

    def _row_menu(self, event):
        iid = self.list_tree.identify_row(event.y)
        if not iid or iid not in self._iid_app:
            return
        if iid not in self.list_tree.selection():
            self.list_tree.selection_set(iid)
        app_ = self._iid_app[iid]
        menu = tk.Menu(self.root, tearoff=0, bg=PANEL2, fg=TEXT,
                       activebackground=PANEL3, activeforeground=PURPLE)
        menu.add_command(label="❌ 卸载", command=lambda: self._uninstall(app_))
        menu.add_command(label="🧹 扫描卸载残留", command=lambda: self._residual_dialog(app_))
        menu.add_command(label="📂 打开安装目录", command=lambda: self._open_dir(app_))
        menu.add_command(label="📋 复制卸载命令",
                         command=lambda: (self.root.clipboard_clear(),
                                          self.root.clipboard_append(app_["uninstall"]),
                                          show_info("已复制", (app_["uninstall"] or "-")[:160])))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _export_inventory(self):
        if not self._all_apps:
            show_info("空", "请先等待扫描完成")
            return
        lines = [f"已安装软件清单  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
                 "=" * 60]
        for a in self._sorted_apps():
            sz = (f"{a['size']/1024:.0f}MB" if a["size"] > 1024
                  else (f"{a['size']:.0f}KB" if a["size"] else "-"))
            lines.append(f"{a['name']}  |  {a.get('publisher','-')}  |  "
                         f"{a.get('date','-')}  |  {sz}  |  {a.get('version','-')}")
        path = Path.home() / f"软件清单_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path.write_text("\n".join(lines), encoding="utf-8")
        show_info("已导出", f"清单已保存到:\n{path}（共 {len(self._all_apps)} 个）")

    # ── 软件更新（winget upgrade，同类产品核心功能）──
    def _upgrade_dialog(self):
        top = tk.Toplevel(self.root)
        top.title("软件更新（winget 官方源）")
        top.configure(bg=BG)
        top.geometry("760x520")
        top.transient(self.root)
        enable_dark_title_bar(top)
        top.update_idletasks()
        try:
            x = self.root.winfo_x() + (self.root.winfo_width() - top.winfo_width()) // 2
            y = self.root.winfo_y() + (self.root.winfo_height() - top.winfo_height()) // 3
            top.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass
        tk.Label(top, text="◈ 可升级软件", bg=BG, fg=GREEN,
                 font=(FONT_UI, 12, "bold")).pack(anchor="w", padx=16, pady=(12, 2))
        status = tk.Label(top, text="正在查询 winget 升级列表…（约 5~20 秒）", bg=BG,
                          fg=TEXT2, font=(FONT_MONO, 8))
        status.pack(anchor="w", padx=16)

        holder = tk.Frame(top, bg=BG)
        holder.pack(fill="both", expand=True, padx=16, pady=(6, 4))
        cols = ("当前版本", "可升级到")
        tree = ttk.Treeview(holder, columns=cols, show="tree headings",
                            height=14, selectmode="extended")
        vs = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vs.set)
        tree.column("#0", width=340, anchor="w")
        tree.heading("#0", text="软件")
        for lb, w in (("当前版本", 130), ("可升级到", 130)):
            tree.column(lb, width=w, anchor="w")
            tree.heading(lb, text=lb)
        vs.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)

        log = tk.Text(top, bg=PANEL2, fg=TEXT2, font=(FONT_MONO, 8), height=6,
                      relief="flat", bd=0, state="disabled", insertbackground=GREEN)
        log.pack(fill="x", padx=16, pady=(4, 4))

        iid_id = {}
        q = queue.Queue()
        upg = {"running": False}
        querying = {"running": False}

        def _log(line):
            log.config(state="normal")
            log.insert("end", line + "\n")
            log.see("end")
            log.config(state="disabled")

        def _query():
            if querying['running'] or not top.winfo_exists():
                return
            querying['running'] = True
            status.config(text="正在查询 winget 升级列表…（约 5~20 秒）")
            def _do():
                try:
                    si = subprocess.STARTUPINFO()
                    si.dwFlags = subprocess.STARTF_USESHOWWINDOW
                    si.wShowWindow = 0
                    r = subprocess.run(["winget", "upgrade"], capture_output=True,
                                       text=True, timeout=60, startupinfo=si,
                                       encoding="gbk", errors="ignore")
                    q.put(("ok", parse_winget_upgrades(r.stdout or "")))
                except Exception as e:
                    q.put(("err", str(e)))
            threading.Thread(target=_do, daemon=True).start()
            top.after(300, _poll)

        def _poll():
            try:
                if not top.winfo_exists():
                    return   # 对话框已关闭
            except Exception:
                return
            try:
                typ, data = q.get_nowait()
            except queue.Empty:
                top.after(300, _poll)
                return
            querying["running"] = False
            if typ == "err":
                status.config(text=f"查询失败：{data[:120]}")
                return
            tree.delete(*tree.get_children())
            iid_id.clear()
            for it in data:
                iid = tree.insert("", "end", text="  " + it["name"][:44],
                                  values=(it["cur"], it["avail"]))
                iid_id[iid] = it["id"]
            if data:
                status.config(text=f"共 {len(data)} 个可升级 · 选中后点下方按钮（升级需联网，静默模式）")
            else:
                status.config(text="✅ 全部软件均为最新，无可升级项 👍")
        _query()

        def _upgrade(targets):
            if upg["running"]:
                show_info("升级中", "当前已有升级任务在进行", parent=top)
                return
            if not targets:
                show_info("未选择", "请先选中要升级的软件", parent=top)
                return
            names = "\n".join(f"  · {t['name']}" for t in targets[:8]) + \
                    ("\n…" if len(targets) > 8 else "")
            if not ask_yesno("确认升级",
                    f"通过 winget 官方源升级 {len(targets)} 个软件？\n{names}", danger=True):
                return
            upg["running"] = True
            def _do():
                for t in targets:
                    q2.put(("log", f"—— 升级 {t['id']} ——"))
                    try:
                        si = subprocess.STARTUPINFO()
                        si.dwFlags = subprocess.STARTF_USESHOWWINDOW
                        si.wShowWindow = 0
                        r = subprocess.run(
                            ["winget", "upgrade", "--id", t["id"], "-e", "--silent",
                             "--accept-package-agreements", "--accept-source-agreements"],
                            capture_output=True, text=True, timeout=1800,
                            startupinfo=si, encoding="gbk", errors="ignore")
                        tail = [l for l in (r.stdout or "").splitlines() if l.strip()][-2:]
                        for l in tail:
                            q2.put(("log", "  " + l.strip()))
                        q2.put(("log", f"  {'✅ 完成' if r.returncode == 0 else '❌ 失败（码 %d）' % r.returncode}"))
                    except Exception as e:
                        q2.put(("log", f"  ❌ 异常：{e}"))
                q2.put(("done", None))
            q2 = queue.Queue()
            threading.Thread(target=_do, daemon=True).start()
            def _poll2():
                try:
                    if not top.winfo_exists():
                        return   # 对话框已关闭（升级线程自行结束）
                except Exception:
                    return
                try:
                    typ, data = q2.get_nowait()
                    if typ == "log":
                        _log(data)
                    else:
                        upg["running"] = False
                        _log("—— 任务结束，自动重新查询升级列表 ——")
                        _query()
                        return
                except queue.Empty:
                    pass
                top.after(400, _poll2)
            _log(f"开始升级 {len(targets)} 项…")
            _poll2()

        def _sel_targets():
            return [{"id": iid_id[i], "name": tree.item(i, "text").strip()}
                    for i in tree.selection() if i in iid_id]
        btnf = tk.Frame(top, bg=BG)
        btnf.pack(fill="x", padx=16, pady=(2, 12))
        tk.Button(btnf, text="⬆ 升级选中", bg=PANEL2, fg=GREEN, font=(FONT_UI, 9, "bold"),
                  bd=0, relief="flat", cursor="hand2",
                  command=lambda: _upgrade(_sel_targets())).pack(side="left")
        tk.Button(btnf, text="⬆⬆ 全部升级", bg=PANEL2, fg=YELLOW, font=(FONT_UI, 9),
                  bd=0, relief="flat", cursor="hand2",
                  command=lambda: _upgrade([{"id": i, "name": tree.item(i, "text").strip()}
                                            for i in iid_id])).pack(side="left", padx=(8, 0))
        tk.Button(btnf, text="🔄 重新查询", bg=PANEL2, fg=CYAN, font=(FONT_UI, 9),
                  bd=0, relief="flat", cursor="hand2",
                  command=_query).pack(side="left", padx=(8, 0))

    def _uninstall(self, app):
        if not app["uninstall"]:
            show_warning("无法卸载", f"[{app['name']}] 没有卸载程序")
            return
        if self._is_sys_component(app["name"]):
            if not ask_yesno("⚠ 系统组件警告",
                    f"[{app['name']}] 是系统组件/运行库。\n\n"
                    f"卸载它可能导致依赖它的游戏、软件无法启动！\n\n"
                    f"确定仍要卸载？", danger=True):
                return
        if not ask_yesno("确认卸载", f"确认卸载 [{app['name']}]？\n卸载后不可恢复。", danger=True): return
        try:
            cmd = _safe_uninstall_cmd(app["uninstall"])
            si = subprocess.STARTUPINFO()
            si.dwFlags = subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            subprocess.Popen(cmd, startupinfo=si)
            show_info("启动卸载", f"已启动 [{app['name']}] 的卸载程序")
            self._chain_residual_watch(app)   # Geek 式串联：条目消失即弹残留扫描
            self._scan()
        except Exception as e:
            show_error("卸载失败", str(e))

    # ── 卸载完成 → 残留扫描串联 ──
    def _app_in_registry(self, name):
        """轻量检查该显示名是否仍存在于卸载注册表。"""
        import winreg
        paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        for hive, sub in paths:
            try:
                k = winreg.OpenKey(hive, sub)
            except OSError:
                continue
            try:
                for i in range(winreg.QueryInfoKey(k)[0]):
                    try:
                        sk = winreg.OpenKey(k, winreg.EnumKey(k, i))
                    except OSError:
                        continue
                    try:
                        if winreg.QueryValueEx(sk, "DisplayName")[0] == name:
                            return True
                    except OSError:
                        continue
                    finally:
                        try: sk.Close()
                        except Exception: pass
            except OSError:
                continue
            finally:
                try: k.Close()
                except Exception: pass
        return False

    def _chain_residual_watch(self, app):
        """后台轮询注册表：该应用条目消失（卸载完成）即经队列回主线程询问残留扫描。
        最多盯 8 分钟；不影响界面（queue+poll 模式）。"""
        q = queue.Queue()
        def _do():
            name = app["name"]
            for _ in range(240):
                time.sleep(2)
                try:
                    if not self._app_in_registry(name):
                        q.put(("gone", name))
                        return
                except Exception:
                    return
            q.put(("timeout", name))
        threading.Thread(target=_do, daemon=True).start()

        def _poll():
            try:
                typ, name = q.get_nowait()
            except queue.Empty:
                self.root.after(2000, _poll)
                return
            if typ != "gone":
                return
            if ask_yesno("卸载完成",
                    f"检测到 [{name}] 已从系统卸载。\n\n是否立即扫描安装残留？"):
                self._residual_dialog({"name": name, "uninstall": app.get("uninstall", ""),
                                       "install_dir": app.get("install_dir", "")})
        self.root.after(2000, _poll)

    def _batch_uninstall(self):
        targets = self._selected_apps()
        if not targets:
            show_info("未选择", "请先选中要卸载的软件（Ctrl/Shift 多选）")
            return
        sys_targets = [a for a in targets if self._is_sys_component(a["name"])]
        names = "\n".join(f"  · {a['name']}" for a in targets)
        warn = ""
        if sys_targets:
            warn = f"\n\n⚠ 其中 {len(sys_targets)} 个是系统组件/运行库（红色标记），卸载后其他软件可能无法运行！"
        if not ask_yesno("确认批量卸载",
                f"将依次启动 {len(targets)} 个卸载程序：\n{names}{warn}\n\n确认继续？", danger=True):
            return
        ok = silent = 0
        for a in targets:
            try:
                cmd, was_silent = _make_silent_uninstall(a["uninstall"])
                si = subprocess.STARTUPINFO()
                si.dwFlags = subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = 0
                subprocess.Popen(cmd, startupinfo=si)
                ok += 1
                if was_silent:
                    silent += 1
            except Exception:
                pass
        show_info("批量卸载",
                            f"已启动 {ok}/{len(targets)} 个卸载程序\n"
                            f"（{silent} 个走静默模式自动完成，其余请在向导中操作）\n\n"
                            f"卸载完成后会自动询问是否扫描安装残留")
        self._chain_batch_residual([a["name"] for a in targets])
        self._scan()

    def _chain_batch_residual(self, names):
        """批量卸载聚合监视：每个名字独立轮询注册表（最多 8 分钟），
        条目消失即上报；主线程聚合后等 10 秒静默期（静默卸载常成批完成），
        再统一询问一次是否扫描残留——避免逐个弹窗轰炸。"""
        q = queue.Queue()
        for name in names:
            def _do(n=name):
                for _ in range(160):
                    time.sleep(3)
                    try:
                        if not self._app_in_registry(n):
                            q.put(("gone", n))
                            return
                    except Exception:
                        return
            threading.Thread(target=_do, daemon=True).start()

        state = {"got": [], "timer": None}
        deadline = time.time() + 600

        def _ask():
            gone = state["got"]
            state["got"] = []
            state["timer"] = None
            if not gone:
                return
            listing = "\n".join(f"  · {n}" for n in gone[:8]) + \
                      ("\n  …" if len(gone) > 8 else "")
            if ask_yesno("卸载完成",
                    f"检测到 {len(gone)} 个软件已卸载：\n{listing}\n\n"
                    f"是否立即扫描安装残留？"):
                for n in gone:
                    self._residual_dialog({"name": n, "uninstall": "", "install_dir": ""})

        def _poll():
            arrived = False
            try:
                while True:
                    typ, name = q.get_nowait()
                    if typ == "gone" and name not in state["got"]:
                        state["got"].append(name)
                        arrived = True
            except queue.Empty:
                pass
            if arrived:
                # 10s 静默期：期间有新完成的项则顺延，之后统一询问
                if state["timer"]:
                    try: self.root.after_cancel(state["timer"])
                    except Exception: pass
                state["timer"] = self.root.after(10000, _ask)
            if time.time() < deadline:
                self.root.after(2000, _poll)
        self.root.after(2000, _poll)

    # ─── 残留扫描（借鉴 Revo：卸载后独立扫描 AppData/ProgramData/注册表）───
    _RESIDUAL_ENV_ROOTS = ("APPDATA", "LOCALAPPDATA", "PROGRAMDATA")
    _RESIDUAL_PF_ROOTS = (r"C:\Program Files", r"C:\Program Files (x86)")

    def _kw_candidates(self, name):
        # Whole app names only; never publisher tokens or substring matches.
        value = re.sub(r'\s*\((?:x64|x86|32-bit|64-bit)\)\s*', ' ', str(name).casefold()).strip()
        value = re.sub(r'\s+[\d.]+\s*$', '', value).strip()
        broad = {'microsoft', 'google', 'adobe', 'tencent', 'mozilla', 'apple',
                 'intel', 'amd', 'nvidia', 'oracle', 'software', 'common files',
                 'shared', 'runtime', 'windows', 'programs', 'apps', 'application',
                 '腾讯', '微软'}
        if len(value) < 3 or value in broad or self._is_sys_component(value):
            return []
        return [value]

    def _owned_residual_dir(self, app_, path):
        # Recorded InstallLocation + exact app leaf + co-located uninstaller.
        # Name-only batch watches intentionally find nothing.
        try:
            keys = self._kw_candidates(app_['name'])
            if not keys or not app_.get('install_dir') or not app_.get('uninstall'):
                return False
            if not CleanupModule._plain_path(path) or not os.path.isdir(path):
                return False
            canonical = lambda p: os.path.normcase(os.path.realpath(p))
            target = canonical(path)
            if target != canonical(app_['install_dir']):
                return False
            if os.path.basename(target).casefold() not in keys:
                return False
            exe = _exe_path_from_cmd(app_['uninstall'])
            if not exe or not os.path.isabs(exe) or canonical(os.path.dirname(exe)) != target:
                return False
            home = str(Path.home())
            bases = list(self._RESIDUAL_PF_ROOTS) + [
                os.path.join(home, 'AppData', 'Local'), os.path.join(home, 'AppData', 'Roaming'),
                r'C:\ProgramData']
            if not any(target != canonical(b) and CleanupModule._contained(target, canonical(b))
                       for b in bases):
                return False
            for other in getattr(self, '_all_apps', ()):
                if other['name'] == app_['name'] or not other.get('install_dir'):
                    continue
                other_path = canonical(other['install_dir'])
                if (CleanupModule._contained(target, other_path)
                        or CleanupModule._contained(other_path, target)):
                    return False
            # Recursive recycle: reject any nested reparse point or unreadable tree.
            def fail(exc):
                raise exc
            for root, dirs, files in os.walk(path, followlinks=False, onerror=fail):
                if not all(CleanupModule._plain_path(os.path.join(root, p)) for p in dirs + files):
                    return False
            return True
        except (OSError, ValueError, TypeError, KeyError):
            return False

    def _scan_residuals(self, app_):
        # Uncertain registry keys are neither offered nor deleted. No broad search.
        path = app_.get('install_dir', '')
        return [('目录', path)] if self._owned_residual_dir(app_, path) else []

    def _residual_dialog(self, app_):
        top = tk.Toplevel(self.root)
        top.title(f"残留扫描 · {app_['name']}")
        top.configure(bg=BG)
        top.geometry("880x520")
        enable_dark_title_bar(top)
        tk.Label(top, text=f"◈ 残留扫描 · {app_['name']}", bg=BG, fg=PURPLE,
                 font=(FONT_UI, 12, "bold")).pack(anchor="w", padx=16, pady=(12, 2))
        status = tk.Label(top, text="正在验证应用专属安装目录…", bg=BG,
                          fg=TEXT2, font=(FONT_MONO, 8))
        status.pack(anchor="w", padx=16)
        tk.Label(top, text="仅提供有归属证据的安装目录；不确定目录及注册表删除已禁用",
                 bg=BG, fg=MUTED, font=(FONT_UI, 8)).pack(anchor="w", padx=16, pady=(0, 6))

        cols = ("类型", "位置")
        tree = ttk.Treeview(top, columns=cols, show="headings")
        tree.heading("类型", text="类型")
        tree.heading("位置", text="位置")
        tree.column("类型", width=70, anchor="w")
        tree.column("位置", width=740, anchor="w")
        vs = ttk.Scrollbar(top, orient="vertical", command=tree.yview)
        vs.pack(side="right", fill="y", padx=(0, 16))
        tree.pack(fill="both", expand=True, padx=(16, 0))
        tree.configure(yscrollcommand=vs.set)
        tree.tag_configure("reg", foreground=ORANGE)
        tree.tag_configure("dir", foreground=TEXT)
        items = {}  # iid → ("目录", path) 或 ("注册表", hname, keypath, hive)

        btnf = tk.Frame(top, bg=BG)
        btnf.pack(fill="x", padx=16, pady=(6, 12))

        def _fill(results):
            for iid in tree.get_children():
                tree.delete(iid)
            items.clear()
            for r in results:
                if r[0] == "目录":
                    iid = tree.insert("", "end", values=("目录", r[1]), tags=("dir",))
                    items[iid] = r
                else:
                    iid = tree.insert("", "end", values=("注册表", f"{r[1]}\\{r[2]}"), tags=("reg",))
                    items[iid] = r
            if not results:
                status.config(text="未发现可验证归属的安装目录（未扫描不确定残留）")
            else:
                n_dir = sum(1 for r in results if r[0] == "目录")
                n_reg = len(results) - n_dir
                status.config(text=f"扫描完成：{n_dir} 个文件目录 + {n_reg} 个注册表键，确认后选中删除")

        scan_state = {'token': None}
        def _do_scan():
            token = scan_state['token'] = object()
            q = queue.Queue()
            status.config(text='正在验证应用专属安装目录…')
            snapshot = dict(app_)
            def work():
                try:
                    q.put(('ok', self._scan_residuals(snapshot)))
                except Exception as exc:
                    q.put(('error', str(exc)))
            def poll():
                if scan_state['token'] is not token or not top.winfo_exists():
                    return
                try:
                    kind, data = q.get_nowait()
                except queue.Empty:
                    top.after(150, poll)
                    return
                if kind == 'ok':
                    _fill(data)
                else:
                    status.config(text='扫描失败: ' + data)
            threading.Thread(target=work, daemon=True).start()
            top.after(150, poll)
        _do_scan()

        def _select_all():
            for iid in tree.get_children():
                tree.selection_add(iid)

        def _delete_selected():
            sel = tree.selection()
            if not sel:
                show_info("未选择", "请先选中要删除的残留行", parent=top)
                return
            n_dir = sum(1 for i in sel if items[i][0] == "目录")
            n_reg = len(sel) - n_dir
            msg = ""
            if n_dir:
                msg += f"· {n_dir} 个目录 → 移入回收站（可还原）\n"
            if n_reg:
                msg += f"· {n_reg} 个注册表键 → 禁止删除\n"
            if not ask_yesno("确认清理",
                    f"确定清理以下残留？\n\n{msg}\n注册表删除已禁用；目录删除前重新验证归属。", parent=top, danger=True):
                return
            d_ok = d_fail = r_ok = r_fail = 0
            for i in sel:
                it = items[i]
                if it[0] == "目录":
                    if not self._owned_residual_dir(app_, it[1]):
                        d_fail += 1
                        continue
                    okk, _ = delete_to_recycle_bin([it[1]])
                    if okk: d_ok += 1
                    else: d_fail += 1
                else:
                    r_fail += 1  # No verified registry ownership/backup.
            parts = []
            if d_ok or d_fail:
                parts.append(f"目录 {d_ok} 成功" + (f" / {d_fail} 失败" if d_fail else ""))
            if r_ok or r_fail:
                parts.append(f"注册表 {r_ok} 成功" + (f" / {r_fail} 失败（可能需要管理员权限）" if r_fail else ""))
            show_info("清理完成", "\n".join(parts) or "无操作", parent=top)
            _do_scan()  # 重扫刷新列表

        self._mkbtn(btnf, "✅ 全选", _select_all)
        self._mkbtn(btnf, "🗑 删除选中", _delete_selected, color=RED)
        self._mkbtn(btnf, "🔄 重扫", _do_scan)
        self._mkbtn(btnf, "✖ 关闭", top.destroy, color=TEXT2)

    def start(self):
        self._scan()   # _scan 自身已是异步安全（内部起线程 + 主线程轮询），勿再包线程
    def stop(self): pass
    def on_show(self): pass

    # ─── UWP / Microsoft Store 应用卸载（Get-AppxPackage / Remove-AppxPackage）───
    _UWP_PROTECTED = ("microsoft.windowsstore", "vclibs", ".net.native", "ui.xaml",
                      "windowsappruntime", "microsoft.services.store",
                      "microsoft.ui.xaml", "microsoft.net.native")

    @staticmethod
    def _ps_encoded(script):
        """PowerShell -EncodedCommand（统一走模块级 ps_encode）"""
        return ps_encode(script)

    @staticmethod
    def _parse_uwp_lines(text):
        """解析 '名称\\tPackageFullName' 行 → [(name, fullname)]，容错处理"""
        apps = []
        seen = set()
        for line in (text or "").splitlines():
            line = line.strip()
            if "\t" not in line:
                continue
            name, fullname = line.split("\t", 1)
            name, fullname = name.strip(), fullname.strip()
            if name and fullname and fullname not in seen:
                seen.add(fullname)
                apps.append((name, fullname))
        return apps

    def _uwp_dialog(self):
        top = tk.Toplevel(self.root)
        top.title("UWP / Microsoft Store 应用")
        top.configure(bg=BG)
        top.geometry("860x540")
        enable_dark_title_bar(top)
        tk.Label(top, text="◈ UWP / Microsoft Store 应用", bg=BG, fg=CYAN,
                 font=(FONT_UI, 12, "bold")).pack(anchor="w", padx=16, pady=(12, 2))
        status = tk.Label(top, text="正在枚举 Appx 包…", bg=BG, fg=TEXT2, font=(FONT_MONO, 8))
        status.pack(anchor="w", padx=16)
        tk.Label(top, text="框架组件/商店等系统关键包已被拦截，仅列出可卸载的应用",
                 bg=BG, fg=MUTED, font=(FONT_UI, 8)).pack(anchor="w", padx=16, pady=(0, 6))

        bar = tk.Frame(top, bg=BG)
        bar.pack(fill="x", padx=16, pady=(0, 6))
        kw_var = tk.StringVar()
        tk.Label(bar, text="🔍", bg=BG, fg=CYAN, font=(FONT_UI, 9)).pack(side="left")
        tk.Entry(bar, textvariable=kw_var, bg=PANEL2, fg=TEXT, font=(FONT_MONO, 9),
                 relief="flat", insertbackground=CYAN, bd=0,
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=CYAN).pack(side="left", ipadx=90, pady=2)

        cols = ("名称", "PackageFullName")
        tree = ttk.Treeview(top, columns=cols, show="headings")
        tree.heading("名称", text="名称")
        tree.heading("PackageFullName", text="PackageFullName")
        tree.column("名称", width=220, anchor="w")
        tree.column("PackageFullName", width=520, anchor="w")
        vs = ttk.Scrollbar(top, orient="vertical", command=tree.yview)
        vs.pack(side="right", fill="y", padx=(0, 16))
        tree.pack(fill="both", expand=True, padx=(16, 0))
        tree.configure(yscrollcommand=vs.set)

        btnf = tk.Frame(top, bg=BG)
        btnf.pack(fill="x", padx=16, pady=(6, 12))
        all_apps = []

        def _refill(*_a):
            kw = kw_var.get().strip().lower()
            tree.delete(*tree.get_children())
            for name, fullname in all_apps:
                if kw and kw not in name.lower() and kw not in fullname.lower():
                    continue
                tree.insert("", "end", values=(name, fullname))
        kw_var.trace_add("write", _refill)

        def _do_scan():
            try:
                script = ("Get-AppxPackage | Where-Object { -not $_.IsFramework } | "
                          "ForEach-Object { $_.DisplayName + \"`t\" + $_.PackageFullName }")
                si = subprocess.STARTUPINFO()
                si.dwFlags = subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = 0
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-EncodedCommand", self._ps_encoded(script)],
                    capture_output=True, text=True, timeout=45, startupinfo=si,
                    encoding="utf-8", errors="ignore")
                apps = self._parse_uwp_lines(r.stdout)
            except Exception as e:
                apps = []
                err = str(e)
            else:
                err = ""
            def _fill():
                nonlocal all_apps
                all_apps = apps
                _refill()
                if err:
                    status.config(text=f"枚举失败：{err[:120]}")
                else:
                    status.config(text=f"共 {len(apps)} 个 UWP 应用（未含框架组件）")
            top.after(0, _fill)
        threading.Thread(target=_do_scan, daemon=True).start()

        def _remove_selected():
            sel = tree.selection()
            if not sel:
                show_info("未选择", "请先选中要卸载的 UWP 应用", parent=top)
                return
            targets = [tree.set(i, "PackageFullName") for i in sel]
            protected = [t for t in targets
                         if any(k in t.lower() for k in self._UWP_PROTECTED)]
            if protected:
                show_error("安全拦截",
                                     "以下为系统关键组件/框架，已禁止卸载：\n" +
                                     "\n".join(f"  · {t}" for t in protected[:5]), parent=top)
                return
            names = "\n".join(f"  · {t}" for t in targets[:8])
            if not ask_yesno("确认卸载",
                    f"卸载 {len(targets)} 个 UWP 应用（当前用户）？\n{names}"
                    + ("\n…" if len(targets) > 8 else ""), parent=top, danger=True):
                return
            ok = 0
            for pkg in targets:
                try:
                    script = f"Remove-AppxPackage -Package '{pkg}'"
                    si = subprocess.STARTUPINFO()
                    si.dwFlags = subprocess.STARTF_USESHOWWINDOW
                    si.wShowWindow = 0
                    subprocess.run(
                        ["powershell", "-NoProfile", "-EncodedCommand", self._ps_encoded(script)],
                        capture_output=True, text=True, timeout=120, startupinfo=si,
                        encoding="utf-8", errors="ignore")
                    ok += 1
                except Exception:
                    pass
            show_info("完成", f"已卸载 {ok}/{len(targets)} 个", parent=top)
            _do_scan()

        self._mkbtn(btnf, "🗑 卸载选中", _remove_selected, color=RED)
        self._mkbtn(btnf, "🔄 刷新", _do_scan)
        self._mkbtn(btnf, "✖ 关闭", top.destroy, color=TEXT2)


# ═══════════════════════════════════════════
# 模块：文件洞察（大文件定位 + 重复文件查找）
# ═══════════════════════════════════════════

class FileModule(BaseModule):
    name = "files"; label = "文件洞察"; icon = "📁"; color = YELLOW

    # 删除禁区：系统目录一律拒绝（宁可误拒不可误删）
    _FORBIDDEN_PREFIXES = ("c:\\windows", "c:\\program files", "c:\\program files (x86)",
                           "c:\\programdata")

    def build(self):
        body = self.body
        top = tk.Frame(body, bg=PANEL)
        top.pack(fill="x", padx=20, pady=(14, 8))
        tk.Label(top, text="② 大文件 / 重复文件（选目录深度洞察）", bg=PANEL, fg=YELLOW,
                 font=(FONT_UI, 13, "bold")).pack(anchor="w", pady=(6, 0))
        tk.Label(top, text="大文件定位 + 重复文件查找 · 删除进回收站可恢复",
                 bg=PANEL, fg=TEXT2, font=(FONT_UI, 8)).pack(anchor="w")
        self._status = tk.Label(top, text="", bg=PANEL, fg=TEXT2,
                                font=(FONT_MONO, 8))
        self._status.pack(anchor="e")

        bar = tk.Frame(body, bg=BG)
        bar.pack(fill="x", padx=20, pady=(0, 6))
        self._dir_var = tk.StringVar(value=str(Path.home() / "Downloads"))
        tk.Label(bar, text="目录：", bg=BG, fg=TEXT2,
                 font=(FONT_UI, 9)).pack(side="left")
        tk.Entry(bar, textvariable=self._dir_var, bg=PANEL2, fg=TEXT,
                 font=(FONT_MONO, 9), relief="flat",
                 insertbackground=YELLOW, bd=0,
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=YELLOW).pack(side="left", padx=6,
                                                     ipadx=110, pady=2)
        self._mkbtn(bar, "📂 选择目录", self._pick_dir)
        self._mkbtn(bar, "🔍 扫描大文件", self._scan_big)
        self._mkbtn(bar, "👥 查找重复文件", self._scan_dup, color=PURPLE)
        self._mkbtn(bar, "✏ 批量重命名", self._rename_dialog, color=GREEN)
        self._mkbtn(bar, "🗑 删除选中（回收站）", self._delete_selected, color=RED)

        cols = ("文件", "大小", "修改时间", "分组")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", height=14)
        for lb, w in zip(cols, [430, 100, 150, 240]):
            self.tree.heading(lb, text=lb, command=lambda c=lb: self._sort(c))
            self.tree.column(lb, width=w, minwidth=50,
                             anchor="w" if lb in ("文件", "分组") else "e")
        vs = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        vs.pack(side="right", fill="y", padx=(0, 20))
        self.tree.pack(fill="both", expand=True, padx=(20, 0), pady=(4, 4))
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.tag_configure("dup", foreground=ORANGE)
        self.tree.tag_configure("big", foreground=YELLOW)

        tk.Label(body, text="提示：重复文件按「大小 → 内容哈希」两级比对，橙色的重复组保留任意一个即可",
                 bg=BG, fg=MUTED, font=(FONT_UI, 8)).pack(anchor="w", padx=20,
                                                          pady=(0, 10))
        self._rows = {}  # iid → 文件路径
        self._scanning = False

    def _mkbtn(self, parent, text, cmd, color=YELLOW):
        btn = tk.Button(parent, text=text, bg=PANEL2, fg=color,
                        font=(FONT_UI, 10), bd=0, relief="flat",
                        cursor="hand2", command=cmd)
        btn.pack(side="left", padx=(0, 6), pady=4)
        btn.bind("<Enter>", lambda e=None, b=btn: b.config(bg=PANEL3))
        btn.bind("<Leave>", lambda e=None, b=btn: b.config(bg=PANEL2))

    def _pick_dir(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(initialdir=self._dir_var.get() or str(Path.home()))
        if d:
            self._dir_var.set(os.path.normpath(d))

    def _set_status(self, s):
        try:
            self._status.config(text=s)
        except Exception:
            pass

    def _walk_files(self, root_dir):
        """遍历目录产出 (path, size, mtime)，跳过无权限/符号链接循环"""
        for r, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                fp = os.path.join(r, f)
                try:
                    st = os.stat(fp)
                    yield fp, st.st_size, st.st_mtime
                except Exception:
                    continue

    def _scan_big(self):
        self._run_scan("大文件", self._do_scan_big)

    def _scan_dup(self):
        self._run_scan("重复文件", self._do_scan_dup)

    def _run_scan(self, title, worker):
        if self._scanning:
            show_info("扫描中", "请等待当前扫描完成")
            return
        root_dir = self._dir_var.get().strip()
        if not os.path.isdir(root_dir):
            show_warning("目录无效", f"目录不存在：\n{root_dir}")
            return
        self._scanning = True
        self._set_status(f"扫描{title}中…")
        q = queue.Queue()
        def _do():
            try:
                q.put(("ok", worker(root_dir)))
            except Exception as e:
                q.put(("err", str(e)))
        threading.Thread(target=_do, daemon=True).start()

        def _poll():
            if not self.tree.winfo_exists():
                self._scanning = False
                return   # 页签已切走
            try:
                typ, data = q.get_nowait()
            except queue.Empty:
                self.root.after(200, _poll)
                return
            if typ == "err":
                self._set_status(f"扫描失败：{data}")
                self._scanning = False
                return
            self._render_rows(title, data)
        self.root.after(200, _poll)

    def _do_scan_big(self, root_dir):
        files = list(self._walk_files(root_dir))
        files.sort(key=lambda x: x[1], reverse=True)
        return [("big", fp, sz, mt, "") for fp, sz, mt in files[:200]]

    def _do_scan_dup(self, root_dir):
        # 第一级：按大小分组（>1MB 才参与，避免海量小文件）
        by_size = {}
        for fp, sz, mt in self._walk_files(root_dir):
            if sz >= 1024 * 1024:
                by_size.setdefault(sz, []).append((fp, mt))
        cand = {sz: lst for sz, lst in by_size.items() if len(lst) > 1}
        rows = []
        # 第二级：采样哈希预筛（首尾 64KB，大文件免整读），
        # 仅采样撞车的文件才做第三级全量 md5——大目录提速一个量级
        group_no = 0
        for sz, lst in sorted(cand.items(), reverse=True):
            if len(lst) > 1:
                by_quick = {}
                for fp, mt in lst:
                    q = self._quick_hash(fp, sz)
                    if q:
                        by_quick.setdefault(q, []).append((fp, mt))
                lst = [f for fl in by_quick.values() if len(fl) > 1 for f in fl]
            by_hash = {}
            for fp, mt in lst:
                h = self._md5(fp)
                if h:
                    by_hash.setdefault(h, []).append((fp, mt))
            for h, fl in by_hash.items():
                if len(fl) < 2:
                    continue
                group_no += 1
                tag = f"组{group_no} · {len(fl)}个 · 各{kb(sz)}"
                for fp, mt in fl:
                    rows.append(("dup", fp, sz, mt, tag))
        return rows

    def _md5(self, fp):
        try:
            h = hashlib.md5()
            with open(fp, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return ""

    def _quick_hash(self, fp, sz):
        """采样哈希：首尾各 64KB + 文件大小（只用于预筛，撞车再全量 md5）"""
        try:
            h = hashlib.md5()
            h.update(str(sz).encode())
            with open(fp, "rb") as f:
                h.update(f.read(65536))
                if sz > 131072:
                    f.seek(sz - 65536)
                    h.update(f.read(65536))
            return h.hexdigest()
        except Exception:
            return ""

    def _render_rows(self, title, rows):
        self._scanning = False
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._rows = {}
        if not rows:
            self._set_status(f"{title}：未发现")
            return
        for kind, fp, sz, mt, tag in rows:
            ts = datetime.datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M") if mt else "-"
            iid = self.tree.insert("", "end", values=(
                fp if len(fp) <= 62 else fp[:59] + "...",
                kb(sz), ts, tag or f"{kb(sz)}"), tags=(kind,))
            self._rows[iid] = fp
        if title == "重复文件":
            dup_files = sum(1 for k, *_ in rows if k == "dup")
            # 可释放 = 每组重复体积 - 每组保留一份的体积
            groups = {}
            for k, _, sz, _, tag in rows:
                if k == "dup":
                    groups.setdefault(tag, []).append(sz)
            reclaim = sum(sum(vs) - vs[0] for vs in groups.values() if len(vs) > 1)
            self._set_status(f"发现 {dup_files} 个重复文件（橙色行），可释放约 {kb(reclaim)}")
        else:
            self._set_status(f"最大 200 个文件，合计 {kb(sum(sz for _, _, sz, _, _ in rows))}")

    def _sort(self, col):
        items = [(self.tree.set(k, col), k) for k in self.tree.get_children()]
        if col == "大小":
            items.sort(key=lambda t: parse_size(t[0]), reverse=True)
        else:
            items.sort()
        for i, (val, k) in enumerate(items):
            self.tree.move(k, "", i)

    # ─── 批量重命名（v3.6）：规则 → 预览 → 执行 → 可撤销 ───
    def _rename_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("批量重命名")
        win.configure(bg=BG)
        win.geometry("880x640")
        win.transient(self.root)
        enable_dark_title_bar(win)
        tk.Label(win, text="◈ 批量重命名", bg=BG, fg=GREEN,
                 font=(FONT_UI, 12, "bold")).pack(anchor="w", padx=16, pady=(12, 2))
        tk.Label(win, text="先预览再执行：改名计划与执行使用同一份计算，所见即所得；"
                           "执行后可一键撤销",
                 bg=BG, fg=TEXT2, font=(FONT_UI, 8)).pack(anchor="w", padx=16)

        drow = tk.Frame(win, bg=BG)
        drow.pack(fill="x", padx=16, pady=(8, 4))
        tk.Label(drow, text="目录", bg=BG, fg=TEXT2, font=(FONT_UI, 9)).pack(side="left")
        dir_var = tk.StringVar(value=self._dir_var.get() or str(Path.home()))
        tk.Entry(drow, textvariable=dir_var, bg=PANEL2, fg=TEXT, font=(FONT_MONO, 9),
                 relief="flat", insertbackground=GREEN, highlightthickness=1,
                 highlightbackground=BORDER, highlightcolor=GREEN).pack(
            side="left", fill="x", expand=True, padx=6, ipady=3)

        def _browse():
            from tkinter import filedialog
            d = filedialog.askdirectory(parent=win, title="选择要重命名的目录")
            if d:
                dir_var.set(d)
        ttk.Button(drow, text="浏览…", command=_browse, width=8).pack(side="left")

        rules = tk.Frame(win, bg=PANEL)
        rules.pack(fill="x", padx=16, pady=(4, 6))
        f1 = tk.Frame(rules, bg=PANEL)
        f1.pack(fill="x", padx=12, pady=(10, 2))
        pre_var = tk.StringVar(); suf_var = tk.StringVar()
        find_var = tk.StringVar(); repl_var = tk.StringVar()
        use_re = tk.BooleanVar(value=False)
        for label, var, w in (("前缀", pre_var, 12), ("后缀", suf_var, 12),
                              ("查找", find_var, 16), ("替换为", repl_var, 16)):
            tk.Label(f1, text=label, bg=PANEL, fg=TEXT2,
                     font=(FONT_UI, 9)).pack(side="left", padx=(0, 4))
            tk.Entry(f1, textvariable=var, width=w, bg=PANEL2, fg=TEXT,
                     font=(FONT_MONO, 9), relief="flat", insertbackground=GREEN,
                     highlightthickness=1, highlightbackground=BORDER
                     ).pack(side="left", padx=(0, 10), ipady=3)
        tk.Checkbutton(f1, text="正则", variable=use_re, bg=PANEL, fg=TEXT2,
                       selectcolor=PANEL3, activebackground=PANEL,
                       activeforeground=GREEN, font=(FONT_UI, 9), bd=0,
                       highlightthickness=0, cursor="hand2").pack(side="left")

        f2 = tk.Frame(rules, bg=PANEL)
        f2.pack(fill="x", padx=12, pady=(4, 10))
        case_var = tk.StringVar(value="keep")
        for val, txt in (("keep", "大小写不变"), ("lower", "转小写"), ("upper", "转大写")):
            tk.Radiobutton(f2, text=txt, variable=case_var, value=val, bg=PANEL,
                           fg=TEXT2, selectcolor=PANEL3, activebackground=PANEL,
                           activeforeground=GREEN, font=(FONT_UI, 9), bd=0,
                           highlightthickness=0, cursor="hand2").pack(side="left", padx=(0, 8))
        tk.Label(f2, text="│  序号", bg=PANEL, fg=MUTED,
                 font=(FONT_UI, 9)).pack(side="left", padx=(6, 4))
        seq_pos = tk.StringVar(value="none")
        for val, txt in (("none", "不加"), ("suffix", "加尾部"), ("prefix", "加头部")):
            tk.Radiobutton(f2, text=txt, variable=seq_pos, value=val, bg=PANEL,
                           fg=TEXT2, selectcolor=PANEL3, activebackground=PANEL,
                           activeforeground=GREEN, font=(FONT_UI, 9), bd=0,
                           highlightthickness=0, cursor="hand2").pack(side="left", padx=(0, 6))
        seq_start = tk.StringVar(value="1"); seq_digits = tk.StringVar(value="2")
        for label, var, w in (("起", seq_start, 4), ("位", seq_digits, 3)):
            tk.Label(f2, text=label, bg=PANEL, fg=MUTED,
                     font=(FONT_UI, 8)).pack(side="left", padx=(4, 2))
            tk.Entry(f2, textvariable=var, width=w, bg=PANEL2, fg=TEXT,
                     font=(FONT_MONO, 9), relief="flat", justify="center",
                     insertbackground=GREEN, highlightthickness=1,
                     highlightbackground=BORDER).pack(side="left", ipady=2)
        ext_var = tk.BooleanVar(value=True)
        tk.Checkbutton(f2, text="扩展名不变", variable=ext_var, bg=PANEL, fg=TEXT2,
                       selectcolor=PANEL3, activebackground=PANEL,
                       activeforeground=GREEN, font=(FONT_UI, 9), bd=0,
                       highlightthickness=0, cursor="hand2").pack(side="left", padx=(12, 0))

        holder = tk.Frame(win, bg=BG)
        holder.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        cols = ("原名", "新名", "状态")
        tree = ttk.Treeview(holder, columns=cols, show="headings", height=12)
        vs = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vs.set)
        for lb, w in zip(cols, [320, 320, 180]):
            tree.heading(lb, text=lb)
            tree.column(lb, width=w, anchor="w")
        tree.tag_configure("bad", foreground=RED)
        tree.tag_configure("ok", foreground=GREEN)
        vs.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        status = tk.Label(win, text="填好规则后点「预览」", bg=BG, fg=TEXT2,
                          font=(FONT_MONO, 8), anchor="w")
        status.pack(fill="x", padx=16)
        state = {"plan": [], "folder": "", "record": []}

        def _collect_rules():
            return dict(
                prefix=pre_var.get(), suffix=suf_var.get(), find=find_var.get(),
                repl=repl_var.get(), use_regex=use_re.get(),
                seq_start=int(seq_start.get() or 1),
                seq_digits=int(seq_digits.get() or 2),
                seq_pos=seq_pos.get(), case=case_var.get(),
                keep_ext=ext_var.get())

        def _preview():
            folder = dir_var.get().strip().strip('"')
            if not os.path.isdir(folder):
                show_warning("路径无效", "目录不存在：" + NL + (folder or "（空）"), parent=win)
                return
            try:
                names = sorted([n for n in os.listdir(folder)
                                if os.path.isfile(os.path.join(folder, n))])
            except OSError as e:
                show_warning("无法读取目录", str(e), parent=win)
                return
            if not names:
                status.config(text="该目录下没有文件", fg=ORANGE)
                return
            try:
                plan = plan_rename(names, existing={n.lower() for n in names},
                                   **_collect_rules())
            except ValueError as e:
                status.config(text=f"规则有误：{e}", fg=RED)
                return
            state["plan"], state["folder"] = plan, folder
            tree.delete(*tree.get_children())
            bad = 0
            for old, new, err in plan:
                if err:
                    bad += 1
                tag = "bad" if err else ("ok" if new != old else "")
                tree.insert("", "end",
                            values=(old, new, err or ("将修改" if new != old else "不变")),
                            tags=(tag,) if tag else ())
            changed = sum(1 for o, n, e in plan if not e and o != n)
            status.config(text=f"共 {len(plan)} 个文件 · 将修改 {changed} 个"
                               + (f" · {bad} 个冲突（红色行不会执行）" if bad else ""),
                          fg=RED if bad else GREEN)

        def _apply():
            if not state["plan"]:
                show_info("未预览", "请先点「预览」生成改名计划", parent=win)
                return
            pairs = [(o, n) for o, n, e in state["plan"] if not e and o != n]
            if not pairs:
                show_info("无需执行", "当前规则不会产生任何改名", parent=win)
                return
            if not ask_yesno("确认执行",
                             f"将重命名 {len(pairs)} 个文件？\n\n执行后可点「撤销」还原。",
                             parent=win, danger=True):
                return
            done, failed, record = apply_rename(state["folder"], pairs)
            state["record"] = record
            # 撤销必须回到"执行改名时"的那个目录：state["folder"] 会被后续
            # 「预览」改写（用户改目录再预览），只存文件名的话撤销就会误作用于新目录
            state["record_folder"] = state["folder"]
            detail = (NL + NL.join(f"  · {o}：{why}" for o, why in failed[:5])) if failed else ""
            if done:
                show_info("执行完成", f"成功重命名 {done} 个文件"
                                     + (f"，{len(failed)} 个跳过{detail}" if failed else ""),
                          parent=win)
            else:
                show_warning("未执行", "全部跳过：" + detail, parent=win)
            _preview()

        def _undo():
            if not state["record"]:
                show_info("无可撤销", "本次还没有执行过的重命名", parent=win)
                return
            folder = state.get("record_folder") or state["folder"]
            n, failed = undo_rename(folder, state["record"])
            state["record"] = []
            show_info("已撤销", f"还原 {n} 个文件名" + (f"，{len(failed)} 个失败" if failed else ""),
                      parent=win)
            dir_var.set(folder)   # 撤销后目录框回到被撤销的那个目录，避免错位误解
            _preview()

        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", padx=16, pady=(4, 12))
        for txt, cmd, col in (("👁 预览", _preview, CYAN),
                              ("✔ 执行改名", _apply, GREEN),
                              ("↩ 撤销", _undo, ORANGE)):
            b = tk.Button(btns, text=txt, bg=PANEL2, fg=col, font=(FONT_UI, 9, "bold"),
                          bd=0, relief="flat", cursor="hand2", padx=14, pady=3,
                          command=cmd)
            b.pack(side="left", padx=(0, 6))
            b.bind("<Enter>", lambda e=None, x=b: x.config(bg=PANEL3))
            b.bind("<Leave>", lambda e=None, x=b: x.config(bg=PANEL2))
        win._preview, win._apply, win._undo = _preview, _apply, _undo
        win._tree, win._dir_var = tree, dir_var
        win._vars = {"pre": pre_var, "suf": suf_var, "find": find_var, "repl": repl_var,
                     "use_re": use_re, "seq_pos": seq_pos, "seq_start": seq_start,
                     "seq_digits": seq_digits, "case": case_var, "ext": ext_var}

    def _delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            show_info("未选择", "请先选中要删除的文件行（可 Ctrl/Shift 多选）")
            return
        paths = [self._rows[i] for i in sel if i in self._rows]
        if not paths:
            return
        # 禁区校验
        for fp in paths:
            rp = os.path.realpath(fp).lower()
            if any(rp.startswith(p) for p in self._FORBIDDEN_PREFIXES):
                show_error("安全拦截", f"系统目录内文件不允许删除：\n{fp}")
                return
        total = sum((os.path.getsize(p) for p in paths if os.path.exists(p)), 0)
        if not ask_yesno("确认删除",
                f"将把 {len(paths)} 个文件移入回收站（共 {kb(total)}）？\n\n"
                f"文件会进入回收站，可随时还原。", danger=True):
            return
        ok, aborted = delete_to_recycle_bin(paths)
        if ok:
            for iid in sel:
                try: self.tree.delete(iid)
                except Exception: pass
            self._set_status(f"已移入回收站 {len(paths)} 个文件")
        elif aborted:
            self._set_status("已取消")
        else:
            show_error("删除失败", "回收站操作失败，请检查文件是否被占用")

    def start(self): pass
    def stop(self): pass
    def on_show(self): pass


# ═══════════════════════════════════════════
# 模块：快速启动（常用工具/文件夹/网址 一键直达）
# ═══════════════════════════════════════════

class LaunchModule(BaseModule):
    name = "launch"; label = "快速启动"; icon = "🚀"; color = GREEN

    LAUNCH_FILE = Path.home() / ".unified_toolbox_quicklaunch.json"
    DEFAULTS = [("任务管理器", "taskmgr.exe"), ("计算器", "calc.exe"),
                ("记事本", "notepad.exe"), ("控制面板", "control"),
                ("服务", "services.msc"), ("注册表编辑器", "regedit"),
                ("设备管理器", "devmgmt.msc"), ("命令提示符", "cmd.exe"),
                ("磁盘管理", "diskmgmt.msc"), ("网络连接", "ncpa.cpl")]

    def build(self):
        body = self.body
        top = tk.Frame(body, bg=PANEL)
        top.pack(fill="x", padx=20, pady=(14, 8))
        tk.Label(top, text="◈ 快速启动", bg=PANEL, fg=GREEN,
                 font=(FONT_UI, 13, "bold")).pack(anchor="w", pady=(6, 0))
        tk.Label(top, text="单击选中 · 双击启动 · 支持程序 / 文件夹 / 网址",
                 bg=PANEL, fg=TEXT2, font=(FONT_UI, 8)).pack(anchor="w")

        bar = tk.Frame(body, bg=BG)
        bar.pack(fill="x", padx=20, pady=(0, 8))
        self._mkbtn(bar, "➕ 添加", self._add)
        self._mkbtn(bar, "✏ 编辑选中", self._edit_sel, color=YELLOW)
        self._mkbtn(bar, "🗑 删除选中", self._del_sel, color=RED)
        self._mkbtn(bar, "🔄 恢复默认", self._restore)

        self.grid = tk.Frame(body, bg=BG)
        self.grid.pack(fill="both", expand=True, padx=20, pady=(0, 14))
        self.grid.grid_columnconfigure((0, 1, 2), weight=1)
        self._sel = None  # 当前选中的条目 (name, target)
        self._cards = {}
        self._load()
        self._render()

    def _mkbtn(self, parent, text, cmd, color=GREEN):
        btn = tk.Button(parent, text=text, bg=PANEL2, fg=color,
                        font=(FONT_UI, 10), bd=0, relief="flat",
                        cursor="hand2", command=cmd)
        btn.pack(side="left", padx=(0, 6), pady=4)
        btn.bind("<Enter>", lambda e=None, b=btn: b.config(bg=PANEL3))
        btn.bind("<Leave>", lambda e=None, b=btn: b.config(bg=PANEL2))

    def _load(self):
        try:
            data = json.loads(self.LAUNCH_FILE.read_text(encoding="utf-8"))
            # JSON 读回是 list，统一转回 tuple——否则 _sel(tuple) 与条目(list)
            # 永不相等，编辑/删除会静默失效
            self.items = ([tuple(x) for x in data]
                          if isinstance(data, list) else list(self.DEFAULTS))
        except Exception:
            self.items = list(self.DEFAULTS)

    def _save(self):
        try:
            self.LAUNCH_FILE.write_text(
                json.dumps(self.items, ensure_ascii=False, indent=1),
                encoding="utf-8")
        except Exception:
            pass

    def _render(self):
        for w in self.grid.winfo_children():
            w.destroy()
        self._cards = {}
        for i, (name, target) in enumerate(self.items):
            r, c = divmod(i, 3)
            sel = self._sel == (name, target)
            card = tk.Frame(self.grid, bg=PANEL2 if sel else PANEL,
                            highlightthickness=1,
                            highlightbackground=GREEN if sel else BORDER)
            card.grid(row=r, column=c, padx=6, pady=6, sticky="nsew")
            tk.Label(card, text="🚀 " + str(name)[:22], bg=card["bg"], fg=TEXT,
                     font=(FONT_UI, 11, "bold"), anchor="w").pack(
                fill="x", padx=12, pady=(10, 2))
            tk.Label(card, text=str(target)[:40], bg=card["bg"], fg=TEXT2,
                     font=(FONT_MONO, 8), anchor="w").pack(
                fill="x", padx=12, pady=(0, 10))
            # e=None 兜底：个别 Tk 时序下事件绑定会被零参数调用，缺省会抛 TypeError
            card.bind("<Button-1>", lambda e=None, n=name, t=target: self._select(n, t))
            card.bind("<Double-1>", lambda e=None, t=target: self._launch(t))
            for child in card.winfo_children():
                child.bind("<Button-1>", lambda e=None, n=name, t=target: self._select(n, t))
                child.bind("<Double-1>", lambda e=None, t=target: self._launch(t))
            self._cards[(name, target)] = card

    def _select(self, name, target):
        # 只改配色、不重建控件——旧实现单击就整体 _render() 销毁重建卡片，
        # 第二次点击落在新建控件上，Tk 的 <Double-1> 判定被打破，
        # 双击启动永远不触发（表现为"点击没反应"）
        if self._sel == (name, target):
            return  # 重复点已选中项：零副作用，保证双击序列完整
        self._sel = (name, target)
        for key, card in self._cards.items():
            is_sel = key == self._sel
            bg = PANEL2 if is_sel else PANEL
            border = GREEN if is_sel else BORDER
            try:
                card.config(bg=bg, highlightbackground=border)
                for child in card.winfo_children():
                    child.config(bg=bg)
            except Exception:
                pass  # 卡片可能已被销毁（切页瞬间）

    def _launch(self, target):
        try:
            t = str(target).strip()
            if t.lower().startswith(("http://", "https://", "www.")):
                os.startfile(t if "://" in t else "https://" + t)
            else:
                os.startfile(os.path.expandvars(t))
        except Exception as e:
            show_error("启动失败", f"无法启动：\n{target}\n\n{e}")

    def _ask(self, title, initial_name="", initial_target=""):
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.configure(bg=PANEL)
        dlg.transient(self.root); dlg.grab_set()
        dlg.resizable(False, False)
        enable_dark_title_bar(dlg)
        tk.Label(dlg, text="名称：", bg=PANEL, fg=TEXT2, font=(FONT_UI, 9)).grid(
            row=0, column=0, sticky="e", padx=(16, 6), pady=(16, 4))
        e1 = tk.Entry(dlg, bg=PANEL2, fg=TEXT, font=(FONT_MONO, 9),
                      relief="flat", insertbackground=GREEN, width=38,
                      highlightthickness=1, highlightbackground=BORDER,
                      highlightcolor=GREEN)
        e1.grid(row=0, column=1, padx=(0, 16), pady=(16, 4), ipady=3)
        e1.insert(0, initial_name)
        tk.Label(dlg, text="目标：", bg=PANEL, fg=TEXT2, font=(FONT_UI, 9)).grid(
            row=1, column=0, sticky="e", padx=(16, 6), pady=4)
        e2 = tk.Entry(dlg, bg=PANEL2, fg=TEXT, font=(FONT_MONO, 9),
                      relief="flat", insertbackground=GREEN, width=38,
                      highlightthickness=1, highlightbackground=BORDER,
                      highlightcolor=GREEN)
        e2.grid(row=1, column=1, padx=(0, 16), pady=4, ipady=3)
        e2.insert(0, initial_target)
        tk.Label(dlg, text="支持 exe/msc/cpl、文件夹路径或网址", bg=PANEL,
                 fg=MUTED, font=(FONT_UI, 8)).grid(row=2, column=1, sticky="w", pady=(0, 4))
        result = {"name": None, "target": None}
        def _ok():
            result["name"] = e1.get().strip()
            result["target"] = e2.get().strip()
            dlg.destroy()
        btnf = tk.Frame(dlg, bg=PANEL)
        btnf.grid(row=3, column=0, columnspan=2, pady=(6, 14))
        tk.Button(btnf, text="确定", bg=PANEL2, fg=GREEN, font=(FONT_UI, 9),
                  bd=0, relief="flat", cursor="hand2", width=10,
                  command=_ok).pack(side="left", padx=8)
        tk.Button(btnf, text="取消", bg=PANEL2, fg=TEXT2, font=(FONT_UI, 9),
                  bd=0, relief="flat", cursor="hand2", width=10,
                  command=dlg.destroy).pack(side="left", padx=8)
        e1.focus_set()
        dlg.wait_window()
        return result["name"], result["target"]

    def _add(self):
        name, target = self._ask("添加启动项")
        if not name or not target:
            return
        self.items.append((name, target))
        self._save(); self._render()

    def _edit_sel(self):
        if not self._sel:
            show_info("未选择", "请先单击选中一个启动项")
            return
        name, target = self._sel
        new_name, new_target = self._ask("编辑启动项", name, target)
        if not new_name or not new_target:
            return
        try:
            idx = next(i for i, it in enumerate(self.items) if tuple(it) == self._sel)
            self.items[idx] = (new_name, new_target)
        except StopIteration:
            pass
        self._sel = (new_name, new_target)
        self._save(); self._render()

    def _del_sel(self):
        if not self._sel:
            show_info("未选择", "请先单击选中一个启动项")
            return
        if ask_yesno("确认删除", f"删除启动项 [{self._sel[0]}]？", danger=True):
            self.items = [it for it in self.items if tuple(it) != self._sel]
            self._sel = None
            self._save(); self._render()

    def _restore(self):
        if not ask_yesno("恢复默认", "恢复为默认系统工具列表？\n（自定义项会被清除）", danger=True):
            return
        self.items = list(self.DEFAULTS)
        self._sel = None
        self._save(); self._render()

    def start(self): pass
    def stop(self): pass
    def on_show(self): pass


# ═══════════════════════════════════════════
# 模块：激活检测（只读检测 + 正版激活辅助，全部官方渠道）
# ═══════════════════════════════════════════

class ActivationModule(BaseModule):
    name = "activation"; label = "激活检测"; icon = "🔑"; color = GREEN

    def build(self):
        self.stop()
        self._view_active = True
        body = self.body
        top = tk.Frame(body, bg=PANEL)
        top.pack(fill="x", padx=20, pady=(12, 8))
        tk.Label(top, text="① 激活状态", bg=PANEL, fg=GREEN,
                 font=(FONT_UI, 13, "bold")).pack(anchor="w", pady=(6, 0))
        tk.Label(top, text="只读检测 Windows/Office 授权状态 · 仅支持自有授权密钥操作",
                 bg=PANEL, fg=TEXT2, font=(FONT_UI, 8)).pack(anchor="w")
        self._refresh_btn = tk.Button(top, text="🔄 刷新", bg=PANEL2, fg=CYAN,
                                      font=(FONT_UI, 9), bd=0, relief="flat",
                                      cursor="hand2", command=self._scan)
        self._refresh_btn.pack(side="right", padx=(0, 6), pady=(6, 0))
        self._refresh_btn.bind("<Enter>", lambda e=None, b=self._refresh_btn: b.config(bg=PANEL3))
        self._refresh_btn.bind("<Leave>", lambda e=None, b=self._refresh_btn: b.config(bg=PANEL2))

        # Windows 卡
        self.win_card = tk.Frame(body, bg=PANEL)
        self.win_card.pack(fill="x", padx=20, pady=(0, 8))
        # Office 卡
        self.off_card = tk.Frame(body, bg=PANEL)
        self.off_card.pack(fill="x", padx=20, pady=(0, 8))
        # 操作卡
        act = tk.Frame(body, bg=PANEL)
        act.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(act, text="② 正版激活辅助", bg=PANEL, fg=CYAN,
                 font=(FONT_UI, 10, "bold")).pack(anchor="w", padx=12, pady=(8, 2))
        tk.Label(act, text="密钥操作仅限你自己拥有授权的键（OEM 预埋键的机器联网即自动激活，无需手动）",
                 bg=PANEL, fg=MUTED, font=(FONT_UI, 8)).pack(anchor="w", padx=12)
        row = tk.Frame(act, bg=PANEL)
        row.pack(anchor="w", padx=12, pady=(4, 10))
        for txt, cmd, clr in (("🔑 安装密钥并激活…", self._install_key_dialog, GREEN),
                              ("🛠 打开系统激活设置", self._open_activation_settings, CYAN),
                              ("📄 生成激活报告", self._export_activation_report, YELLOW)):
            b = tk.Button(row, text=txt, bg=PANEL2, fg=clr, font=(FONT_UI, 9),
                          bd=0, relief="flat", cursor="hand2", command=cmd)
            b.pack(side="left", padx=(0, 6))
            b.bind("<Enter>", lambda e=None, bb=b: bb.config(bg=PANEL3))
            b.bind("<Leave>", lambda e=None, bb=b: bb.config(bg=PANEL2))
        self._loading = None

    # ── 数据扫描（后台线程 → 队列 → 主线程轮询渲染。
    #    后台线程禁止直调 root.after：Tcl 未在主循环时会抛 RuntimeError）──
    def _scan(self):
        if getattr(self, '_scanning', False) or not self._view_active:
            return
        token = self._view_token
        task = self._scan_task = object()
        self._scanning = True
        self._refresh_btn.config(state='disabled', text='查询中…')
        q = queue.Queue()
        def work():
            try:
                win = query_windows_activation(force=True)
                perm, detail = is_permanent_activated(slmgr_xpr_text())
                office, store = query_office_activation(force=True)
                q.put(('ok', (win, perm, detail, office, store)))
            except Exception as exc:
                q.put(('err', str(exc)))
        def poll():
            if not self._view_live(token) or self._scan_task is not task:
                return
            try:
                kind, data = q.get_nowait()
            except queue.Empty:
                self.root.after(300, poll)
                return
            self._scanning = False
            self._scan_task = None
            self._refresh_btn.config(state='normal', text='刷新')
            if kind == 'ok':
                self._render(*data)
            else:
                for w in self.win_card.winfo_children():
                    w.destroy()
                tk.Label(self.win_card, text='查询失败：' + data, bg=PANEL,
                         fg=RED).pack(anchor='w', padx=12, pady=14)
        threading.Thread(target=work, daemon=True).start()
        self.root.after(300, poll)

    def _render(self, win, perm, perm_txt, office, store):
        self._scanning = False
        try:
            self._refresh_btn.config(state="normal", text="🔄 刷新")
        except Exception:
            pass
        # ── Windows 卡 ──
        for w in self.win_card.winfo_children():
            w.destroy()
        head = tk.Frame(self.win_card, bg=PANEL)
        head.pack(fill="x", padx=12, pady=(8, 2))
        tk.Label(head, text="Windows", bg=PANEL, fg=CYAN,
                 font=(FONT_UI, 10, "bold")).pack(side="left")
        ok = win["status_code"] == 1
        badge = tk.Label(head, text=("✅ " if ok else "⚠ ") + win["status"],
                         bg=PANEL, fg=GREEN if ok else (YELLOW if win["status_code"] > 1 else RED),
                         font=(FONT_UI, 10, "bold"))
        badge.pack(side="right")
        rows = [("版本", win["edition"]), ("授权渠道", win["channel"]),
                ("密钥尾号", win["partial"] or "-"), ("激活性质", perm_txt)]
        grid = tk.Frame(self.win_card, bg=PANEL)
        grid.pack(fill="x", padx=12, pady=(0, 4))
        for i, (lb, val) in enumerate(rows):
            r, c = divmod(i, 2)
            cell = tk.Frame(grid, bg=PANEL2)
            cell.grid(row=r, column=c, padx=2, pady=2, sticky="nsew")
            grid.grid_columnconfigure((0, 1), weight=1)
            tk.Label(cell, text=lb, bg=PANEL2, fg=TEXT2, font=(FONT_UI, 8),
                     anchor="w").pack(anchor="w", padx=8, pady=(4, 0))
            tk.Label(cell, text=val, bg=PANEL2, fg=TEXT, font=(FONT_MONO, 9, "bold"),
                     anchor="w").pack(anchor="w", padx=8, pady=(0, 4))
        oem_row = tk.Frame(self.win_card, bg=PANEL)
        oem_row.pack(fill="x", padx=12, pady=(2, 10))
        if win["oem_key"]:
            tk.Label(oem_row, text="主板预埋 OEM 键（重装联网自动激活）", bg=PANEL,
                     fg=TEXT2, font=(FONT_UI, 8)).pack(anchor="w")
            kv = tk.Frame(oem_row, bg=PANEL2)
            kv.pack(fill="x", pady=(2, 0))
            tk.Label(kv, text=win["oem_key"], bg=PANEL2, fg=GREEN,
                     font=(FONT_MONO, 10, "bold"), anchor="w").pack(side="left", padx=8, pady=6)
            cp = tk.Button(kv, text="📋 复制", bg=PANEL2, fg=CYAN, font=(FONT_UI, 8),
                           bd=0, relief="flat", cursor="hand2",
                           command=lambda k=win["oem_key"]: self._copy_key(k))
            cp.pack(side="right", padx=6)
        else:
            tk.Label(oem_row, text="主板未预埋 OEM 键（组装机常见；零售/数字许可证授权不受影响）",
                     bg=PANEL, fg=MUTED, font=(FONT_UI, 8)).pack(anchor="w")
        # ── Office 卡 ──
        for w in self.off_card.winfo_children():
            w.destroy()
        tk.Label(self.off_card, text="Office", bg=PANEL, fg=CYAN,
                 font=(FONT_UI, 10, "bold")).pack(anchor="w", padx=12, pady=(8, 2))
        if not office:
            msg = "未检测到已安装授权的 Office" + ("（检测到 Microsoft Store 版）" if store else "")
            tk.Label(self.off_card, text=msg, bg=PANEL, fg=TEXT2,
                     font=(FONT_UI, 9)).pack(anchor="w", padx=12, pady=(0, 10))
        else:
            for it in office:
                row = tk.Frame(self.off_card, bg=PANEL2)
                row.pack(fill="x", padx=12, pady=2)
                o_ok = it["status_code"] == 1
                tk.Label(row, text=("✅ " if o_ok else "⚠ ") + it["name"],
                         bg=PANEL2, fg=TEXT, font=(FONT_UI, 9), anchor="w").pack(
                    side="left", padx=8, pady=5)
                tk.Label(row, text=f"{it['status']} · {it['channel']} · 尾号 {it['partial']}",
                         bg=PANEL2, fg=GREEN if o_ok else YELLOW,
                         font=(FONT_MONO, 8)).pack(side="right", padx=8)
            tk.Frame(self.off_card, bg=PANEL, height=8).pack()

    def _copy_key(self, key):
        self.root.clipboard_clear()
        self.root.clipboard_append(key)
        show_info("已复制", f"OEM 密钥已复制到剪贴板：\n{key}")

    def _open_activation_settings(self):
        try:
            os.startfile("ms-settings:windowsactivation")
        except Exception as e:
            show_error("打开失败", str(e))

    def _install_key_dialog(self):
        """安装自有密钥并联网激活（slmgr /ipk + /ato，需要 UAC 管理员确认）。"""
        dlg = tk.Toplevel(self.root)
        dlg.title("安装密钥并激活")
        dlg.configure(bg=PANEL)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        enable_dark_title_bar(dlg)
        tk.Label(dlg, text="输入你拥有授权的产品密钥", bg=PANEL, fg=TEXT,
                 font=(FONT_UI, 10, "bold")).pack(anchor="w", padx=20, pady=(16, 2))
        tk.Label(dlg, text="格式 XXXXX-XXXXX-XXXXX-XXXXX-XXXXX · 仅限自有授权，\n"
                           "将请求管理员权限执行官方 slmgr /ipk + /ato 联网激活",
                 bg=PANEL, fg=TEXT2, font=(FONT_UI, 8), justify="left").pack(
            anchor="w", padx=20)
        ent = tk.Entry(dlg, bg=PANEL2, fg=TEXT, font=(FONT_MONO, 11), width=34,
                       relief="flat", insertbackground=GREEN,
                       highlightthickness=1, highlightbackground=BORDER,
                       highlightcolor=GREEN)
        ent.pack(padx=20, pady=(10, 4), ipady=4)
        ent.focus_set()
        result = {"key": None}
        def _ok(e=None):
            k = ent.get().strip().upper()
            if re.fullmatch(r"[A-Z0-9]{5}(-[A-Z0-9]{5}){4}", k):
                result["key"] = k
                dlg.destroy()
            else:
                show_warning("格式不对", "密钥应为 5×5 位字母数字，用短横线分隔", parent=dlg)
        btnf = tk.Frame(dlg, bg=PANEL)
        btnf.pack(fill="x", padx=20, pady=(4, 16))
        tk.Button(btnf, text="下一步", bg=PANEL2, fg=GREEN, font=(FONT_UI, 9, "bold"),
                  bd=0, relief="flat", cursor="hand2", width=10, command=_ok).pack(side="right")
        tk.Button(btnf, text="取消", bg=PANEL2, fg=TEXT2, font=(FONT_UI, 9),
                  bd=0, relief="flat", cursor="hand2", width=10,
                  command=dlg.destroy).pack(side="right", padx=(0, 8))
        ent.bind("<Return>", _ok)
        dlg.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dlg.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dlg.winfo_height()) // 3
        dlg.geometry(f"+{max(0, x)}+{max(0, y)}")
        dlg.grab_set(); dlg.wait_window()
        key = result["key"]
        if not key:
            return
        if not ask_yesno("确认激活",
                f"将以下密钥安装到本机并联网激活？\n\n{key}\n\n"
                f"仅限你自己拥有授权的密钥；Windows 会弹出管理员确认（UAC）。",
                danger=True):
            return
        self._begin_activation(key)

    def _export_activation_report(self):
        token = self._view_token
        def _do():
            try:
                win = query_windows_activation()
                xpr = slmgr_xpr_text()
                _, perm_txt = is_permanent_activated(xpr)
                office, store = query_office_activation()
                q.put(("ok", (win, perm_txt, office, store)))
            except Exception as e:
                q.put(("err", str(e)))
        q = queue.Queue()
        threading.Thread(target=_do, daemon=True).start()

        def _poll():
            if not self._view_live(token):
                return
            try:
                typ, data = q.get_nowait()
            except queue.Empty:
                self.root.after(300, _poll)
                return
            if typ == "err":
                show_error("导出失败", data)
                return
            win, perm_txt, office, store = data
            lines = [f"激活状态报告  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
                     "=" * 48, "",
                     f"系统: {get_sys_info()['操作系统']}",
                     f"Windows 授权: {win['status']} · {win['channel']}",
                     f"版本: {win['edition']}",
                     f"激活性质: {perm_txt}",
                     f"主板预埋 OEM 键: {'有（' + win['oem_key'][-5:] + ' 结尾）' if win['oem_key'] else '无'}",
                     ""]
            if office:
                lines.append("[Office]")
                for it in office:
                    lines.append(f"  · {it['name']}: {it['status']} · {it['channel']}")
            else:
                lines.append("[Office] 未检测到已安装授权的产品" +
                             ("（有 Microsoft Store 版）" if store else ""))
            lines.append("")
            lines.append("说明: 本报告由 统一工具箱 只读检测生成，数据来自微软官方 SoftwareLicensing 接口。")
            path = Path.home() / f"激活报告_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            path.write_text("\n".join(lines), encoding="utf-8")
            show_info("已导出", f"报告已保存到:\n{path}")
        self.root.after(300, _poll)

    def start(self):
        self._view_active = True
        self._scan()
    def stop(self):
        self._view_active = False
        self._view_token = object()
        self._scan_task = None
        self._scanning = False
    def on_show(self): pass

    def _view_live(self, token):
        if getattr(self.app, '_closing', False):
            return False
        try:
            return (self._view_active and self._view_token is token
                    and bool(self.body.winfo_exists()))
        except Exception:
            return False

    def _begin_activation(self, key):
        if getattr(self, '_activating', False):
            show_info('激活任务进行中', '请等待现有任务结束。')
            return
        if not re.fullmatch(r'[A-Z0-9]{5}(-[A-Z0-9]{5}){4}', key):
            show_warning('格式不对', '产品密钥格式无效')
            return
        self._activating = True
        token = self._view_token
        q = queue.Queue()
        def work():
            try:
                q.put(self._activation_command(key))
            except Exception as exc:
                q.put(('error', str(exc)))
        def poll():
            if getattr(self.app, '_closing', False):
                return
            try:
                kind, detail = q.get_nowait()
            except queue.Empty:
                self.root.after(300, poll)
                return
            self._activating = False
            if not self._view_live(token):
                return
            if kind == 'completed':
                show_info('命令执行结束（并非激活成功证明）', detail[:600])
            elif kind == 'cancelled':
                show_warning('UAC 已取消', detail[:600])
            else:
                show_warning('激活执行失败', detail[:600])
            self._scan()
        threading.Thread(target=work, daemon=True).start()
        self.root.after(300, poll)

    @staticmethod
    def _activation_command(key):
        # Official user-confirmed license operations only; no ANSI batch file.
        import base64
        def encoded(command):
            return base64.b64encode(command.encode('utf-16le')).decode('ascii')
        def literal(value):
            return "'" + str(value).replace("'", "''") + "'"
        if not re.fullmatch(r'[A-Z0-9]{5}(-[A-Z0-9]{5}){4}', key):
            return 'error', 'Invalid product key format'
        with tempfile.TemporaryDirectory(prefix='utb_activation_') as directory:
            log = Path(directory) / 'result.txt'
            child = (
                "$ErrorActionPreference='Stop'; $rc=0; try { "
                "$slmgr=Join-Path $env:windir 'System32\\slmgr.vbs'; "
                "$hostexe=Join-Path $env:windir 'System32\\cscript.exe'; "
                "& $hostexe //nologo $slmgr /ipk " + literal(key) +
                " | Out-File -Encoding utf8 -LiteralPath " + literal(log) + "; "
                "$rc=$LASTEXITCODE; if ($rc -eq 0) { "
                "& $hostexe //nologo $slmgr /ato | Out-File -Append -Encoding utf8 -LiteralPath " +
                literal(log) + "; $rc=$LASTEXITCODE }; "
                "} catch { $_ | Out-File -Append -Encoding utf8 -LiteralPath " + literal(log) +
                "; $rc=1 }; exit $rc")
            outer = (
                "$ErrorActionPreference='Stop'; try { "
                "$p=Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') "
                "-Verb RunAs -Wait -PassThru -ArgumentList "
                "'-NoProfile -NonInteractive -EncodedCommand " + encoded(child) +
                "'; exit $p.ExitCode } catch { "
                "$e=$_.Exception; while ($null -ne $e) { "
                "if ($e.NativeErrorCode -eq 1223) { Write-Output 'UTB_UAC_CANCELLED'; exit 1223 }; "
                "$e=$e.InnerException }; Write-Output $_; exit 1 }")
            powershell = str(Path(os.environ.get('SystemRoot', r'C:\Windows')) /
                             'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe')
            # No Tk wait, no deletion while elevated child may still write.
            result = subprocess.run([powershell, '-NoProfile', '-NonInteractive',
                                     '-EncodedCommand', encoded(outer)], capture_output=True)
            detail = log.read_text(encoding='utf-8-sig', errors='replace') if log.exists() else ''
            output = (result.stdout or b'') + (result.stderr or b'')
            if b'UTB_UAC_CANCELLED' in output:
                return 'cancelled', '用户取消了管理员权限请求；未完成激活。'
            if result.returncode != 0:
                return 'error', f'退出码 {result.returncode}\n{detail or output.decode(errors="replace")}'
            return 'completed', detail or '命令退出码为 0；请以重新扫描的授权状态为准。'



# ═══════════════════════════════════════════
# 模块：新机配置（预装体检 / winget 装机 / 隐私快设 / 交付报告）
# ═══════════════════════════════════════════

class SetupModule(BaseModule):
    """新机验机页的「隐私快设 + 交付报告」区块。
    激活区块由 ActivationModule 提供，预装体检/winget 装机区块由 SoftwareModule 提供。"""
    name = "setup"; label = "新机配置"; icon = "🧰"; color = ORANGE

    def build(self):
        body = self.body
        # ── 隐私快设 ──
        pv = tk.Frame(body, bg=PANEL)
        pv.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(pv, text="③ 隐私快设（微软文档化的用户级设置，可随时改回）", bg=PANEL, fg=CYAN,
                 font=(FONT_UI, 10, "bold")).pack(anchor="w", padx=12, pady=(8, 2))
        self._pv_vars = {}
        for t in _PRIVACY_TOGGLES:
            var = tk.BooleanVar(value=privacy_toggle_state(t["id"]))
            cb = tk.Checkbutton(pv, text=t["label"], variable=var, bg=PANEL, fg=TEXT,
                                selectcolor=PANEL3, activebackground=PANEL,
                                font=(FONT_UI, 9), bd=0, highlightthickness=0,
                                cursor="hand2", anchor="w")
            cb.pack(fill="x", padx=12, pady=1)
            self._pv_vars[t["id"]] = var
        prow = tk.Frame(pv, bg=PANEL)
        prow.pack(fill="x", padx=12, pady=(4, 10))
        tk.Button(prow, text="✔ 应用勾选设置", bg=PANEL2, fg=YELLOW,
                  font=(FONT_UI, 9, "bold"), bd=0, relief="flat", cursor="hand2",
                  command=self._apply_privacy).pack(side="left")
        tk.Label(prow, text="取消勾选＝恢复系统默认；不影响系统更新与杀毒防护",
                 bg=PANEL, fg=MUTED, font=(FONT_UI, 8)).pack(side="left", padx=10)

        # ── 交付报告 ──
        rp = tk.Frame(body, bg=PANEL)
        rp.pack(fill="x", padx=20, pady=(0, 14))
        tk.Label(rp, text="④ 新机交付报告（配置 + 激活 + 磁盘，给买家看）", bg=PANEL, fg=CYAN,
                 font=(FONT_UI, 10, "bold")).pack(anchor="w", padx=12, pady=(8, 2))
        tk.Button(rp, text="📄 生成交付报告", bg=PANEL2, fg=ORANGE,
                  font=(FONT_UI, 9, "bold"), bd=0, relief="flat", cursor="hand2",
                  command=self._export_delivery).pack(anchor="w", padx=12, pady=(0, 12))

    def start(self): pass
    def stop(self): pass
    def on_show(self): pass

    # ── 隐私快设 ──
    def _apply_privacy(self):
        changes = [(tid, var.get()) for tid, var in self._pv_vars.items()
                   if var.get() != privacy_toggle_state(tid)]
        if not changes:
            show_info("无改动", "勾选状态与当前系统设置一致")
            return
        summary = "\n".join(
            f"  · {'关闭' if off else '恢复'}：{t['label']}"
            for tid, off in changes for t in _PRIVACY_TOGGLES if t["id"] == tid)
        if not ask_yesno("确认应用",
                f"将修改 {len(changes)} 项系统隐私设置？\n{summary}\n\n"
                f"均为微软文档化的用户级设置，可随时回来勾掉还原。", danger=True):
            return
        for tid, off in changes:
            privacy_toggle_apply(tid, off)
        for tid, var in self._pv_vars.items():
            var.set(privacy_toggle_state(tid))
        show_info("已应用", f"已更新 {len(changes)} 项隐私设置并即时生效")

    # ── 交付报告 ──
    def _export_delivery(self):
        def _do():
            try:
                info = get_sys_info()
                extra = get_extra_info()
                win = query_windows_activation()
                xpr = slmgr_xpr_text()
                _, perm_txt = is_permanent_activated(xpr)
                office, store = query_office_activation()
                q.put(("ok", (info, extra, win, perm_txt, office, store)))
            except Exception as e:
                q.put(("err", str(e)))
        q = queue.Queue()
        threading.Thread(target=_do, daemon=True).start()

        def _poll():
            try:
                typ, data = q.get_nowait()
            except queue.Empty:
                self.root.after(300, _poll)
                return
            if typ == "err":
                show_error("生成失败", data)
                return
            info, extra, win, perm_txt, office, store = data
            lines = [f"新机交付报告  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
                     "=" * 52, "", "[整机配置]"]
            for k, v in info.items():
                lines.append(f"  {k}: {v}")
            for k in ("GPU", "显存", "主板", "磁盘型号", "BIOS", "安全启动"):
                v = extra.get(k)
                if v and v not in ("未知", "-"):
                    lines.append(f"  {k}: {v}")
            lines.append("")
            lines.append("[磁盘]")
            for d in get_disks():
                lines.append(f"  {d['mount']}  {kb(d['used'])} / {kb(d['total'])}（{d['percent']}%）")
            lines.append("")
            lines.append("[授权状态]")
            lines.append(f"  Windows: {win['status']} · {win['channel']} · {perm_txt}")
            if win["oem_key"]:
                lines.append(f"  主板预埋正版键: 有（{win['oem_key'][-5:]} 结尾，重装联网自动激活）")
            if office:
                for it in office:
                    lines.append(f"  Office: {it['name']} — {it['status']}")
            else:
                lines.append("  Office: " + ("Microsoft Store 版" if store else "未安装"))
            up = time.time() - psutil.boot_time()
            lines.append("")
            lines.append(f"[验机] 开机时长 {int(up)//3600} 小时（新机应接近 0）")
            # 硬件验机工具的结果（在验机页执行过才有）
            vf = self.app.modules.get("verify")
            hw = getattr(vf, "_hw_results", {}) if vf else {}
            lines.append("")
            lines.append("[硬件验机]")
            drv = hw.get("driver")
            if drv is None:
                lines.append("  驱动检查：未执行")
            elif not drv:
                lines.append("  驱动检查：✅ 无异常设备")
            else:
                lines.append(f"  驱动检查：⚠ {len(drv)} 个问题设备")
                for p2 in drv[:6]:
                    lines.append(f"      · {p2['name']}（{p2['why']}）")
            pxr = hw.get("pixel")
            lines.append("  屏幕坏点：" + (f"已遍历 {pxr[0]}/{pxr[1]} 色（人工目视确认）" if pxr else "未执行"))
            kbr = hw.get("keyboard")
            lines.append("  键盘鼠标：" + (f"已测 {kbr[0]}/{kbr[1]} 键" if kbr else "未执行"))
            lines.append("数据来源：微软官方 SoftwareLicensing 接口与系统 WMI，只读检测。")
            path = Path.home() / f"新机交付报告_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            path.write_text("\n".join(lines), encoding="utf-8")
            show_info("已生成", f"交付报告已保存到:\n{path}")
        self.root.after(300, _poll)


# ═══════════════════════════════════════════
# 合并模块（薄壳容器）：点击页签进入完整场景，
# 内部持有原子模块实例并按流程拼装；子模块注册兼容别名供跨页引用。
# ═══════════════════════════════════════════

class SpaceModule(BaseModule):
    """空间清理 = ① 垃圾扫描清理 + ② 大文件 / 重复文件洞察"""
    name = "space"; label = "空间清理"; icon = "🧹"; color = PURPLE

    def __init__(self, app):
        super().__init__(app)
        self._junk = CleanupModule(app)
        self._files = FileModule(app)

    def build(self):
        top = page_header(self.body, "◈ 空间清理",
                          "垃圾一键清 → 大文件 / 重复文件定位 · 删除进回收站可恢复", PURPLE)
        lk = tk.Button(top, text="🔒 占用查询", bg=PANEL2, fg=ORANGE,
                       font=(FONT_UI, 9, "bold"), bd=0, relief="flat",
                       cursor="hand2", command=self._locks_dialog)
        lk.pack(side="right")
        lk.bind("<Enter>", lambda e=None, b=lk: b.config(bg=PANEL3))
        lk.bind("<Leave>", lambda e=None, b=lk: b.config(bg=PANEL2))
        rp = tk.Button(top, text="🛡 系统还原点", bg=PANEL2, fg=GREEN,
                       font=(FONT_UI, 9, "bold"), bd=0, relief="flat",
                       cursor="hand2", command=self._restore_dialog)
        rp.pack(side="right", padx=(0, 8))
        rp.bind("<Enter>", lambda e=None, b=rp: b.config(bg=PANEL3))
        rp.bind("<Leave>", lambda e=None, b=rp: b.config(bg=PANEL2))
        ed = tk.Button(top, text="🗂 空文件夹", bg=PANEL2, fg=PURPLE,
                       font=(FONT_UI, 9, "bold"), bd=0, relief="flat",
                       cursor="hand2", command=self._empty_dirs_dialog)
        ed.pack(side="right", padx=(0, 8))
        ed.bind("<Enter>", lambda e=None, b=ed: b.config(bg=PANEL3))
        ed.bind("<Leave>", lambda e=None, b=ed: b.config(bg=PANEL2))
        tm = tk.Button(top, text="🗺 体积树图", bg=PANEL2, fg=CYAN,
                       font=(FONT_UI, 9, "bold"), bd=0, relief="flat",
                       cursor="hand2", command=self._treemap_dialog)
        tm.pack(side="right", padx=(0, 8))
        tm.bind("<Enter>", lambda e=None, b=tm: b.config(bg=PANEL3))
        tm.bind("<Leave>", lambda e=None, b=tm: b.config(bg=PANEL2))
        fs = tk.Button(top, text="⚡ 极速搜索", bg=PANEL2, fg=YELLOW,
                        font=(FONT_UI, 9, "bold"), bd=0, relief="flat",
                        cursor="hand2", command=self._fast_search_dialog)
        fs.pack(side="right", padx=(0, 8))
        fs.bind("<Enter>", lambda e=None, b=fs: b.config(bg=PANEL3))
        fs.bind("<Leave>", lambda e=None, b=fs: b.config(bg=PANEL2))
        junk_body = tk.Frame(self.body, bg=BG)
        junk_body.pack(fill="x")
        self._junk.body = junk_body
        self._junk.build()
        files_body = tk.Frame(self.body, bg=BG)
        files_body.pack(fill="x")
        self._files.body = files_body
        self._files.build()

    # ── 空文件夹清理（v3.5 接线：find_empty_dirs 此前是无调用方的孤儿函数）──
    def _empty_dirs_dialog(self):
        """扫描并清理空文件夹。删除前二次校验（仍为空 + 非系统目录）后进回收站。"""
        import tempfile
        win = tk.Toplevel(self.root)
        win.title("空文件夹清理")
        win.configure(bg=BG)
        win.geometry("820x540")
        win.transient(self.root)
        enable_dark_title_bar(win)
        tk.Label(win, text="◈ 空文件夹清理", bg=BG, fg=PURPLE,
                 font=(FONT_UI, 12, "bold")).pack(anchor="w", padx=16, pady=(12, 2))
        tk.Label(win, text="扫描不含任何文件的空目录（Windows / Program Files 等系统目录自动跳过）；"
                           "删除前进回收站，可随时还原",
                 bg=BG, fg=TEXT2, font=(FONT_UI, 8)).pack(anchor="w", padx=16)

        bar = tk.Frame(win, bg=BG)
        bar.pack(fill="x", padx=16, pady=(8, 4))
        var = tk.StringVar(value=tempfile.gettempdir())
        ent = tk.Entry(bar, textvariable=var, bg=PANEL2, fg=TEXT, font=(FONT_MONO, 9),
                       relief="flat", insertbackground=PURPLE, highlightthickness=1,
                       highlightbackground=BORDER, highlightcolor=PURPLE)
        ent.pack(side="left", fill="x", expand=True, ipady=3)
        status = tk.Label(win, text="选好目录后点「扫描」", bg=BG, fg=TEXT2,
                          font=(FONT_MONO, 8), anchor="w")
        status.pack(fill="x", padx=16)

        holder = tk.Frame(win, bg=BG)
        holder.pack(fill="both", expand=True, padx=16, pady=(4, 4))
        tree = ttk.Treeview(holder, columns=("路径",), show="headings",
                            selectmode="extended")
        vs = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vs.set)
        tree.heading("路径", text="空目录路径")
        tree.column("路径", width=760, anchor="w")
        vs.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        alive = {"v": True}
        win.protocol("WM_DELETE_WINDOW", lambda: (alive.update(v=False), win.destroy()))
        q = queue.Queue()

        def _browse():
            from tkinter import filedialog
            d = filedialog.askdirectory(parent=win, title="选择要扫描的目录")
            if d:
                var.set(d)
        tk.Button(bar, text="📂 浏览", bg=PANEL2, fg=TEXT2, font=(FONT_UI, 9),
                  bd=0, relief="flat", cursor="hand2",
                  command=_browse).pack(side="left", padx=4)

        def _fill(found):
            tree.delete(*tree.get_children())
            for p in found:
                tree.insert("", "end", values=(p,))
            status.config(text=(f"发现 {len(found)} 个空文件夹（Ctrl/Shift 可多选）"
                                if found else "没有发现空文件夹，很干净 👍"),
                          fg=GREEN if found else TEXT2)

        def _scan():
            path = var.get().strip().strip('"')
            if not os.path.isdir(path):
                show_warning("路径无效", "目录不存在：" + NL + (path or "（空）"), parent=win)
                return
            status.config(text="扫描中…", fg=TEXT2)
            def _do():
                try:
                    q.put(("ok", find_empty_dirs([path], stop=lambda: not alive["v"])))
                except Exception as e:
                    q.put(("err", str(e)))
            threading.Thread(target=_do, daemon=True).start()
            def _poll():
                try:
                    typ, data = q.get_nowait()
                except queue.Empty:
                    if win.winfo_exists():
                        win.after(250, _poll)
                    return
                if not win.winfo_exists():
                    return
                if typ == "err":
                    status.config(text="扫描失败：" + data[:70], fg=RED)
                    return
                _fill(data)
            win.after(250, _poll)

        def _select_all():
            tree.selection_set(tree.get_children())

        def _delete():
            sels = tree.selection()
            if not sels:
                show_info("未选择", "请先选中要删除的空目录", parent=win)
                return
            paths = [tree.set(i, "路径") for i in sels]
            # 二次校验：扫描到删除之间可能已被写入内容；非空则跳过，绝不强删
            ok_paths, skipped = [], 0
            for p in paths:
                try:
                    if os.path.isdir(p) and not os.listdir(p):
                        ok_paths.append(p)
                    else:
                        skipped += 1
                except OSError:
                    skipped += 1
            if not ok_paths:
                show_info("无需删除", "选中的目录都已被填充或已不存在，已自动跳过", parent=win)
                _scan()
                return
            listing = "\n".join("  · " + p for p in ok_paths[:10]) + \
                      (f"\n  … 共 {len(ok_paths)} 个" if len(ok_paths) > 10 else "")
            if not ask_yesno("确认删除",
                    f"将以下空文件夹移入回收站（可还原）：\n{listing}"
                    + (f"\n\n另有 {skipped} 个已被填充，自动跳过" if skipped else ""),
                    parent=win, danger=True):
                return
            done, aborted = delete_to_recycle_bin(ok_paths)
            status.config(text=(f"已移入回收站 {len(ok_paths)} 个空文件夹"
                                + ("（操作被中止）" if aborted else "")
                                + (f" · 跳过 {skipped} 个" if skipped else "")),
                          fg=GREEN if done else ORANGE)
            _scan()

        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", padx=16, pady=(0, 12))
        for txt, cmd, col in (("🔍 扫描", _scan, CYAN), ("☑ 全选", _select_all, TEXT2),
                              ("🗑 删除选中（回收站）", _delete, RED)):
            b = tk.Button(btns, text=txt, bg=PANEL2, fg=col, font=(FONT_UI, 9, "bold"),
                          bd=0, relief="flat", cursor="hand2", command=cmd)
            b.pack(side="left", padx=(0, 6), pady=2)
            b.bind("<Enter>", lambda e=None, x=b: x.config(bg=PANEL3))
            b.bind("<Leave>", lambda e=None, x=b: x.config(bg=PANEL2))
        win._tree = tree
        win._scan = _scan
        win._var = var
        win._delete = _delete
        _scan()

    # ── 体积树图（v3.7 C 波）：目录大小一图看穿，点击色块下钻 ──
    _TM_PALETTE = ["#2d5b8f", "#8f4a2d", "#3a7d5d", "#7d3a6b", "#6b6b2d",
                   "#3a5d7d", "#7d2d3a", "#2d7d7d", "#5d3a7d", "#4a6b2d"]

    def _treemap_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("体积树图")
        win.configure(bg=BG)
        win.geometry("940x640")
        win.transient(self.root)
        enable_dark_title_bar(win)
        tk.Label(win, text="◈ 体积树图", bg=BG, fg=CYAN,
                 font=(FONT_UI, 12, "bold")).pack(anchor="w", padx=16, pady=(12, 2))
        tk.Label(win, text="色块面积 = 占用体积 · 点击目录色块可下钻，右键或「⬆ 返回」回上一级",
                 bg=BG, fg=TEXT2, font=(FONT_UI, 8)).pack(anchor="w", padx=16)

        bar = tk.Frame(win, bg=BG)
        bar.pack(fill="x", padx=16, pady=(8, 4))
        path_var = tk.StringVar(value=self._dir_var.get() if hasattr(self, "_dir_var")
                                else str(Path.home()))
        tk.Entry(bar, textvariable=path_var, bg=PANEL2, fg=TEXT, font=(FONT_MONO, 9),
                 relief="flat", insertbackground=CYAN, highlightthickness=1,
                 highlightbackground=BORDER, highlightcolor=CYAN).pack(
            side="left", fill="x", expand=True, ipady=3)
        state = {"stack": [], "items": [], "total": 0, "scanning": False}

        def _browse():
            from tkinter import filedialog
            d = filedialog.askdirectory(parent=win, title="选择要分析的目录")
            if d:
                path_var.set(d)
                _scan_dir(d)

        ttk.Button(bar, text="浏览…", command=_browse, width=8).pack(
            side="left", padx=(6, 0))

        # 面包屑导航（点击回任意上级）
        crumb = tk.Label(win, text="", bg=BG, fg=MUTED, font=(FONT_MONO, 8),
                         anchor="w", cursor="hand2")
        crumb.pack(fill="x", padx=16)
        holder = tk.Frame(win, bg=BG)
        holder.pack(fill="both", expand=True, padx=16, pady=(4, 0))
        cv = tk.Canvas(holder, bg=PANEL2, highlightthickness=0)
        cv.pack(fill="both", expand=True)
        status = tk.Label(win, text="输入目录后按回车开始分析", bg=BG, fg=TEXT2,
                          font=(FONT_MONO, 8), anchor="w")
        status.pack(fill="x", padx=16)

        def _fmt(n):
            return kb(n)

        def _render(items, total, path):
            cv.delete("all")
            state["items"] = items
            state["total"] = total
            # 面包屑：D:\a\b\c → 可点分段
            crumb.unbind("<Button-1>")
            crumb.bind("<Button-1>", lambda e: None)
            drive, rest = os.path.splitdrive(path)
            segs = [p for p in rest.split(os.sep) if p]
            crumb.config(text=(drive + os.sep if drive else "") +
                         " › ".join(segs[-4:]) if segs else path)
            big = [it for it in items if it["size"] > 0]
            if not big:
                cv.create_text(cv.winfo_width() // 2 or 440, 240,
                               text="此目录为空或全部子项体积为 0", fill=MUTED,
                               font=(FONT_UI, 10))
                return
            cv.update_idletasks()
            W = max(200, cv.winfo_width() - 8)
            H = max(120, cv.winfo_height() - 8)
            vals = [it["size"] for it in big]
            rects = squarify(vals, 4, 4, W, H)
            pad = 2
            for it, (rx, ry, rw, rh) in zip(big, rects):
                if rw < 4 or rh < 4:
                    continue
                col = self._TM_PALETTE[abs(hash(it["name"])) % len(self._TM_PALETTE)]
                rid = cv.create_rectangle(rx + pad/2, ry + pad/2, rx + rw - pad/2,
                                          ry + rh - pad/2, fill=col, outline=PANEL2)
                label = it["name"]
                if rw > 46 and rh > 15:
                    txt = label if len(label) * 7 < rw - 8 else label[:max(1, int(rw/7)-2)] + "…"
                    cv.create_text(rx + 6, ry + 8, text=txt, fill="#ffffff",
                                   anchor="nw", font=(FONT_UI, 8, "bold"))
                if rw > 60 and rh > 34:
                    cv.create_text(rx + 6, ry + 24, text=_fmt(it["size"]),
                                   fill="#e8e8e8", anchor="nw", font=(FONT_MONO, 7))
                if it["is_dir"]:
                    cv.tag_bind(rid, "<Button-1>",
                                lambda e, p=it["path"]: _scan_dir(p))
                    cv.tag_bind(rid, "<Enter>",
                                lambda e, p=it["path"], n=it["name"]:
                                (cv.config(cursor="hand2"),
                                 status.config(text=f"📂 {n} — {_fmt(it['size'])} · 点击下钻",
                                               fg=CYAN)))
                    cv.tag_bind(rid, "<Leave>",
                                lambda e: (cv.config(cursor=""),
                                           status.config(
                                               text=f"共 {state['total']} 项 · 合计 {_fmt(state['total'])}",
                                               fg=TEXT2)))
                else:
                    cv.tag_bind(rid, "<Double-Button-1>",
                                lambda e, p=it["path"]: os.startfile(
                                    os.path.dirname(p)))
                    cv.tag_bind(rid, "<Enter>",
                                lambda e, n=it["name"]:
                                (cv.config(cursor="hand2"),
                                 status.config(text=f"📄 {n} — {_fmt(it['size'])}",
                                               fg=CYAN)))

        def _scan_dir(path):
            if not os.path.isdir(path):
                show_warning("路径无效", "目录不存在：" + NL + (path or "（空）"), parent=win)
                return
            if state["scanning"]:
                return
            state["scanning"] = True
            status.config(text="◐ 正在统计体积（大目录可能要几秒）…", fg=CYAN)
            cv.delete("all")
            cv.create_text(cv.winfo_width() // 2 or 440, 240,
                           text="扫描中…", fill=MUTED, font=(FONT_UI, 10))
            q = queue.Queue()

            def _do():
                try:
                    items, total, truncated = scan_dir_sizes(path, budget=10.0, top_n=80)
                    q.put((items, total, truncated, path, None))
                except Exception as e:
                    q.put((None, 0, False, path, str(e)))

            threading.Thread(target=_do, daemon=True).start()

            def _poll():
                try:
                    if not win.winfo_exists():
                        return   # 对话框已关闭（扫描线程会自行结束）
                except Exception:
                    return
                try:
                    items, total, truncated, p, err = q.get_nowait()
                except queue.Empty:
                    win.after(200, _poll)
                    return
                state["scanning"] = False
                if err:
                    status.config(text="扫描失败：" + err, fg=RED)
                    return
                # 记录导航栈（下钻用）
                if state["stack"] and state["stack"][-1] != p:
                    state["stack"].append(p)
                elif not state["stack"]:
                    state["stack"] = [p]
                state["stack"] = state["stack"][-12:]
                _render(items, total, p)
                # total 是"字节总和"而不是项数，旧文案会显示成"共 12345678 项"
                status.config(
                    text=f"合计 {_fmt(total)} · 子项 {len(items)} 个"
                         + ("（已达展示上限，仅前 60 项）" if truncated else ""),
                    fg=ORANGE if truncated else TEXT2)

            win.after(200, _poll)

        def _up():
            if len(state["stack"]) >= 2:
                state["stack"].pop()
                _scan_dir(state["stack"][-1])
            else:
                status.config(text="已经在最上层了", fg=TEXT2)

        def _back_home():
            if state["stack"]:
                _scan_dir(state["stack"][0])

        # 回车 = 扫描输入的路径
        for w2 in (path_var,):
            w2.trace_add("write", lambda *a: None)  # 占位，防止误触发
        cv.bind_all("<Return>", lambda e: _scan_dir(path_var.get().strip().strip('"')))
        win.protocol("WM_DELETE_WINDOW",
                     lambda: (cv.unbind_all("<Return>"), win.destroy()))

        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", padx=16, pady=(4, 12))
        for txt, cmd, col in (("🔍 分析", lambda: _scan_dir(path_var.get().strip().strip('"')), CYAN),
                              ("⬆ 返回上级", _up, ORANGE),
                              ("🏠 回到起点", _back_home, TEXT2)):
            b = tk.Button(btns, text=txt, bg=PANEL2, fg=col, font=(FONT_UI, 9, "bold"),
                          bd=0, relief="flat", cursor="hand2", command=cmd)
            b.pack(side="left", padx=(0, 6))
            b.bind("<Enter>", lambda e=None, x=b: x.config(bg=PANEL3))
            b.bind("<Leave>", lambda e=None, x=b: x.config(bg=PANEL2))
        win._scan = _scan_dir
        win._canvas = cv
        win._path_var = path_var
        win._state = state

    # ── 极速文件搜索（v3.6 C 波）：自建索引 + 输入即搜 ──
    def _fast_search_dialog(self):
        """全盘文件秒搜。首次使用需建索引（后台扫描，进度可见），
        之后毫秒级返回；索引含生成时间，太旧会提示重建。"""
        win = tk.Toplevel(self.root)
        win.title("极速文件搜索")
        win.configure(bg=BG)
        win.geometry("780x520")
        win.transient(self.root)
        enable_dark_title_bar(win)
        state = {"entries": [], "ts": 0.0, "building": False,
                 "stop": False, "job": None, "searched": False}

        top = tk.Frame(win, bg=BG)
        top.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(top, text="◈ 极速文件搜索", bg=BG, fg=YELLOW,
                 font=(FONT_UI, 12, "bold")).pack(anchor="w")
        tk.Label(top, text="首次使用先建索引（后台扫描全盘文件名，一次性）· 建好后输入即搜、毫秒级响应",
                 bg=BG, fg=MUTED, font=(FONT_UI, 9)).pack(anchor="w", pady=(2, 0))

        bar = tk.Frame(win, bg=BG)
        bar.pack(fill="x", padx=16, pady=(8, 4))
        ent = tk.Entry(bar, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                       font=(FONT_MONO, 11), bd=0, relief="flat",
                       highlightthickness=1, highlightbackground=BORDER,
                       highlightcolor=CYAN)
        ent.pack(side="left", fill="x", expand=True, ipady=6)
        hint = tk.Label(bar, text="", bg=BG, fg=MUTED, font=(FONT_UI, 9))
        hint.pack(side="left", padx=(8, 0))

        # 索引状态行
        info = tk.Label(win, text="", bg=BG, fg=TEXT2, font=(FONT_UI, 9))
        info.pack(anchor="w", padx=18, pady=(2, 0))

        holder = tk.Frame(win, bg=BG)
        holder.pack(fill="both", expand=True, padx=16, pady=(6, 4))
        cols = (("类型", 50), ("路径", 560), ("所在目录", 130))
        tree = ttk.Treeview(holder, columns=[c[0] for c in cols], show="headings")
        vs = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vs.set)
        for lb, w in cols:
            tree.heading(lb, text=lb)
            tree.column(lb, width=w, minwidth=40,
                        anchor="center" if lb == "类型" else "w")
        tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")

        def _show_info():
            if state["building"]:
                n = state.get("count", 0)
                info.config(text=f"⏳ 正在建索引… 已收录 {n:,} 项（可继续输入，建好自动生效）",
                            fg=CYAN)
            elif state["ts"] > 0:
                age = (time.time() - state["ts"]) / 86400
                info.config(text=f"✓ 索引就绪：{len(state['entries']):,} 项 · "
                                 f"生成于 {time.strftime('%m-%d %H:%M', time.localtime(state['ts']))} "
                                 f"（{age:.1f} 天前）", fg=TEXT2)
            else:
                info.config(text="尚未建索引——点击下方「建索引」开始（扫描期间可做别的事）",
                            fg=MUTED)

        def _do_search(*_):
            kw = ent.get().strip()
            if not kw:
                tree.delete(*tree.get_children())
                state["searched"] = False
                return
            if not state["entries"]:
                return
            t0 = time.perf_counter()
            hits = search_index(state["entries"], kw)
            ms = (time.perf_counter() - t0) * 1000
            tree.delete(*tree.get_children())
            for is_dir, path in hits:
                tree.insert("", "end", values=("📁" if is_dir else "📄",
                                               os.path.basename(path),
                                               os.path.dirname(path)))
            state["searched"] = True
            if hits:
                hint.config(text=f"{len(hits)} 项 · {ms:.0f} ms", fg=GREEN)
            else:
                hint.config(text="无匹配", fg=MUTED)

        def _debounced(*_):
            if state["job"]:
                try:
                    win.after_cancel(state["job"])
                except Exception:
                    pass
            state["job"] = win.after(200, _do_search)

        ent.bind("<KeyRelease>", _debounced)

        def _pick_roots():
            """默认扫描所有本地固定磁盘；光驱/可移动盘不进索引"""
            roots = []
            import string
            for d in psutil.disk_partitions(all=False):
                if d.fstype:  # 有文件系统才是真实磁盘（排除光驱）
                    roots.append(d.device + os.sep)
            if not roots:   # psutil 异常时退回遍历盘符
                for c in string.ascii_uppercase:
                    if os.path.isdir(f"{c}:{os.sep}"):
                        roots.append(f"{c}:{os.sep}")
            # 常见系统/缓存目录不进索引（大而无效）
            return roots, ("\\Windows\\WinSxS", "\\Windows\\Installer",
                           "$Recycle.Bin", "node_modules", "__pycache__",
                           "\\AppData\\Local\\Temp", "\\AppData\\Local\\Microsoft",
                           "\\AppData\\Local\\Packages")

        def _build_index():
            if state["building"]:
                return
            roots, skips = _pick_roots()
            state["building"] = True
            state["stop"] = False
            state["count"] = 0
            _show_info()

            def work():
                def prog(done, cur):
                    # progress 回调在后台线程：只写共享计数，UI 由主线程 _tick 刷新
                    state["count"] = done
                entries = build_file_index(roots, progress=prog,
                                           stop=lambda: state["stop"],
                                           skip_prefixes=skips)
                if state["stop"]:
                    return
                state["entries"] = entries
                ok = save_index(entries)
                state["ts"] = INDEX_FILE.stat().st_mtime if ok and INDEX_FILE.exists() else 0.0
                state["building"] = False
                if not ok:
                    if win.winfo_exists():
                        info.config(text="⚠ 索引保存失败（磁盘满或权限不足）", fg=RED)

            threading.Thread(target=work, daemon=True).start()
            # 进度定时刷新（主线程）
            def _tick():
                if not win.winfo_exists():
                    return
                if state["building"]:
                    _show_info()
                    win.after(500, _tick)
                else:
                    _show_info()
                    if state["ts"] > 0 and ent.get().strip():
                        _do_search()
            win.after(500, _tick)

        def _load_existing():
            entries, ts = load_index()
            if entries:
                state["entries"] = entries
                state["ts"] = ts
            _show_info()

        def _del_index():
            try:
                if INDEX_FILE.exists():
                    INDEX_FILE.unlink()
            except Exception:
                pass
            state["entries"] = []
            state["ts"] = 0.0
            state["searched"] = False
            tree.delete(*tree.get_children())
            hint.config(text="")
            _show_info()

        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", padx=16, pady=(4, 12))
        for txt, cmd, col in (("⚡ 建索引 / 更新", _build_index, YELLOW),
                              ("🗑 删除索引", _del_index, RED)):
            b = tk.Button(btns, text=txt, bg=PANEL2, fg=col, font=(FONT_UI, 9, "bold"),
                          bd=0, relief="flat", cursor="hand2", command=cmd)
            b.pack(side="left", padx=(0, 6))
            b.bind("<Enter>", lambda e=None, x=b: x.config(bg=PANEL3))
            b.bind("<Leave>", lambda e=None, x=b: x.config(bg=PANEL2))

        # 双击结果 → 打开所在目录并选中
        def _open_loc(e):
            sel = tree.selection()
            if not sel:
                return
            vals = tree.item(sel[0], "values")
            full = os.path.join(vals[2], vals[1])
            try:
                subprocess.Popen(["explorer.exe", "/select,", full])
            except Exception:
                show_warning(self.root, "打开失败", "无法调起资源管理器")
        tree.bind("<Double-1>", _open_loc)

        def _on_close():
            state["stop"] = True   # 停止可能还在跑的后台扫描
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", _on_close)
        _load_existing()
        win._state = state
        win._tree = tree
        win._entry = ent
        win._do_search = _do_search
        win._build = _build_index
        win._load = _load_existing

    # ── 文件占用查询（谁锁了我的文件；Restart Manager 官方 API）──
    def _locks_dialog(self):
        top = tk.Toplevel(self.root)
        top.title("文件占用查询")
        top.configure(bg=BG)
        top.geometry("720x470")
        top.transient(self.root)
        enable_dark_title_bar(top)
        tk.Label(top, text="◈ 文件占用查询", bg=BG, fg=ORANGE,
                 font=(FONT_UI, 12, "bold")).pack(anchor="w", padx=16, pady=(12, 2))
        tk.Label(top, text="文件被另一个程序占用删不掉？粘路径查是谁锁的，必要时结束它"
                 "（系统进程请勿强行结束）",
                 bg=BG, fg=TEXT2, font=(FONT_UI, 8), wraplength=650,
                 justify="left").pack(anchor="w", padx=16)
        row = tk.Frame(top, bg=BG)
        row.pack(fill="x", padx=16, pady=(8, 4))
        # 操作按钮先占住底部：窗口高度不够时也不再被挤没（旧版按钮最后 pack，直接消失）
        btnf = tk.Frame(top, bg=BG)
        btnf.pack(side="bottom", fill="x", padx=16, pady=(2, 12))
        var = tk.StringVar()
        ent = tk.Entry(row, textvariable=var, bg=PANEL2, fg=TEXT, font=(FONT_MONO, 9),
                       relief="flat", insertbackground=ORANGE,
                       highlightthickness=1, highlightbackground=BORDER,
                       highlightcolor=ORANGE)
        ent.pack(side="left", fill="x", expand=True, ipady=3)
        status = tk.Label(top, text="粘入完整文件路径 → 查询", bg=BG, fg=TEXT2,
                          font=(FONT_MONO, 8), anchor="w")
        status.pack(fill="x", padx=16)
        q = queue.Queue()
        holder = tk.Frame(top, bg=BG)
        holder.pack(fill="both", expand=True, padx=16, pady=(4, 4))
        tree = ttk.Treeview(holder, columns=("类型", "状态"), show="tree headings",
                            height=11)
        vsh = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsh.set)
        tree.column("#0", width=300, anchor="w")
        tree.heading("#0", text="占用进程")
        tree.column("类型", width=120, anchor="w")
        tree.heading("类型", text="类型")
        tree.column("状态", width=140, anchor="w")
        tree.heading("状态", text="状态")
        vsh.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        tree.tag_configure("ok", foreground=GREEN)
        tree.tag_configure("warn", foreground=RED)
        iid_pid = {}

        def _fill(locks, err):
            tree.delete(*tree.get_children())
            iid_pid.clear()
            if err:
                tree.insert("", "end", text="  ❌ " + err, tags=("warn",))
                return
            if not locks:
                tree.insert("", "end", text="  ✅ 没有进程占用此文件，可以直接删除",
                            tags=("ok",))
                return
            for l in locks:
                iid = tree.insert("", "end", text=f"  {l['name']}（PID {l['pid']}）",
                                  values=(l["type"], l["status"]))
                iid_pid[iid] = l["pid"]

        def _query():
            path = var.get().strip().strip('"')
            if not os.path.isfile(path):
                show_warning("路径无效", "文件不存在：" + NL + (path or "（空）"), parent=top)
                return
            status.config(text="查询中…")
            def _do():
                q.put(find_file_locks(path))
            threading.Thread(target=_do, daemon=True).start()
            def _poll():
                try:
                    if not top.winfo_exists():
                        return   # 对话框已关闭（查询线程会自行结束）
                except Exception:
                    return
                try:
                    locks, err = q.get_nowait()
                except queue.Empty:
                    top.after(250, _poll)
                    return
                _fill(locks, err)
                n = len(locks)
                status.config(text=(f"查询完成：{n} 个占用进程" if n
                                    else "查询完成：无占用"))
            top.after(250, _poll)

        def _kill():
            sel = tree.selection()
            if not sel or sel[0] not in iid_pid:
                show_info("未选择", "请先选中占用进程", parent=top)
                return
            pid = iid_pid[sel[0]]
            name = tree.item(sel[0], "text").strip()
            if not ask_yesno("结束进程",
                    f"确定结束 [{name}]（PID {pid}）？" + NL +
                    "未保存的数据可能丢失。", danger=True):
                return
            try:
                proc = psutil.Process(pid)
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except psutil.TimeoutExpired:
                    proc.kill()
                show_info("已结束", "[{0}] 已结束，现在可以删除/移动文件了".format(name))
                _query()
            except psutil.NoSuchProcess:
                show_info("已结束", "进程已不存在")
            except Exception as e:
                show_error("结束失败", str(e))

        tk.Button(btnf, text="🔍 查询", bg=PANEL2, fg=ORANGE, font=(FONT_UI, 9, "bold"),
                  bd=0, relief="flat", cursor="hand2", command=_query).pack(side="left")
        tk.Button(btnf, text="📋 粘贴剪贴板路径", bg=PANEL2, fg=CYAN, font=(FONT_UI, 9),
                  bd=0, relief="flat", cursor="hand2",
                  command=lambda: var.set(self.root.clipboard_get().strip())).pack(
            side="left", padx=(8, 0))
        tk.Button(btnf, text="❌ 结束选中进程", bg=PANEL2, fg=RED, font=(FONT_UI, 9),
                  bd=0, relief="flat", cursor="hand2", command=_kill).pack(
            side="left", padx=(8, 0))
        ent.bind("<Return>", lambda e: _query())

    # ── 系统还原点（清理/卸载前的后悔药；官方 Checkpoint-Computer）──
    def _restore_dialog(self):
        top = tk.Toplevel(self.root)
        top.title("系统还原点")
        top.configure(bg=BG)
        top.geometry("680x480")
        top.transient(self.root)
        enable_dark_title_bar(top)
        tk.Label(top, text="◈ 系统还原点", bg=BG, fg=GREEN,
                 font=(FONT_UI, 12, "bold")).pack(anchor="w", padx=16, pady=(12, 2))
        tk.Label(top, text="大扫除/卸载前先建一个还原点：系统出问题可回滚设置与注册表（个人文件不受影响）。"
                           "列出/创建都需要管理员权限（UAC 确认）。",
                 bg=BG, fg=TEXT2, font=(FONT_UI, 8), justify="left",
                 wraplength=620).pack(anchor="w", padx=16)
        status = tk.Label(top, text="点击下方按钮操作", bg=BG, fg=TEXT2,
                          font=(FONT_MONO, 8))
        status.pack(anchor="w", padx=16, pady=(4, 2))
        # 操作按钮先占住底部：窗口高度不够时也不再被挤没
        btnf = tk.Frame(top, bg=BG)
        btnf.pack(side="bottom", fill="x", padx=16, pady=(2, 12))
        tree = ttk.Treeview(top, height=13, show="tree", selectmode="browse")
        tree.pack(fill="both", expand=True, padx=16, pady=(4, 4))
        # 两个操作各用各的队列：共用一个队列时，UAC 期间连点两个按钮会让
        # _poll 把「创建」的 (ok, msg) 当成「列出」的 (pts, total)，于是
        # `for p in pts` 拿 bool 迭代直接 TypeError，整条轮询链断掉。
        busy = {"v": False}

        def _list_points():
            if busy["v"]:
                return          # 上一次 UAC 还没结束，避免结果互相插队
            busy["v"] = True
            status.config(text="正在列出还原点…（会弹 UAC 确认）")
            q = queue.Queue()
            threading.Thread(target=lambda: q.put(list_restore_points()),
                             daemon=True).start()
            def _poll():
                try:
                    if not top.winfo_exists():
                        return   # 对话框已关闭
                except Exception:
                    return
                try:
                    pts, total = q.get_nowait()
                except queue.Empty:
                    top.after(300, _poll)
                    return
                busy["v"] = False
                tree.delete(*tree.get_children())
                if pts is None:
                    status.config(text=f"列出失败：{total}")
                    return
                if not pts:
                    tree.insert("", "end", text="  （当前没有任何还原点）")
                for p in pts:
                    tree.insert("", "end", text="  🛡 " + p)
                status.config(text=f"最近 {len(pts)} 条（系统共 {total} 个还原点）")
            top.after(300, _poll)

        def _create():
            if busy["v"]:
                return
            if not ask_yesno("创建还原点",
                    "将创建一个系统还原点（描述：UnifiedToolbox）？\n"
                    "会弹出 UAC 管理员确认；通常 10~40 秒完成。", danger=True):
                return
            busy["v"] = True
            status.config(text="正在创建还原点…（10~40 秒，请勿关闭）")
            q = queue.Queue()
            threading.Thread(target=lambda: q.put(create_restore_point("UnifiedToolbox")),
                             daemon=True).start()
            def _poll2():
                try:
                    if not top.winfo_exists():
                        return   # 对话框已关闭
                except Exception:
                    return
                try:
                    ok, msg = q.get_nowait()
                except queue.Empty:
                    top.after(300, _poll2)
                    return
                busy["v"] = False
                (show_info if ok else show_warning)("系统还原点", msg, parent=top)
                _list_points()
            top.after(300, _poll2)
        tk.Button(btnf, text="🛡 创建还原点", bg=PANEL2, fg=GREEN, font=(FONT_UI, 9, "bold"),
                  bd=0, relief="flat", cursor="hand2", command=_create).pack(side="left")
        tk.Button(btnf, text="🔄 列出还原点", bg=PANEL2, fg=CYAN, font=(FONT_UI, 9),
                  bd=0, relief="flat", cursor="hand2", command=_list_points).pack(side="left", padx=(8, 0))

    def start(self):
        self._junk.start(); self._files.start()
    def stop(self):
        self._junk.stop(); self._files.stop()
    def on_show(self): pass


class SoftwareModule(BaseModule):
    """软件管家 = ① 已安装软件（卸载/残留/UWP）+ ② 预装体检 + ③ winget 一键装机"""
    name = "software"; label = "软件管家"; icon = "📦"; color = ORANGE

    def __init__(self, app):
        super().__init__(app)
        self._uninstall = UninstallModule(app)
        self._installing = False
        self._wg_version = ""
        self._view_token = object()
        self._view_active = False

    def build(self):
        self._view_token = object()
        self._view_active = True
        page_header(self.body, "◈ 软件管家",
                    "已安装 / 卸载 / 残留扫描 / UWP → 预装体检 → winget 装机", ORANGE)
        uni_body = tk.Frame(self.body, bg=BG)
        uni_body.pack(fill="x")
        self._uninstall.body = uni_body
        self._uninstall.build()

        # ── ② 预装体检 ──
        bl = tk.Frame(self.body, bg=PANEL)
        bl.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(bl, text="② 预装软件体检（识别推广/试用类预装）", bg=PANEL, fg=CYAN,
                 font=(FONT_UI, 10, "bold")).pack(anchor="w", padx=12, pady=(8, 2))
        brow = tk.Frame(bl, bg=PANEL)
        brow.pack(fill="x", padx=12)
        self._bloat_scan_btn = tk.Button(brow, text="🔍 扫描预装", bg=PANEL2, fg=CYAN,
                                         font=(FONT_UI, 9), bd=0, relief="flat",
                                         cursor="hand2", command=self._scan_bloat)
        self._bloat_scan_btn.pack(side="left", pady=(2, 4))
        self._bloat_box = tk.Frame(bl, bg=PANEL)
        self._bloat_box.pack(fill="x", padx=12, pady=(0, 10))
        tk.Label(self._bloat_box, text="点击扫描后列出检测结果", bg=PANEL, fg=MUTED,
                 font=(FONT_UI, 8)).pack(anchor="w")

        # ── ③ winget 一键装机 ──
        wg = tk.Frame(self.body, bg=PANEL)
        wg.pack(fill="x", padx=20, pady=(0, 14))
        tk.Label(wg, text="③ winget 一键装机（微软官方源）", bg=PANEL, fg=CYAN,
                 font=(FONT_UI, 10, "bold")).pack(anchor="w", padx=12, pady=(8, 2))
        self._winget_lbl = tk.Label(wg, text="检测 winget 中…", bg=PANEL, fg=TEXT2,
                                    font=(FONT_UI, 8))
        self._winget_lbl.pack(anchor="w", padx=12)
        self._wg_vars = {}
        grid = tk.Frame(wg, bg=PANEL)
        grid.pack(fill="x", padx=12, pady=(2, 2))
        for i, (name, wid) in enumerate(WINGET_APPS):
            r, c = divmod(i, 5)
            var = tk.BooleanVar(value=False)
            cb = tk.Checkbutton(grid, text=name, variable=var, bg=PANEL, fg=TEXT,
                                selectcolor=PANEL3, activebackground=PANEL,
                                font=(FONT_UI, 9), bd=0, highlightthickness=0,
                                cursor="hand2")
            cb.grid(row=r, column=c, padx=(0, 10), pady=1, sticky="w")
            grid.grid_columnconfigure(list(range(5)), weight=1)
            self._wg_vars[wid] = var
        crow = tk.Frame(wg, bg=PANEL)
        crow.pack(fill="x", padx=12, pady=(0, 8))
        self._wg_go = tk.Button(crow, text="📦 安装勾选项", bg=PANEL2, fg=GREEN,
                                font=(FONT_UI, 9, "bold"), bd=0, relief="flat",
                                cursor="hand2", command=self._install_checked, state="disabled")
        self._wg_go.pack(side="left")
        tk.Label(crow, text="安装过程输出在下方日志（首次使用 winget 需联网）",
                 bg=PANEL, fg=MUTED, font=(FONT_UI, 8)).pack(side="left", padx=10)
        self._wg_log = tk.Text(wg, bg=PANEL2, fg=TEXT2, font=(FONT_MONO, 8), height=7,
                               relief="flat", bd=0, state="disabled",
                               insertbackground=GREEN)
        self._wg_log.pack(fill="x", padx=12, pady=(0, 10))
        self._render_winget(self._wg_version)

    def start(self):
        self._uninstall.start()
        self._check_winget_async()
    def stop(self):
        self._view_active = False
        self._view_token = object()
        self._uninstall.stop()
    def on_show(self): pass

    # ── 预装体检 ──
    def _scan_bloat(self):
        token = self._view_token
        self._bloat_scan_btn.config(state="disabled", text="⏳ 扫描中…")
        for w in self._bloat_box.winfo_children():
            w.destroy()
        tk.Label(self._bloat_box, text="扫描注册表安装列表中…", bg=PANEL, fg=TEXT2,
                 font=(FONT_UI, 8)).pack(anchor="w")
        q = queue.Queue()
        def _do():
            try:
                apps = self._uninstall._all_apps or []
                if not apps:
                    apps = self._uninstall._scan_reg()
                q.put(("ok", match_oem_bloat(apps)))
            except Exception as e:
                q.put(("err", str(e)))
        threading.Thread(target=_do, daemon=True).start()

        def _poll():
            if not self._view_live(token):
                return
            try:
                typ, data = q.get_nowait()
            except queue.Empty:
                self.root.after(300, _poll)
                return
            if typ == "err":
                self._bloat_scan_btn.config(state="normal", text="扫描预装")
                for w in self._bloat_box.winfo_children():
                    w.destroy()
                tk.Label(self._bloat_box, text=f"扫描失败：{data}", bg=PANEL, fg=RED,
                         font=(FONT_UI, 8)).pack(anchor="w")
                return
            self._render_bloat(data)
        self.root.after(300, _poll)

    def _render_bloat(self, found):
        self._bloat_scan_btn.config(state="normal", text="🔍 扫描预装")
        for w in self._bloat_box.winfo_children():
            w.destroy()
        if not found:
            tk.Label(self._bloat_box, text="✅ 未发现推广/试用类预装，很干净 👍",
                     bg=PANEL, fg=GREEN, font=(FONT_UI, 9)).pack(anchor="w")
            return
        for app, why in found:
            row = tk.Frame(self._bloat_box, bg=PANEL2)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=f"⚠ {app['name']}（{why}）", bg=PANEL2, fg=YELLOW,
                     font=(FONT_UI, 9), anchor="w").pack(side="left", padx=8, pady=4)
            btn = tk.Button(row, text="卸载", bg=PANEL3, fg=RED, font=(FONT_UI, 8),
                            bd=0, relief="flat", cursor="hand2",
                            command=lambda a=app: self._uninstall_one(a))
            btn.pack(side="right", padx=6, pady=3)
        tk.Label(self._bloat_box, text="卸载会启动软件自带卸载向导，跟随提示完成即可",
                 bg=PANEL, fg=MUTED, font=(FONT_UI, 8)).pack(anchor="w", pady=(4, 0))

    def _uninstall_one(self, app):
        if not app.get("uninstall"):
            show_warning("无法卸载", f"[{app['name']}] 没有卸载程序")
            return
        if not ask_yesno("确认卸载",
                f"确认卸载预装软件 [{app['name']}]？\n将启动其官方卸载向导。", danger=True):
            return
        try:
            cmd = _safe_uninstall_cmd(app["uninstall"])
            si = subprocess.STARTUPINFO()
            si.dwFlags = subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            subprocess.Popen(cmd, startupinfo=si)
        except Exception as e:
            show_error("卸载失败", str(e))

    # ── winget 装机 ──
    def _check_winget_async(self):
        token = self._view_token
        task = self._winget_check = object()
        q = queue.Queue()
        def work():
            try:
                q.put(check_winget())
            except Exception:
                q.put('')
        def poll():
            if not self._view_live(token) or self._winget_check is not task:
                return
            try:
                version = q.get_nowait()
            except queue.Empty:
                self.root.after(300, poll)
                return
            self._render_winget(version)
        threading.Thread(target=work, daemon=True).start()
        self.root.after(300, poll)

    def _render_winget(self, v):
        self._wg_version = v
        if v:
            self._winget_lbl.config(text=f"winget 就绪（{v}）", fg=GREEN)
            self._wg_go.config(state="disabled" if self._installing else "normal",
                               text="⏳ 安装中…" if self._installing else "📦 安装勾选项")
        else:
            self._wg_go.config(state="disabled")
            self._winget_lbl.config(
                text="未检测到 winget —— 请从 Microsoft Store 安装「应用安装程序」后刷新",
                fg=YELLOW)

    def _wg_log_append(self, line):
        try:
            self._wg_log.config(state="normal")
            self._wg_log.insert("end", line + "\n")
            self._wg_log.see("end")
            self._wg_log.config(state="disabled")
        except Exception:
            pass

    def _install_checked(self):
        if self._installing:
            show_info("安装中", "当前已有安装任务在进行")
            return
        ids = [wid for wid, var in self._wg_vars.items() if var.get()]
        if not ids:
            show_info("未选择", "请先勾选要安装的软件")
            return
        if not ask_yesno("确认安装",
                f"通过微软 winget 官方源安装 {len(ids)} 个软件？\n" +
                "\n".join(f"  · {wid}" for wid in ids[:8]) +
                ("\n…" if len(ids) > 8 else "")):
            return
        token = self._view_token
        self._installing = True
        self._wg_go.config(state="disabled", text="⏳ 安装中…")
        q = queue.Queue()
        def _do():
            for wid in ids:
                q.put(("log", f"—— 安装 {wid} ——"))
                try:
                    si = subprocess.STARTUPINFO()
                    si.dwFlags = subprocess.STARTF_USESHOWWINDOW
                    si.wShowWindow = 0
                    r = subprocess.run(
                        ["winget", "install", "--id", wid, "-e", "--silent",
                         "--accept-package-agreements", "--accept-source-agreements"],
                        capture_output=True, text=True, timeout=900,
                        startupinfo=si, encoding="gbk", errors="ignore")
                    tail = [l for l in (r.stdout or "").splitlines() if l.strip()][-3:]
                    for l in tail:
                        q.put(("log", "  " + l.strip()))
                    q.put(("log", f"  {'✅ 完成' if r.returncode == 0 else '❌ 失败（码 %d）' % r.returncode}"))
                except Exception as e:
                    q.put(("log", f"  ❌ 异常：{e}"))
            q.put(("done", None))
        def _poll():
            if getattr(self.app, "_closing", False):
                return
            live = self._view_live(token)
            try:
                while True:
                    typ, data = q.get_nowait()
                    if typ == "log":
                        if live:
                            self._wg_log_append(data)
                    else:
                        self._installing = False
                        if self._view_live(self._view_token):
                            self._render_winget(self._wg_version)
                        if live:
                            self._wg_log_append("—— 全部任务结束 ——")
                        return
            except queue.Empty:
                pass
            self.root.after(400, _poll)
        self._wg_log_append(f"开始安装 {len(ids)} 项（官方源，静默模式）…")
        threading.Thread(target=_do, daemon=True).start()
        self.root.after(400, _poll)

    def _view_live(self, token):
        if getattr(self.app, '_closing', False):
            return False
        try:
            return (self._view_active and self._view_token is token
                    and bool(self.body.winfo_exists()))
        except Exception:
            return False



class UtilityModule(BaseModule):
    """实用工具 = ① 电源控制（定时/立即 关机·重启·休眠） + ② 屏幕取色器"""
    name = "utility"; label = "实用工具"; icon = "🎛"; color = CYAN

    def __init__(self, app):
        super().__init__(app)
        self._pick_history = []      # 本次会话的取色记录（HEX 字符串）
        self._power_target = 0.0     # 定时关机目标时间戳（倒计时用）
        self._power_label = ""
        self._power_tick = None
        self._float_win = None       # 系统悬浮窗（None = 未开）

    def build(self):
        page_header(self.body, "◈ 实用工具",
                    "电源定时 · 屏幕取色 · 悬浮监控 —— 常用小工具集中放置，无需另装软件", CYAN)
        row = tk.Frame(self.body, bg=BG)
        row.pack(fill="x", padx=20, pady=(0, 6))
        self._build_power(row)
        self._build_picker(row)
        row2 = tk.Frame(self.body, bg=BG)
        row2.pack(fill="x", padx=20, pady=(0, 14))
        self._build_float(row2)

    # ═══ ① 电源控制 ═══
    def _build_power(self, parent):
        card = tk.Frame(parent, bg=PANEL)
        card.pack(side="left", fill="both", expand=True, padx=(0, 8))
        tk.Label(card, text="🔌 电源控制", bg=PANEL, fg=CYAN,
                 font=(FONT_UI, 11, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
        tk.Label(card, text="定时交给 Windows 计时器，关闭工具箱也会照常执行",
                 bg=PANEL, fg=MUTED, font=(FONT_UI, 8)).pack(anchor="w", padx=14)

        form = tk.Frame(card, bg=PANEL)
        form.pack(fill="x", padx=14, pady=(10, 2))
        tk.Label(form, text="时长", bg=PANEL, fg=TEXT2,
                 font=(FONT_UI, 9)).pack(side="left")
        self._mins_var = tk.StringVar(value="30")
        ent = tk.Entry(form, textvariable=self._mins_var, width=5, bg=PANEL2, fg=TEXT,
                       font=(FONT_MONO, 10), relief="flat", justify="center",
                       insertbackground=CYAN, highlightthickness=1,
                       highlightbackground=BORDER, highlightcolor=CYAN)
        ent.pack(side="left", padx=6, ipady=3)
        tk.Label(form, text="分钟后", bg=PANEL, fg=TEXT2,
                 font=(FONT_UI, 9)).pack(side="left")
        self._power_action = tk.StringVar(value="shutdown")
        for val, txt in (("shutdown", "关机"), ("restart", "重启")):
            tk.Radiobutton(form, text=txt, variable=self._power_action, value=val,
                           bg=PANEL, fg=TEXT2, selectcolor=PANEL3,
                           activebackground=PANEL, activeforeground=CYAN,
                           font=(FONT_UI, 9), bd=0, highlightthickness=0,
                           cursor="hand2").pack(side="left", padx=(10, 0))

        btns = tk.Frame(card, bg=PANEL)
        btns.pack(fill="x", padx=14, pady=(8, 2))
        self._mkbtn(btns, "⏱ 定时执行", self._power_schedule, CYAN)
        self._mkbtn(btns, "✖ 取消定时", self._power_cancel, ORANGE)
        self._power_status = tk.Label(card, text="未设定定时任务", bg=PANEL, fg=TEXT2,
                                      font=(FONT_MONO, 8), anchor="w")
        self._power_status.pack(fill="x", padx=14, pady=(2, 8))

        tk.Frame(card, bg=BORDER, height=1).pack(fill="x", padx=14, pady=(2, 8))
        tk.Label(card, text="立即执行", bg=PANEL, fg=TEXT2,
                 font=(FONT_UI, 9)).pack(anchor="w", padx=14)
        now = tk.Frame(card, bg=PANEL)
        now.pack(fill="x", padx=14, pady=(6, 12))
        self._mkbtn(now, "🌙 休眠", lambda: self._power_now("hibernate"), PURPLE)
        self._mkbtn(now, "⏻ 关机", lambda: self._power_now("shutdown"), RED)
        self._mkbtn(now, "↻ 重启", lambda: self._power_now("restart"), YELLOW)

    def _power_schedule(self):
        try:
            mins = float(self._mins_var.get())
        except ValueError:
            show_warning("时间无效", "请填写分钟数（可含小数，如 1.5）")
            return
        secs = int(mins * 60)
        action = self._power_action.get()
        label = _POWER_ACTIONS.get(action, ("", "操作"))[1]
        if not ask_yesno("确认定时",
                f"{mins:g} 分钟后{label}？\n\n倒计时期间可随时点「取消定时」。",
                danger=True):
            return
        ok, msg = schedule_power_action(action, secs)
        if not ok:
            show_warning("设定失败", msg)
            return
        self._power_target = time.time() + secs
        self._power_label = label
        self._power_tick_status()
        self._power_countdown()

    def _power_countdown(self):
        if self._power_tick:
            try: self.root.after_cancel(self._power_tick)
            except Exception: pass
        if not self._power_target:
            self._power_tick = None
            return
        left = int(self._power_target - time.time())
        if left <= 0:
            self._power_target = 0
            self._power_status.config(text=f"已到时间，正在{self._power_label}…", fg=ORANGE)
            self._power_tick = None
            return
        h, m, s = left // 3600, (left % 3600) // 60, left % 60
        self._power_status.config(
            text=f"◐ {h:02d}:{m:02d}:{s:02d} 后{self._power_label}（可取消）", fg=CYAN)
        self._power_tick = self.root.after(1000, self._power_countdown)

    def _power_tick_status(self):
        self._power_status.config(text="定时已设定，倒计时启动…", fg=CYAN)

    def _power_cancel(self):
        ok, msg = cancel_power_action()
        if not ok:
            self._power_status.config(text=msg, fg=TEXT2)
            return
        self._power_target = 0
        if self._power_tick:
            try: self.root.after_cancel(self._power_tick)
            except Exception: pass
            self._power_tick = None
        self._power_status.config(text="已取消定时任务", fg=GREEN)

    def _power_now(self, action):
        names = {"hibernate": "休眠", "shutdown": "关机", "restart": "重启"}
        if action != "hibernate":
            if not ask_yesno(f"确认{names[action]}",
                             f"将在 10 秒后{names[action]}，期间可用「✖ 取消定时」中断。\n\n继续？",
                             danger=True):
                return
        ok, msg = power_action_now(action)
        if not ok:
            show_warning("操作失败", msg)
        else:
            self._power_status.config(text=msg, fg=ORANGE)

    # ═══ ② 屏幕取色器 ═══
    def _build_picker(self, parent):
        card = tk.Frame(parent, bg=PANEL)
        card.pack(side="left", fill="both", expand=True, padx=(8, 0))
        tk.Label(card, text="🎨 屏幕取色器", bg=PANEL, fg=PURPLE,
                 font=(FONT_UI, 11, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
        tk.Label(card, text="点击「开始取色」后移动鼠标，左键拾取 · 右键或 Esc 退出",
                 bg=PANEL, fg=MUTED, font=(FONT_UI, 8)).pack(anchor="w", padx=14)
        bar = tk.Frame(card, bg=PANEL)
        bar.pack(fill="x", padx=14, pady=(10, 6))
        self._mkbtn(bar, "🎯 开始取色", self._start_picker, PURPLE)
        self._mkbtn(bar, "🗑 清除记录", self._clear_pick_history, TEXT2)
        self._pick_status = tk.Label(card, text="尚未取色", bg=PANEL, fg=TEXT2,
                                     font=(FONT_MONO, 8), anchor="w")
        self._pick_status.pack(fill="x", padx=14)
        tk.Label(card, text="取色记录（点击复制）", bg=PANEL, fg=TEXT2,
                 font=(FONT_UI, 9)).pack(anchor="w", padx=14, pady=(10, 2))
        self._pick_canvas = tk.Canvas(card, bg=PANEL2, height=86,
                                      highlightthickness=0)
        self._pick_canvas.pack(fill="x", padx=14, pady=(0, 12))
        self._render_pick_history()

    def _render_pick_history(self):
        c = self._pick_canvas
        c.delete("all")
        if not self._pick_history:
            c.create_text(12, 43, text=" 拾取的颜色会显示在这里", fill=MUTED,
                          font=(FONT_UI, 9), anchor="w")
            return
        W = c.winfo_width() or 420
        cell = max(54, min(88, (W - 16) // max(1, len(self._pick_history))))
        for i, hexv in enumerate(self._pick_history[:8]):
            x0 = 8 + i * (cell + 4)
            c.create_rectangle(x0, 8, x0 + cell, 44, fill=hexv, outline=BORDER)
            c.create_text(x0 + cell / 2, 56, text=hexv, fill=TEXT2,
                          font=(FONT_MONO, 7))
            c.tag_bind(c.create_rectangle(x0, 62, x0 + cell, 78, fill=PANEL3,
                                          outline=""),
                       "<Button-1>", lambda e, h=hexv: self._copy_hex(h))
        c.tag_bind("all", "<Enter>", lambda e=None: c.config(cursor="hand2"))

    def _copy_hex(self, hexv):
        self.root.clipboard_clear()
        self.root.clipboard_append(hexv)
        self._pick_status.config(text=f"已复制 {hexv} 到剪贴板", fg=GREEN)

    def _clear_pick_history(self):
        self._pick_history.clear()
        self._render_pick_history()
        self._pick_status.config(text="取色记录已清空", fg=TEXT2)

    def _remember_color(self, hexv):
        if hexv in self._pick_history:
            self._pick_history.remove(hexv)
        self._pick_history.insert(0, hexv)
        del self._pick_history[8:]
        self._render_pick_history()

    def _start_picker(self):
        """全屏取色：近乎透明的遮罩接收鼠标事件，独立放大镜窗口保证色彩真实
        （遮罩若带可见不透明度，会把采样到的颜色一起压暗）。"""
        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True)
        sw, sh = ov.winfo_screenwidth(), ov.winfo_screenheight()
        ov.geometry(f"{sw}x{sh}+0+0")
        ov.attributes("-topmost", True)
        ov.attributes("-alpha", 0.02)
        cv = tk.Canvas(ov, bg="#808080", highlightthickness=0, cursor="crosshair")
        cv.pack(fill="both", expand=True)

        mag = tk.Toplevel(ov)
        mag.overrideredirect(True)
        mag.attributes("-topmost", True)
        mcv = tk.Canvas(mag, width=132, height=132, bg=PANEL,
                        highlightthickness=1, highlightbackground=CYAN)
        mcv.pack()
        info = tk.Toplevel(ov)
        info.overrideredirect(True)
        info.attributes("-topmost", True)
        icv = tk.Canvas(info, width=132, height=46, bg=PANEL,
                        highlightthickness=1, highlightbackground=BORDER)
        icv.pack()

        state = {"img": None, "last": 0.0}

        def _close(e=None):
            for w in (info, mag, ov):
                try: w.destroy()
                except Exception: pass
            return "break"

        def _pos(x, y):
            mx = min(max(0, x + 20), sw - 150)
            my = min(max(0, y + 20), sh - 190)
            mag.geometry(f"+{mx}+{my}")
            info.geometry(f"+{mx}+{my + 138}")

        def _update(x, y):
            now = time.time()
            if state["img"] is not None and now - state["last"] < 0.04:
                return
            state["last"] = now
            rgb = grab_pixel_rgb(x, y)
            if not rgb:
                return
            hexv = "#%02X%02X%02X" % rgb
            zoom = grab_region_zoom(x, y, half=7, zoom=9)
            if zoom is not None:
                state["img"] = _PILImageTk.PhotoImage(zoom)
                mcv.delete("all")
                mcv.create_image(0, 0, image=state["img"], anchor="nw")
                cx = cy = 132 // 2
                mcv.create_line(cx - 16, cy, cx + 16, cy, fill="#ffffff")
                mcv.create_line(cx, cy - 16, cx, cy + 16, fill="#ffffff")
                mcv.create_rectangle(cx - 6, cy - 6, cx + 6, cy + 6,
                                     outline="#000000")
            icv.delete("all")
            icv.create_rectangle(8, 10, 42, 36, fill=hexv, outline=BORDER)
            icv.create_text(50, 16, text=hexv, fill=TEXT, anchor="w",
                            font=(FONT_MONO, 9, "bold"))
            icv.create_text(50, 32, text=f"RGB {rgb[0]}, {rgb[1]}, {rgb[2]}",
                            fill=TEXT2, anchor="w", font=(FONT_MONO, 8))

        def _motion(e):
            _pos(e.x_root, e.y_root)
            _update(e.x_root, e.y_root)

        def _click(e):
            rgb = grab_pixel_rgb(e.x_root, e.y_root)
            if rgb:
                hexv = "#%02X%02X%02X" % rgb
                self.root.clipboard_clear()
                self.root.clipboard_append(hexv)
                self._remember_color(hexv)
                self._pick_status.config(
                    text=f"已拾取 {hexv}（RGB {rgb[0]}, {rgb[1]}, {rgb[2]}）并复制到剪贴板",
                    fg=GREEN)
            _close()

        cv.bind("<Motion>", _motion)
        cv.bind("<Button-1>", _click)
        cv.bind("<Button-3>", _close)
        ov.bind("<Escape>", _close)
        ov.focus_force()
        self._pick_status.config(text="取色中：移动鼠标预览，左键拾取，右键/Esc 取消", fg=PURPLE)
        _pos(sw // 2, sh // 2)
        _update(sw // 2, sh // 2)

    # ═══ ③ 系统悬浮窗（v3.7 C 波）：无边框置顶小窗实时 CPU/内存/网速 ═══
    def _build_float(self, parent):
        card = tk.Frame(parent, bg=PANEL)
        card.pack(fill="x", padx=0, pady=0)
        tk.Label(card, text="🖥 系统悬浮窗", bg=PANEL, fg=GREEN,
                 font=(FONT_UI, 11, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
        tk.Label(card, text="无边框置顶小窗：实时 CPU · 内存 · 网速，可拖到任意角落，位置自动记忆",
                 bg=PANEL, fg=MUTED, font=(FONT_UI, 8)).pack(anchor="w", padx=14)
        bar = tk.Frame(card, bg=PANEL)
        bar.pack(fill="x", padx=14, pady=(10, 12))
        self._float_btn = self._mkbtn(bar, "🪟 开启悬浮窗", self._toggle_float, GREEN)
        self._float_hint = tk.Label(card, text="悬浮窗独立于主窗口，关闭后可再点按钮重开（位置已记忆）",
                                    bg=PANEL, fg=TEXT2, font=(FONT_UI, 8), anchor="w")
        self._float_hint.pack(fill="x", padx=14, pady=(0, 10))

    def _toggle_float(self):
        if self._float_win is not None:
            self._close_float()
        else:
            self._open_float()

    def _close_float(self):
        if self._float_win is not None:
            try:
                self._float_win.destroy()
            except Exception:
                pass
            self._float_win = None
        if getattr(self, "_float_btn", None) is not None:
            self._float_btn.config(text="🪟 开启悬浮窗")
            self._float_hint.config(text="悬浮窗已关闭（上次位置已记住）", fg=TEXT2)

    def _open_float(self):
        """无边框置顶小窗：psutil 采样在主线程（Tk 非线程安全，psutil 非阻塞 <1ms）"""
        if self._float_win is not None:
            return
        fl = tk.Toplevel(self.root)
        fl.overrideredirect(True)              # 无标题栏
        fl.attributes("-topmost", True)        # 永远置顶
        fl.configure(bg=PANEL, cursor="fleur")
        # 位置记忆：上次拖到哪儿，这次还从那儿出现
        geo = SETTINGS.get("float_geo", "")
        if geo and re.match(r"^\+\d+\+\d+$", geo):
            fl.geometry(geo)
        else:
            fl.geometry(f"+{fl.winfo_screenwidth() - 250}+80")
        inner = tk.Frame(fl, bg=PANEL, highlightthickness=1,
                         highlightbackground=BORDER)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        cv = tk.Canvas(inner, bg=PANEL, highlightthickness=0, width=210, height=64)
        cv.pack(fill="both", expand=True)

        # 拖动（整窗按下即拖）
        drag = {"on": False, "dx": 0, "dy": 0}

        def _press(e):
            drag.update(on=True, dx=e.x_root - fl.winfo_x(), dy=e.y_root - fl.winfo_y())

        def _drag(e):
            if drag["on"]:
                fl.geometry(f"+{e.x_root - drag['dx']}+{e.y_root - drag['dy']}")

        def _release(e=None):
            if drag["on"]:
                drag["on"] = False
                # 松手即记忆位置
                SETTINGS["float_geo"] = f"+{fl.winfo_x()}+{fl.winfo_y()}"
                save_settings()

        for w in (cv, inner):
            w.bind("<Button-1>", _press)
            w.bind("<B1-Motion>", _drag)
            w.bind("<ButtonRelease-1>", _release)
        # 双击窗口任意处关闭
        cv.bind("<Double-Button-1>", lambda e: self._close_float())
        # 右上角 ✕ 热区
        cid = cv.create_text(198, 10, text="✕", fill=MUTED,
                             font=(FONT_UI, 8), tags=("close",))
        cv.tag_bind("close", "<Button-1>", lambda e: self._close_float())
        cv.tag_bind("close", "<Enter>", lambda e: cv.itemconfig(cid, fill=RED))
        cv.tag_bind("close", "<Leave>", lambda e: cv.itemconfig(cid, fill=MUTED))

        state = {"last_net": None, "last_t": time.time(), "hist": []}
        _state_keep = state  # 防 GC

        def _fmt_speed(bps):
            if bps >= 1024 * 1024: return f"{bps/1024/1024:.1f}MB/s"
            if bps >= 1024: return f"{bps/1024:.0f}KB/s"
            return f"{bps:.0f}B/s"

        def _sample():
            """主线程 1 秒采样渲染一次"""
            try:
                cpu = psutil.cpu_percent(interval=0)
                mem = psutil.virtual_memory().percent
                n = psutil.net_io_counters()
                now = time.time()
                dn = up = 0
                if state["last_net"] is not None:
                    dt = max(0.25, now - state["last_t"])
                    dn = max(0, n.bytes_recv - state["last_net"].bytes_recv) / dt
                    up = max(0, n.bytes_sent - state["last_net"].bytes_sent) / dt
                state["last_net"], state["last_t"] = n, now
                state["hist"].append(cpu)
                del state["hist"][:-40]
                # 渲染（✕ 每次重绘）
                cv.delete("all")
                cid = cv.create_text(198, 10, text="✕", fill=MUTED,
                                     font=(FONT_UI, 8), tags=("close",))
                cv.tag_bind("close", "<Button-1>", lambda e: self._close_float())
                cv.tag_bind("close", "<Enter>", lambda e: cv.itemconfig(cid, fill=RED))
                cv.tag_bind("close", "<Leave>", lambda e: cv.itemconfig(cid, fill=MUTED))
                # 三行信息
                cpu_col = RED if cpu >= 90 else (ORANGE if cpu >= 60 else GREEN)
                cv.create_text(10, 8, text=f"CPU {cpu:5.1f}%", fill=cpu_col,
                               anchor="nw", font=(FONT_MONO, 9, "bold"))
                mem_col = RED if mem >= 90 else (ORANGE if mem >= 80 else CYAN)
                cv.create_text(10, 26, text=f"内存 {mem:5.1f}%", fill=mem_col,
                               anchor="nw", font=(FONT_MONO, 9, "bold"))
                cv.create_text(10, 44, text=f"↓{_fmt_speed(dn)}  ↑{_fmt_speed(up)}",
                               fill=TEXT2, anchor="nw", font=(FONT_MONO, 8))
                # 右侧迷你 CPU 柱状史（40px 宽条带）
                base_x, base_y = 132, 36
                for i, v in enumerate(state["hist"][-26:]):
                    hgt = max(2, int(v / 100 * 28))
                    col = RED if v >= 90 else (ORANGE if v >= 60 else GREEN)
                    cv.create_rectangle(base_x + i * 3, base_y - hgt,
                                        base_x + i * 3 + 2, base_y,
                                        fill=col, outline="")
            except Exception:
                pass
            if self._float_win is fl and fl.winfo_exists():
                fl.after(1000, _sample)

        self._float_win = fl
        fl.protocol("WM_DELETE_WINDOW", self._close_float)
        self._float_btn.config(text="🪟 关闭悬浮窗")
        self._float_hint.config(text="悬浮窗已开启：拖动移位 · 双击或点 ✕ 关闭", fg=GREEN)
        _sample()

    def start(self): pass
    def stop(self):
        if self._power_tick:
            try: self.root.after_cancel(self._power_tick)
            except Exception: pass
            self._power_tick = None
    def on_show(self): pass


class VerifyModule(BaseModule):
    """新机验机 = ① 激活状态 + ② 正版激活辅助 + ③ 硬件验机工具 + ④ 隐私快设 + ⑤ 交付报告"""
    name = "verify"; label = "新机验机"; icon = "🧾"; color = GREEN

    def __init__(self, app):
        super().__init__(app)
        self._activation = ActivationModule(app)
        self._setup = SetupModule(app)
        # 硬件验机结果（None=未执行），供交付报告与状态条使用
        self._hw_results = {"driver": None, "pixel": None, "keyboard": None}

    def build(self):
        page_header(self.body, "◈ 新机验机",
                    "授权状态 → 硬件验机 → 隐私快设 → 交付报告 · 一条龙验机", GREEN)
        act_body = tk.Frame(self.body, bg=BG)
        act_body.pack(fill="x")
        self._activation.body = act_body
        self._activation.build()
        self._build_hw_tools()
        setup_body = tk.Frame(self.body, bg=BG)
        setup_body.pack(fill="x")
        self._setup.body = setup_body
        self._setup.build()

    # ── ③ 硬件验机工具（坏点 / 键鼠 / 驱动）──
    def _build_hw_tools(self):
        hw = tk.Frame(self.body, bg=PANEL)
        hw.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(hw, text="③ 硬件验机工具（屏幕 / 键鼠 / 驱动）", bg=PANEL, fg=CYAN,
                 font=(FONT_UI, 10, "bold")).pack(anchor="w", padx=12, pady=(8, 2))
        row = tk.Frame(hw, bg=PANEL)
        row.pack(fill="x", padx=12, pady=(2, 10))
        for txt, cmd, clr in (("🖥 屏幕坏点测试", self._pixel_test, CYAN),
                              ("⌨ 键盘·鼠标测试", self._keyboard_test, GREEN),
                              ("🔌 驱动异常检查", self._driver_dialog, YELLOW)):
            b = tk.Button(row, text=txt, bg=PANEL2, fg=clr, font=(FONT_UI, 9, "bold"),
                          bd=0, relief="flat", cursor="hand2", command=cmd)
            b.pack(side="left", padx=(0, 6))
            b.bind("<Enter>", lambda e=None, bb=b: bb.config(bg=PANEL3))
            b.bind("<Leave>", lambda e=None, bb=b: bb.config(bg=PANEL2))
        tk.Label(hw, text="全屏工具按 Esc 退出 · 结果自动并入交付报告",
                 bg=PANEL, fg=MUTED, font=(FONT_UI, 8)).pack(side="left", padx=10)
        self._hw_state_lbl = tk.Label(hw, text=self._hw_status_text(), bg=PANEL, fg=CYAN,
                                      font=(FONT_MONO, 8))
        self._hw_state_lbl.pack(side="right", padx=12)

    def _hw_status_text(self):
        r = self._hw_results
        drv = ("驱动:已查 0 异常" if r["driver"] == [] else
               (f"驱动:{len(r['driver'])} 异常" if r["driver"] else "驱动:未查"))
        px = f"坏点:{r['pixel'][0]}/8 色" if r["pixel"] else "坏点:未测"
        kb = (f"键鼠:{r['keyboard'][0]}/{r['keyboard'][1]} 键" if r["keyboard"]
              else "键鼠:未测")
        return f"{drv} · {px} · {kb}"

    def _touch_hw_status(self):
        try:
            self._hw_state_lbl.config(text=self._hw_status_text())
        except Exception:
            pass

    # ── 屏幕坏点测试：全屏纯色循环，找出坏点/亮点/暗点 ──
    def _pixel_test(self):
        colors = [("纯白", "#ffffff"), ("纯黑", "#000000"), ("纯红", "#ff0000"),
                  ("纯绿", "#00ff00"), ("纯蓝", "#0000ff"), ("纯黄", "#ffff00"),
                  ("纯青", "#00ffff"), ("纯品红", "#ff00ff")]
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.geometry(f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")
        win.attributes("-topmost", True)
        idx = {"i": 0}
        visited = {0}
        hint = None

        def _show_hint():
            nonlocal hint
            if hint is not None and hint.winfo_exists():
                hint.destroy()
            hint = tk.Label(win, text=f"{colors[idx['i']][0]}  ·  单击=下一色  Esc=退出",
                            bg="#000000", fg="#ffffff", font=(FONT_UI, 12, "bold"))
            hint.place(relx=0.5, rely=0.96, anchor="center")
            win.after(2500, _hide_hint)

        def _hide_hint():
            nonlocal hint
            if hint is not None and hint.winfo_exists():
                hint.destroy()
                hint = None

        def _apply():
            win.configure(bg=colors[idx["i"]][1])
            _show_hint()

        def _next(_e=None):
            idx["i"] = (idx["i"] + 1) % len(colors)
            visited.add(idx["i"])
            _apply()

        def _prev(_e=None):
            idx["i"] = (idx["i"] - 1) % len(colors)
            visited.add(idx["i"])
            _apply()

        def _quit(_e=None):
            self._hw_results["pixel"] = (len(visited), len(colors))
            self._touch_hw_status()
            try:
                win.destroy()
            except Exception:
                pass
        for seq in ("<Button-1>", "<space>", "<Right>", "<Return>"):
            win.bind(seq, _next)
        win.bind("<Left>", _prev)
        win.bind("<Escape>", _quit)
        win.focus_force()
        _apply()

    # ── 键盘·鼠标测试：全屏可视化按键，验证每个键与鼠标事件 ──
    _KB_ROWS = [
        [("`", "quoteleft"), ("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"), ("5", "5"),
         ("6", "6"), ("7", "7"), ("8", "8"), ("9", "9"), ("0", "0"), ("-", "minus"),
         ("=", "equal"), ("⌫", "BackSpace")],
        [("Tab", "Tab"), ("Q", "q"), ("W", "w"), ("E", "e"), ("R", "r"), ("T", "t"),
         ("Y", "y"), ("U", "u"), ("I", "i"), ("O", "o"), ("P", "p"), ("[", "bracketleft"),
         ("]", "bracketright"), ("\\", "backslash")],
        [("Caps", "Caps_Lock"), ("A", "a"), ("S", "s"), ("D", "d"), ("F", "f"),
         ("G", "g"), ("H", "h"), ("J", "j"), ("K", "k"), ("L", "l"), (";", "semicolon"),
         ("'", "apostrophe"), ("Enter", "Return")],
        [("Shift", "Shift_L"), ("Z", "z"), ("X", "x"), ("C", "c"), ("V", "v"),
         ("B", "b"), ("N", "n"), ("M", "m"), (",", "comma"), (".", "period"),
         ("/", "slash"), ("Shift", "Shift_R")],
        [("Ctrl", "Control_L"), ("Win", "Win_L"), ("Alt", "Alt_L"),
         ("──── 空格 ────", "space"), ("Alt", "Alt_R"), ("Fn", "Fn"),
         ("☰", "Menu"), ("Ctrl", "Control_R")],
    ]

    def _keyboard_test(self):
        win = tk.Toplevel(self.root)
        win.title("键盘·鼠标测试（Esc 退出）")
        win.configure(bg="#08090c")
        win.geometry(f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")
        win.attributes("-topmost", True)
        win.focus_force()
        status = tk.Label(win, text="已测按键 0/0 · 按下物理按键点亮对应键位；全部点亮即通过 · Esc=退出",
                          bg="#08090c", fg=TEXT2, font=(FONT_UI, 11))
        status.pack(pady=(24, 8))
        c = tk.Canvas(win, bg="#08090c", highlightthickness=0)
        c.pack(expand=True)
        rects = {}
        KW, KH, GAP = 52, 46, 5
        y = 8
        for row in self._KB_ROWS:
            x = 8
            for label, keysym in row:
                w = KW * (2 if keysym in ("BackSpace", "Tab", "Caps_Lock", "Return",
                                          "Shift_L") else
                          (1 if keysym not in ("space",) else 7))
                r = c.create_rectangle(x, y, x + w, y + KH, fill=PANEL2, outline=BORDER)
                t = c.create_text(x + w / 2, y + KH / 2, text=label, fill=TEXT2,
                                  font=(FONT_UI, 9))
                rects[keysym] = (r, t, x, y, x + w, y + KH)
                x += w + GAP
            y += KH + GAP
        mrow = 3
        m_y = y + 12
        mouse = {}
        mx = 8
        for label in ("鼠标左键", "鼠标右键", "鼠标中键", "滚轮↑", "滚轮↓"):
            r = c.create_rectangle(mx, m_y, mx + 110, m_y + 40, fill=PANEL2, outline=BORDER)
            t = c.create_text(mx + 55, m_y + 20, text=label + " 0", fill=TEXT2,
                              font=(FONT_UI, 9))
            mouse[label] = (r, t)
            mx += 118
        hit = {"keys": set(), "total": 0}
        keymap = {}
        for row in self._KB_ROWS:
            for label, keysym in row:
                keymap[keysym] = keysym   # 直接以 keysym 为索引
        def _light(keysym, on):
            e = rects.get(keysym)
            if not e:
                return False
            r, t, x0, y0, x1, y1 = e
            c.itemconfig(r, fill=CYAN if on else PANEL2)
            c.itemconfig(t, fill="#0d1117" if on else TEXT2)
            return True
        def _press(e):
            hit["total"] += 1
            ks = e.keysym
            if ks in rects and ks not in hit["keys"]:
                hit["keys"].add(ks)
            _light(ks, True)
            tested = sum(1 for ks in rects if ks in hit["keys"])
            status.config(text=f"已测按键 {tested}/{len(rects)} · 累计 {hit['total']} 次 · "
                               "全部点亮即通过 · Esc=退出",
                          fg=GREEN if tested >= len(rects) else TEXT2)
        def _release(e):
            _light(e.keysym, False)
        def _mb(e, label):
            r, t = mouse[label]
            n = int(c.itemcget(t, "text").split()[-1]) + 1
            c.itemconfig(t, text=f"{label} {n}")
            c.itemconfig(r, fill=GREEN)
            win.after(200, lambda: c.itemconfig(r, fill=PANEL2))
        win.bind("<KeyPress>", _press)
        win.bind("<KeyRelease>", _release)
        win.bind("<Button-1>", lambda e: _mb(e, "鼠标左键"))
        win.bind("<Button-3>", lambda e: _mb(e, "鼠标右键"))
        win.bind("<Button-2>", lambda e: _mb(e, "鼠标中键"))
        win.bind("<MouseWheel>", lambda e: _mb(e, "滚轮↑" if e.delta > 0 else "滚轮↓"))
        def _close(_e=None):
            tested = sum(1 for ks in rects if ks in hit["keys"])
            self._hw_results["keyboard"] = (tested, len(rects))
            self._touch_hw_status()
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", _close)
        win.bind("<Escape>", _close)

    # ── 驱动异常检查 ──
    def _driver_dialog(self):
        top = tk.Toplevel(self.root)
        top.title("驱动异常检查")
        top.configure(bg=BG)
        top.geometry("760x520")
        top.transient(self.root)
        enable_dark_title_bar(top)
        tk.Label(top, text="◈ 驱动健康检查", bg=BG, fg=YELLOW,
                 font=(FONT_UI, 12, "bold")).pack(anchor="w", padx=16, pady=(12, 2))
        status = tk.Label(top, text="正在枚举问题设备与显卡驱动…（约 10~30 秒）", bg=BG,
                          fg=TEXT2, font=(FONT_MONO, 8))
        status.pack(anchor="w", padx=16)
        # 操作按钮先占住底部：窗口高度不够时也不再被挤没
        btnf = tk.Frame(top, bg=BG)
        btnf.pack(side="bottom", fill="x", padx=16, pady=(4, 12))
        holder = tk.Frame(top, bg=BG)
        holder.pack(fill="both", expand=True, padx=16, pady=(6, 4))
        tree = ttk.Treeview(holder, columns=("状态",), show="tree headings", height=15)
        vs = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vs.set)
        tree.column("#0", width=480, anchor="w")
        tree.heading("#0", text="项目")
        tree.column("状态", width=200, anchor="w")
        tree.heading("状态", text="状态")
        vs.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        q = queue.Queue()
        def _do():
            q.put(scan_driver_issues())
        threading.Thread(target=_do, daemon=True).start()
        result = {}
        def _poll():
            try:
                if not top.winfo_exists():
                    return   # 对话框已关闭
            except Exception:
                return
            try:
                result["data"] = q.get_nowait()
            except queue.Empty:
                top.after(300, _poll)
                return
            d = result["data"]
            self._hw_results["driver"] = list(d["problems"])
            self._touch_hw_status()
            tree.delete(*tree.get_children())
            if not d["problems"]:
                tree.insert("", "end", text="  ✅ 设备管理器无异常设备",
                            values=("全部驱动工作正常",), tags=("ok",))
            else:
                tree.insert("", "end", text=f"  ⚠ 发现 {len(d['problems'])} 个问题设备",
                            values=("建议重装驱动或重启",), tags=("warn",))
                for p in d["problems"]:
                    tree.insert("", "end", text="      " + p["name"],
                                values=(f"错误码 {p['code']} · {p['why']}",), tags=("warn2",))
            for g in d["gpus"]:
                tree.insert("", "end", text="  🎮 " + g["name"],
                            values=(f"驱动 {g['ver']} · {g['date']}",), tags=("ok",))
            status.config(text=f"检查完成：{len(d['problems'])} 个问题设备 · "
                               f"{len(d['gpus'])} 张显卡")
        tree.tag_configure("ok", foreground=GREEN)
        tree.tag_configure("warn", foreground=RED, font=(FONT_UI, 10, "bold"))
        tree.tag_configure("warn2", foreground=ORANGE)
        top.after(300, _poll)
        def _export():
            d = result.get("data") or {"problems": [], "gpus": []}
            lines = [f"驱动健康检查  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
                     "=" * 48]
            if d["problems"]:
                lines.append(f"问题设备 {len(d['problems'])} 个：")
                for p in d["problems"]:
                    lines.append(f"  · {p['name']}（{p['why']}）")
            else:
                lines.append("问题设备：无")
            for g in d["gpus"]:
                lines.append(f"显卡：{g['name']} · 驱动 {g['ver']} · {g['date']}")
            path = Path.home() / f"驱动检查_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            path.write_text("\n".join(lines), encoding="utf-8")
            show_info("已导出", f"报告已保存到:\n{path}")
        tk.Button(btnf, text="📄 导出报告", bg=PANEL2, fg=YELLOW, font=(FONT_UI, 9),
                  bd=0, relief="flat", cursor="hand2", command=_export).pack(side="left")
        tk.Button(btnf, text="🛠 打开设备管理器", bg=PANEL2, fg=CYAN, font=(FONT_UI, 9),
                  bd=0, relief="flat", cursor="hand2",
                  command=lambda: os.startfile("devmgmt.msc")).pack(side="left", padx=(8, 0))

    def start(self):
        self._activation.start(); self._setup.start()
    def stop(self):
        self._activation.stop(); self._setup.stop()
    def on_show(self): pass


# ═══════════════════════════════════════════
# 主窗口
# ═══════════════════════════════════════════

MODULES = [HomeModule, HardwareModule, ClipboardModule,
           SpaceModule, SoftwareModule, LaunchModule, UtilityModule,
           VerifyModule]


class App:
    def __init__(self, root):
        self.root = root
        self._closing = False
        self._ui_events = queue.Queue()
        self._stop_event = threading.Event()
        self._tray_ready = False
        self._tray_icon = None
        self._tray_lock = threading.Lock()
        self._hotkey_thread_id = None
        self._target_identity(0)  # establish pointer-sized Win32 signatures early
        self._page_cleanup = None
        root.protocol('WM_DELETE_WINDOW', self._hide_to_tray)
        self._event_timer = root.after(50, self._drain_ui_events)
        root.title(f"{APP_NAME} {APP_VERSION}")
        root.configure(bg=BG)
        self._setup_ttk_style()
        try: ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except: pass

        # 懒加载模块：启动只建页签（读类属性），页面实例在首次切换时才创建
        self._module_classes = {cls.name: cls for cls in MODULES}
        self.modules = {}

        self._build_ui()
        self._bind_hotkeys()
        self._switch("home")
        # 恢复上次窗口大小/位置（无保存记录则用默认）
        saved_geo = SETTINGS.get("geometry", "")
        root.geometry(self._validated_geometry(saved_geo))
        root.minsize(1100, 500)
        # 窗口状态复原：要么用户勾了"启动时最大化"，要么上次退出时就是最大化的。
        # 旧版完全没有这段：_save_geometry 在最大化时直接 return，既不记录用户
        # 想要最大化，也不复原，于是每次启动都回到那个小尺寸 —— 就是"开起来只有半屏"。
        if SETTINGS.get("start_maximized") or SETTINGS.get("maximized"):
            try:
                root.update_idletasks()
                root.state("zoomed")
            except Exception:
                pass
        # 标题栏跟随主题深浅（需窗口已布局后调用）
        enable_dark_title_bar(root)
        root.after(300, lambda: enable_dark_title_bar(root))  # 显式显示后再补一次

        # ─── 常驻能力：剪贴板监听提前启动 + 托盘 + 全局热键 ───
        try:
            cm = self.module("clipboard")
            cm._load_history()
            cm._ensure_watcher()
        except Exception:
            pass
        self._quick_panel = None
        self._setup_tray_and_hotkey()
        self._reset_schedule()

    def module(self, name):
        """按名获取模块实例（首次访问时创建）。"""
        m = self.modules.get(name)
        if m is None:
            m = self._module_classes[name](self)
            self.modules[name] = m
        return m

    # ─── 定时任务（定时清理 / 休息提醒）───
    def _reset_schedule(self):
        """按设置重排下次执行时间（设置保存/启动时调用）。"""
        now = time.time()
        self._next_clean = (now + _as_int(SETTINGS.get("sch_clean_hours"), 168, lo=1) * 3600
                            if SETTINGS.get("sch_clean_enabled") else None)
        self._next_rest = (now + _as_int(SETTINGS.get("sch_rest_minutes"), 45, lo=5) * 60
                           if SETTINGS.get("sch_rest_enabled") else None)
        job = getattr(self, "_sch_job", None)
        if job:
            try: self.root.after_cancel(job)
            except Exception: pass
        self._sch_job = None
        self._schedule_tick()

    def _schedule_tick(self):
        if self._closing:
            return
        now = time.time()
        if self._next_clean is not None and now >= self._next_clean:
            self._next_clean = now + _as_int(SETTINGS.get("sch_clean_hours"), 168, lo=1) * 3600
            threading.Thread(target=self._run_scheduled_clean, daemon=True).start()
        if self._next_rest is not None and now >= self._next_rest:
            self._next_rest = now + _as_int(SETTINGS.get("sch_rest_minutes"), 45, lo=5) * 60
            self._rest_reminder()
        self._sch_job = self.root.after(30000, self._schedule_tick)

    def _run_scheduled_clean(self):
        """静默定时清理：只跑白名单目录，结果写审计日志（不弹窗打断）。"""
        try:
            worker = getattr(self, "_clean_worker", None)
            if worker is None:
                worker = CleanupModule(self)
                self._clean_worker = worker
            jobs = tuple((c, p, pat) for c, p, pat, _d in worker._junk_dirs())
            totals = worker._delete_clean_jobs(jobs)
            if self._tray_ready and self._tray_icon is not None:
                try:
                    self._tray_icon.notify(
                        f"定时清理完成：删除 {totals.get('count', 0)} 个文件",
                        APP_NAME)
                except Exception:
                    pass
        except Exception:
            pass

    def _rest_reminder(self):
        if self._closing:
            return
        try:
            win = tk.Toplevel(self.root)
            win.title("休息一下")
            win.attributes("-topmost", True)
            win.configure(bg=BG)
            win.geometry("340x170")
            win.transient(self.root)
            enable_dark_title_bar(win)
            tk.Label(win, text="👀 该休息一下了", bg=BG, fg=CYAN,
                     font=(FONT_UI, 14, "bold")).pack(expand=True)
            tk.Label(win, text="远眺 20 秒，放松眼睛和肩膀", bg=BG, fg=TEXT2,
                     font=(FONT_UI, 9)).pack()
            tk.Button(win, text="知道了", bg=PANEL2, fg=CYAN, font=(FONT_UI, 9),
                      bd=0, relief="flat", cursor="hand2",
                      command=win.destroy).pack(pady=12)
            self.root.after(60000, lambda: win.destroy() if win.winfo_exists() else None)
        except Exception:
            pass

    def _setup_ttk_style(self):
        """ttk 控件统一配色（主题切换时整组重刷）。"""
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, borderwidth=0)
        style.configure("Treeview", background=PANEL, foreground=TEXT,
                        borderwidth=0, fieldbackground=PANEL,
                        rowheight=30, font=(FONT_MONO, 9))
        style.configure("Treeview.Heading", background=PANEL3, foreground=CYAN,
                        borderwidth=0, relief="flat",
                        font=(FONT_UI, 9, "bold"), padding=(8, 6))
        style.map("Treeview.Heading", background=[("active", PANEL3)])
        # 选中行：强调色高亮（旧 PANEL2 与底色几乎无差别）
        style.map("Treeview", background=[("selected", PANEL3)],
                  foreground=[("selected", CYAN)])
        # 滚动条：窄条、无箭头（原生灰白样式与主题割裂）
        for _o in ("Vertical", "Horizontal"):
            style.layout(f"{_o}.TScrollbar", [
                (f"{_o}.Scrollbar.trough", {"children": [
                    (f"{_o}.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})],
                    "sticky": "ns" if _o == "Vertical" else "we"})])
            style.configure(f"{_o}.TScrollbar", background=PANEL2, troughcolor=BG,
                            bordercolor=BG, relief="flat")
            style.map(f"{_o}.TScrollbar",
                      background=[("active", PANEL3), ("pressed", BORDER)])
        style.configure("Frame", background=BG)

    def _apply_theme_live(self, name):
        """实时切换主题：改写全局色值 → 重刷 ttk → 重绘顶部骨架 → 重建当前页。"""
        apply_theme(name)
        self._setup_ttk_style()
        r = self.root
        r.configure(bg=BG)
        self.tab_frame.config(bg=PANEL)
        for n, btn in self.tab_btns.items():
            active = (n == self.current.name) if getattr(self, "current", None) else False
            btn.config(bg=PANEL2 if active else PANEL,
                       fg=CYAN if active else TEXT2,
                       activebackground=PANEL2, activeforeground=CYAN)
        sb = getattr(self, "_settings_btn", None)
        if sb is not None:
            sb.config(bg=PANEL, fg=TEXT2, activebackground=PANEL2, activeforeground=CYAN)
        vl = getattr(self, "_version_lbl", None)
        if vl is not None:
            vl.config(bg=PANEL, fg=MUTED)
        self._strip.config(bg=BG)
        self._draw_strip()
        self.status_bar.config(bg=PANEL2)
        self.status_lbl.config(bg=PANEL2, fg=TEXT2)
        self.clock_lbl.config(bg=PANEL2, fg=GREEN)
        if getattr(self, "_tab_ind", None) is not None:
            self._tab_ind.config(bg=CYAN)
        enable_dark_title_bar(r)
        # 重建当前页（所有控件在创建时读取色值）
        self._switch(self.current.name)
        # 设置窗口若开着，关掉重开以套用新配色
        sw = getattr(self, "_settings_win", None)
        if sw is not None and sw.winfo_exists():
            sw.destroy()
            self._settings_win = None
            r.after(60, self.show_settings)

    def _save_geometry(self):
        """记住窗口大小/位置，以及当时是否最大化。

        旧版在最大化时直接 return：既不记录"用户要最大化"，也不更新 geometry。
        于是习惯最大化使用的用户，每次启动都回到上一次的窗口态尺寸 ——
        在 1920x1080 上就是 1100x906 那一小块，看着像"只开了半屏"。
        现在把最大化状态一起持久化，启动时如实复原；窗口态尺寸仍只在非最大化
        时更新，所以从最大化还原（双击标题栏）依然落在一个正常大小上。
        """
        try:
            maximized = self.root.state() == "zoomed"
            SETTINGS["maximized"] = maximized
            if not maximized:
                SETTINGS["geometry"] = self._validated_geometry(self.root.geometry())
            save_settings()
        except Exception:
            pass

    # ─── 托盘 / 全局热键 / 剪贴板快速面板（借鉴 Ditto 形态）───
    def _setup_tray_and_hotkey(self):
        if os.environ.get("UTB_NO_TRAY"):
            return
        threading.Thread(target=self._hotkey_worker, daemon=True).start()
        if TRAY_OK:
            threading.Thread(target=self._tray_worker, daemon=True).start()

    def _hotkey_worker(self):
        user32 = None
        registered = []
        try:
            user32 = ctypes.windll.user32
            self._hotkey_thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
            msg = ctypes.wintypes.MSG()
            # Create message queue before shutdown can post WM_QUIT.
            user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
            vk = str(SETTINGS.get('hotkey_vk') or 'V').upper()[:1]
            if len(vk) != 1 or not vk.isascii() or not vk.isalnum():
                vk = 'V'
            for ident, key in ((1, vk), (2, 'T')):
                if user32.RegisterHotKey(None, ident, 0x4003, ord(key)):
                    registered.append(ident)
            if not registered:
                return
            while not self._stop_event.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0 or self._stop_event.is_set():
                    break
                if msg.message == 0x0312 and msg.wParam in registered:
                    action = 'quick' if msg.wParam == 1 else 'pin'
                    self._ui_events.put((action, user32.GetForegroundWindow()))
        except Exception:
            pass
        finally:
            if user32 is not None:
                for ident in registered:
                    user32.UnregisterHotKey(None, ident)
            self._hotkey_thread_id = None

    def toggle_pin_action(self):
        """置顶切换 + 精致提示条（顶部居中，1.5s 自动消散）"""
        try:
            pinned, title = toggle_pin_foreground()
            if pinned is None:
                return
            t = tk.Toplevel(self.root)
            t.overrideredirect(True)
            t.attributes("-topmost", True)
            txt = (f"📌 已置顶 · {title[:36]}" if pinned
                   else f"📌 已取消置顶 · {title[:36]}")
            tk.Label(t, text=f"  {txt}  ", bg=PANEL2,
                     fg=CYAN if pinned else TEXT2,
                     font=(FONT_UI, 10, "bold"), padx=18, pady=9,
                     highlightthickness=1, highlightbackground=BORDER).pack()
            t.update_idletasks()
            x = (t.winfo_screenwidth() - t.winfo_width()) // 2
            y = int(t.winfo_screenheight() * 0.12)
            t.geometry(f"+{x}+{y}")
            t.after(1500, t.destroy)
        except Exception:
            pass

    def _tray_worker(self):
        try:
            img = _PILImage.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = _PILDraw.Draw(img)
            d.rounded_rectangle([3, 3, 61, 61], radius=14, fill=(13, 17, 23, 255),
                                outline=(0, 137, 233, 255), width=4)
            d.ellipse([22, 12, 42, 32], fill=(0, 180, 216, 255))
            d.rounded_rectangle([16, 40, 48, 51], radius=5, fill=(45, 212, 160, 255))
            menu = pystray.Menu(
                pystray.MenuItem(T("显示主窗口"),
                                 lambda *a: self._ui_events.put(("show", None)), default=True),
                pystray.MenuItem(T("剪贴板面板 (Ctrl+Alt+V)") if SETTINGS.get("lang") == "en"
                                 else "剪贴板面板 (Ctrl+Alt+V)",
                                 lambda *a: self._ui_events.put(("quick", None))),
                pystray.MenuItem(T("窗口置顶 (Ctrl+Alt+T)") if SETTINGS.get("lang") == "en"
                                 else "窗口置顶 (Ctrl+Alt+T)",
                                 lambda *a: self._ui_events.put(("pin", None))),
                pystray.MenuItem(T("设置") if SETTINGS.get("lang") == "en" else "设置",
                                 lambda *a: self._ui_events.put(("settings", None))),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(T("退出"), lambda *a: self._ui_events.put(("quit", None))),
            )
            icon = pystray.Icon(APP_NAME, img, f"{APP_NAME} {APP_VERSION}", menu)
            with self._tray_lock:
                if self._stop_event.is_set():
                    return
                self._tray_icon = icon
            def ready(tray):
                with self._tray_lock:
                    if self._stop_event.is_set():
                        # setup runs on pystray's setup thread; stop() may join
                        # that thread, so call it from a separate daemon.
                        threading.Thread(target=tray.stop, daemon=True).start()
                        return
                    tray.visible = True
                    self._ui_events.put(('tray_ready', tray))
            try:
                icon.run(setup=ready)
            finally:
                self._ui_events.put(('tray_stopped', icon))
        except Exception:
            self._ui_events.put(('tray_stopped', getattr(self, '_tray_icon', None)))

    def _hide_to_tray(self):
        """关主窗口：跟随设置（托盘/退出）。托盘不可用时必须真退出，
        否则窗口永久消失、只能任务管理器杀进程（旧版隐患）。"""
        self._save_geometry()
        if self._closing:
            return
        has_tray = self._tray_ready and self._tray_icon is not None
        if SETTINGS.get("close_action", "tray") == "tray" and has_tray:
            self.root.withdraw()
            if not getattr(self, "_tray_hinted", False):
                self._tray_hinted = True
                try:
                    self._tray_icon.notify("已最小化到托盘：双击图标恢复，右键可退出", APP_NAME)
                except Exception:
                    pass
        else:
            self._quit_app()

    def _show_main(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _quit_app(self):
        if self._closing:
            return
        self._closing = True
        self._save_geometry()
        self._stop_event.set()
        if self._page_cleanup:
            self._page_cleanup()
            self._page_cleanup = None
        for module in self.modules.values():
            try:
                shutdown = getattr(module, 'shutdown', None)
                (shutdown if callable(shutdown) else module.stop)()
            except Exception:
                pass
        try:
            self.root.after_cancel(self._event_timer)
        except Exception:
            pass
        try:
            if self._hotkey_thread_id:
                ctypes.windll.user32.PostThreadMessageW(self._hotkey_thread_id, 0x0012, 0, 0)
        except Exception:
            pass
        with self._tray_lock:
            icon = self._tray_icon
            self._tray_ready = False
        if icon is not None:
            # pystray stop may wait for its setup thread; never block Tk on it.
            def stop_tray():
                try:
                    icon.stop()
                except Exception:
                    pass
            threading.Thread(target=stop_tray, daemon=True).start()
        self._qp_hide()
        # 统一取消所有待执行 after：避免销毁瞬间 Tcl 触发已失效回调产生 bgerror
        try:
            for after_id in str(self.root.tk.eval("after info")).split():
                try: self.root.after_cancel(after_id)
                except Exception: pass
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def show_quick_panel(self, target=None):
        """全局热键呼出的剪贴板快速面板：回车/双击 → 复制并自动粘贴回原窗口"""
        cm = self.module("clipboard")
        if not cm.history:
            try:
                cm._load_history()
            except Exception:
                pass
        # 记住呼出前的前台窗口，粘贴时还原焦点
        if self._closing:
            return
        if not (self._quick_panel and self._quick_panel.winfo_viewable()):
            target = target or ctypes.windll.user32.GetForegroundWindow()
            self._fg_before_panel = self._target_identity(target)
        if self._quick_panel is None or not self._quick_panel.winfo_exists():
            self._quick_panel = self._build_quick_panel()
        qp, lb = self._quick_panel, self._quick_panel.listbox
        lb.delete(0, "end")
        self._qp_items = [dict(h) for h in cm.history[:15]]
        for h in self._qp_items:
            text = str(h.get("text", "")).replace("\n", " ")[:56]
            lb.insert("end", f"{h.get('time', '')}  {text}")
        qp.update_idletasks()
        # 面板出现在鼠标附近（ clamp 到屏幕内）
        x = min(max(0, qp.winfo_pointerx() - 280), qp.winfo_screenwidth() - 540)
        y = min(max(0, qp.winfo_pointery() + 14), qp.winfo_screenheight() - 380)
        qp.geometry(f"+{x}+{y}")
        qp.deiconify()
        lb.selection_clear(0, "end")
        lb.selection_set(0)
        lb.activate(0)
        lb.focus_set()

    def _build_quick_panel(self):
        qp = tk.Toplevel(self.root)
        qp.title("剪贴板快速面板")
        qp.overrideredirect(True)  # 无边框弹出层（Ditto 风）
        qp.configure(bg=BORDER)
        qp.attributes("-topmost", True)
        tk.Label(qp, text=" ⚡ 剪贴板 · 回车/双击=粘贴 · Esc=关闭 ", bg=PANEL, fg=CYAN,
                 font=(FONT_UI, 9, "bold")).pack(fill="x")
        lb = tk.Listbox(qp, bg=PANEL2, fg=TEXT, font=(FONT_MONO, 9),
                        selectbackground=CYAN, selectforeground=BG,
                        relief="flat", bd=0, width=66, height=12, activestyle="none",
                        highlightthickness=1, highlightbackground=BORDER,
                        highlightcolor=CYAN)
        lb.pack(fill="both", expand=True, padx=1, pady=1)
        lb.bind("<Return>", self._qp_paste)
        lb.bind("<Double-Button-1>", self._qp_paste)
        lb.bind("<Escape>", lambda e: self._qp_hide())
        qp.bind("<Escape>", lambda e: self._qp_hide())
        qp.bind("<FocusOut>", lambda e: self.root.after(200, self._qp_maybe_hide))
        qp.listbox = lb
        return qp

    def _qp_paste(self, event=None):
        lb = self._quick_panel.listbox
        sel = lb.curselection()
        cm = self.modules.get("clipboard")
        if not sel or cm is None or sel[0] >= len(self._qp_items):
            return "break"
        h = self._qp_items[sel[0]]
        # 面板存的是历史条目的副本：按 id 找回真身，让 uses 计数与持久化落到正主上
        real = next((x for x in cm.history if x.get("id") and x.get("id") == h.get("id")), h)
        if h.get("type") == "img":
            # 图片条目要写 CF_DIB。旧版统一走 clipboard_append(text)，
            # 结果是目标程序粘到 "[图片] 800×600" 这段字面文字。
            if not cm._copy_img(real):
                self._qp_hide()          # 缓存已被清理：别把残留内容粘到别人窗口
                return "break"
        else:
            cm._copy_text(h.get("text", ""))
        self._qp_hide()
        # 还原焦点到呼出前的窗口，再模拟 Ctrl+V 完成真正的"粘贴"
        try:
            target = self._fg_before_panel
            if target and self._target_identity(target[0]) == target:
                if ctypes.windll.user32.SetForegroundWindow(target[0]):
                    self.root.after(120, lambda: self._send_ctrl_v(target))
        except Exception:
            pass
        return "break"

    def _qp_hide(self):
        try:
            if self._quick_panel and self._quick_panel.winfo_exists():
                self._quick_panel.withdraw()
        except Exception:
            pass

    def _qp_maybe_hide(self):
        try:
            panel = self._quick_panel
            widget = self.root.focus_get()
            if panel is not None and widget is not None:
                if widget.winfo_toplevel() is panel:
                    return
            self._qp_hide()
        except Exception:
            self._qp_hide()

    def _send_ctrl_v(self, target):
        if self._closing or not target:
            return False
        u32 = ctypes.windll.user32
        try:
            if (self._target_identity(target[0]) != target or
                    u32.GetForegroundWindow() != target[0]):
                return False
            # Do not interfere with keys the user is currently holding.
            if any(u32.GetAsyncKeyState(k) & 0x8000 for k in (0x10, 0x11, 0x12, 0x5B, 0x5C)):
                return False
            try:
                u32.keybd_event(0x11, 0, 0, 0)
                u32.keybd_event(0x56, 0, 0, 0)
            finally:
                u32.keybd_event(0x56, 0, 2, 0)
                u32.keybd_event(0x11, 0, 2, 0)
            return True
        except Exception:
            return False

    def _build_ui(self):
        self.tab_frame = tk.Frame(self.root, bg=PANEL, height=46)
        self.tab_frame.pack(fill="x", side="top")
        self.tab_frame.pack_propagate(False)
        self.tab_btns = {}
        # 页签按功能分组（视觉归类）：首页 ‖ 硬件·验机 ‖ 清理·管家 ‖ 效率
        tab_groups = [("home",),
                      ("hardware", "verify"),
                      ("space", "software", "launch"),
                      ("clipboard", "utility")]
        for gi, group in enumerate(tab_groups):
            if gi:
                sep = tk.Canvas(self.tab_frame, bg=PANEL, width=1, height=20,
                                highlightthickness=0)
                sep.create_line(0, 3, 0, 17, fill=MUTED)
                sep.pack(side="left", padx=4, pady=6)
            for name in group:
                cls = self._module_classes[name]
                btn = tk.Button(self.tab_frame, text=f"  {cls.icon}  {T(cls.label)}  ",
                                bg=PANEL, fg=TEXT2, font=(FONT_UI, 10, "bold"),
                                activebackground=PANEL2, activeforeground=CYAN,
                                bd=0, relief="flat", cursor="hand2",
                                takefocus=0, highlightthickness=0,
                                command=lambda n=name: self._switch(n))
                btn.pack(side="left", padx=4, pady=6)
                btn.bind("<Enter>", lambda e=None, b=btn: b.config(bg=PANEL2, fg=CYAN))
                btn.bind("<Leave>", lambda e=None, b=btn: b.config(bg=PANEL, fg=TEXT2))
                self.tab_btns[name] = btn
        set_btn = tk.Button(self.tab_frame, text="⚙ 设置", bg=PANEL, fg=TEXT2,
                            font=(FONT_UI, 10, "bold"), activebackground=PANEL2,
                            activeforeground=CYAN, bd=0, relief="flat",
                            cursor="hand2", takefocus=0,
                            command=self.show_settings)
        set_btn.pack(side="right", padx=(0, 8))
        set_btn.bind("<Enter>", lambda e=None, b=set_btn: b.config(fg=CYAN))
        set_btn.bind("<Leave>", lambda e=None, b=set_btn: b.config(fg=TEXT2))
        self._settings_btn = set_btn
        vl = tk.Label(self.tab_frame, text=APP_VERSION, bg=PANEL, fg=MUTED,
                      font=(FONT_MONO, 8))
        vl.pack(side="right", padx=12)
        self._version_lbl = vl

        # 主题渐变装饰线（分段绘制避免逐像素卡顿；色值取自当前主题 STRIP）
        self._strip = tk.Canvas(self.root, bg=BG, height=4, highlightthickness=0)
        self._strip.pack(fill="x", side="top")
        self._strip.bind("<Configure>", self._draw_strip)

        self.body = tk.Frame(self.root, bg=BG)
        self.body.pack(fill="both", expand=True)

        self.status_bar = tk.Frame(self.root, bg=PANEL2, height=24)
        self.status_bar.pack(fill="x", side="bottom")
        self.status_bar.pack_propagate(False)
        self.status_lbl = tk.Label(self.status_bar, text="◈ 就绪", bg=PANEL2,
                                    fg=TEXT2, font=(FONT_MONO, 8), anchor="w")
        self.status_lbl.pack(side="left", padx=12, fill="x", expand=True)
        self.clock_lbl = tk.Label(self.status_bar, bg=PANEL2, fg=GREEN,
                                   font=(FONT_MONO, 8))
        self.clock_lbl.pack(side="right", padx=12)
        self._tick_clock()

    def _draw_strip(self, e=None):
        sc = self._strip
        sc.delete("all")
        w = sc.winfo_width()
        c1, c2 = THEMES.get(THEME_NAME, THEMES["blue"])["STRIP"]
        r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
        r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
        seg = 16  # 每16px一段渐变，视觉上平滑
        for i in range(0, w, seg):
            t = i / max(1, w - 1)
            r = int(r1 + (r2 - r1) * t); g = int(g1 + (g2 - g1) * t); b = int(b1 + (b2 - b1) * t)
            sc.create_rectangle(i, 0, min(i + seg, w), 4,
                                outline="", fill="#%02x%02x%02x" % (r, g, b))

    def _bind_hotkeys(self):
        self.root.bind("<Control-Alt-d>", lambda e: self._switch("clipboard"))

    # ─── 在线更新（只在手动点「检查更新」时联网，不做后台静默请求）───
    def check_update(self, repo=None):
        """查最新 Release → 比对版本 → 询问 → 下载 → 退出后自替换并重启。"""
        repo = (repo if repo is not None else SETTINGS.get("update_repo", "")) \
            or UPDATE_REPO_DEFAULT
        repo = repo.strip()
        if not repo or "/" not in repo:
            show_info("未配置更新源",
                      "请先在上面的「更新源」里填 owner/repo，例如 myname/toolbox。\n\n"
                      "并确认该仓库已发布 Release，且把 exe 作为附件上传。",
                      parent=getattr(self, "_settings_win", None) or self.root)
            return
        win = tk.Toplevel(self.root)
        win.title("检查更新")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self.root)
        enable_dark_title_bar(win)
        tk.Label(win, text=f"正在检查 {repo} …", bg=BG, fg=TEXT2,
                 font=(FONT_UI, 9)).pack(padx=26, pady=(20, 8))
        bar = ttk.Progressbar(win, mode="indeterminate", length=320)
        bar.pack(padx=26, pady=(0, 18))
        bar.start(12)
        win.update_idletasks()
        _center_on(win, self.root)

        q = queue.Queue()
        threading.Thread(target=lambda: q.put(fetch_latest_release(repo)),
                         daemon=True).start()

        def _poll():
            try:
                if not win.winfo_exists():
                    return
            except Exception:
                return
            try:
                tag, url, name, err = q.get_nowait()
            except queue.Empty:
                win.after(200, _poll)
                return
            bar.stop()
            win.destroy()
            if err:
                show_warning("检查更新失败", err, parent=self.root)
                return
            if not tag:
                show_warning("检查更新失败", "Release 里没有版本号", parent=self.root)
                return
            if version_key(tag) <= version_key(APP_VERSION):
                show_info("已是最新版本",
                          f"当前 {APP_VERSION}，最新 {tag}。", parent=self.root)
                return
            if not url:
                show_warning("该版本没有可下载的文件",
                             f"最新版本 {tag} 的 Release 里没有 exe 附件。\n"
                             "请在 GitHub 上把打包好的 exe 作为 Release 附件上传。",
                             parent=self.root)
                return
            if not ask_yesno("发现新版本",
                             f"当前版本：{APP_VERSION}\n最新版本：{tag}\n"
                             f"更新文件：{name}\n\n"
                             "现在下载并更新吗？下载完成后程序会自动退出、"
                             "替换自身并重新启动。",
                             parent=self.root):
                return
            self._download_update(url, name)
        win.after(200, _poll)

    def _download_update(self, url, name):
        """下载更新包，然后交给批处理在退出后替换 exe 并重启。"""
        dest = Path(tempfile.gettempdir()) / (name or "unified_toolbox_new.exe")
        win = tk.Toplevel(self.root)
        win.title("下载更新")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self.root)
        win.protocol("WM_DELETE_WINDOW", lambda: None)   # 下载中不允许关掉
        enable_dark_title_bar(win)
        status = tk.Label(win, text="正在下载…", bg=BG, fg=TEXT2, font=(FONT_UI, 9))
        status.pack(padx=26, pady=(20, 8))
        bar = ttk.Progressbar(win, mode="determinate", length=320, maximum=100)
        bar.pack(padx=26, pady=(0, 18))
        win.update_idletasks()
        _center_on(win, self.root)

        prog = {"done": 0, "total": 0}
        box = {}

        def _work():
            box["err"] = download_update(
                url, dest, progress=lambda d, t: prog.update(done=d, total=t))

        threading.Thread(target=_work, daemon=True).start()

        def _poll():
            try:
                if not win.winfo_exists():
                    return
            except Exception:
                return
            if "err" not in box:
                done, total = prog["done"], prog["total"]
                if total:
                    bar.config(value=min(100, done * 100 // total))
                    status.config(text=f"正在下载… {done/1024/1024:.1f} / "
                                       f"{total/1024/1024:.1f} MB")
                else:
                    status.config(text=f"正在下载… {done/1024/1024:.1f} MB")
                win.after(150, _poll)
                return
            win.destroy()
            err = box["err"]
            if err:
                show_error("更新失败", err, parent=self.root)
                return
            self._apply_update(dest)
        win.after(150, _poll)

    def _apply_update(self, new_exe):
        """退出前把手交给批处理：等本进程结束 → 覆盖 exe → 重启。"""
        if not getattr(sys, "frozen", False):
            # 源码运行：覆盖 python.exe 毫无意义，直接告诉用户拉代码
            show_info("当前以源码方式运行",
                      "源码运行不需要自更新，直接更新代码即可（如 git pull）。\n\n"
                      f"更新包已下载到：\n{new_exe}", parent=self.root)
            return
        try:
            script = write_update_swapper()
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(["cmd", "/c", str(script), str(new_exe),
                              sys.executable, str(os.getpid())],
                             creationflags=flags)
        except Exception as e:
            show_error("更新失败", f"无法启动替换程序：{e}", parent=self.root)
            return
        self._quit_app()

    def show_settings(self):
        """设置中心：主题 / 开机自启 / 关闭行为 / 热键展示 / 剪贴板缓存清理"""
        if getattr(self, "_settings_win", None) is not None and self._settings_win.winfo_exists():
            self._settings_win.deiconify(); self._settings_win.lift()
            return
        win = tk.Toplevel(self.root)
        self._settings_win = win
        win.title(T("设置中心"))
        win.configure(bg=BG)
        win.transient(self.root)
        enable_dark_title_bar(win)

        # 底部按钮先 pack 到底部，保证任何屏幕高度下「保存/取消」都可见。
        # 旧版把按钮放在最后 pack、窗口又锁死 470x680，而内容实际需要约 962px，
        # 结果是按钮被挤出可视区、既看不到也滚不到。
        btns = tk.Frame(win, bg=BG)
        btns.pack(side="bottom", fill="x", padx=18, pady=(10, 14))

        # 表单区放进可滚动容器：小屏 / 高 DPI 下也能访问到全部分区
        area = _ScrollArea(win, bg=BG)
        area.pack(fill="both", expand=True, padx=(18, 4))
        form = area.inner

        def section(title):
            tk.Label(form, text=T(title), bg=BG, fg=CYAN,
                     font=(FONT_UI, 10, "bold")).pack(anchor="w", pady=(14, 4))

        def card():
            f = tk.Frame(form, bg=PANEL)
            f.pack(fill="x", pady=(0, 2))
            return f

        # ── 主题风格（点选即时预览，保存持久化，取消还原） ──
        section("◈ 主题风格")
        f0 = card()
        # 「取消」要还原到"打开设置中心时"的主题。切换主题会销毁并重建本窗口
        # （_apply_theme_live），所以原主题必须挂在 App 上跨重建保存；否则新窗口的
        # THEME_NAME 已经等于刚才预览的主题，二者恒相等，取消就成了空操作（旧版 bug）。
        saved_theme = getattr(self, "_settings_theme_at_open", None) or THEME_NAME
        self._settings_theme_at_open = saved_theme
        theme_var = tk.StringVar(value=THEME_NAME)
        theme_grid = tk.Frame(f0, bg=PANEL)
        theme_grid.pack(fill="x", padx=12, pady=(6, 4))
        for i, (tkey, tdef) in enumerate(THEMES.items()):
            r, c = divmod(i, 2)
            chip_bg = tdef["BG"] if tdef["dark"] else tdef["PANEL2"]
            swatch = tk.Frame(theme_grid, bg=chip_bg, highlightthickness=1,
                              highlightbackground=tdef["BORDER"])
            swatch.grid(row=r, column=c, padx=(0, 8), pady=3, sticky="nsew")
            theme_grid.grid_columnconfigure((0, 1), weight=1)
            dot = tk.Label(swatch, text="●", bg=chip_bg, fg=tdef["CYAN"],
                           font=(FONT_UI, 9))
            dot.pack(side="left", padx=(8, 3), pady=7)
            sel = tk.Radiobutton(swatch, text=tdef["label"], value=tkey,
                                 variable=theme_var,
                                 bg=chip_bg, fg=tdef["TEXT"], selectcolor=tdef["BG"],
                                 activebackground=chip_bg, activeforeground=tdef["CYAN"],
                                 font=(FONT_UI, 9), bd=0, highlightthickness=0,
                                 cursor="hand2",
                                 command=lambda k=tkey: self._apply_theme_live(k))
            sel.pack(side="left")
            for w in (swatch, dot):
                w.bind("<Double-1>", lambda e, k=tkey: self._apply_theme_live(k))
        tk.Label(f0, text="点选即时预览整窗换肤；「保存」长期生效，「取消」还原原主题",
                 bg=PANEL, fg=TEXT2, font=(FONT_UI, 8)).pack(anchor="w", padx=12, pady=(0, 8))
        # 自定义配色导入/导出
        te_row = tk.Frame(f0, bg=PANEL)
        te_row.pack(fill="x", padx=12, pady=(0, 8))

        def export_theme():
            from tkinter import filedialog
            path = filedialog.asksaveasfilename(
                parent=win, title="导出配色", initialfile="utb_theme.json",
                defaultextension=".json", filetypes=[("JSON", "*.json")])
            if not path:
                return
            try:
                data = dict(THEMES[theme_var.get()] if theme_var.get() in THEMES
                            else THEMES[THEME_NAME])
                Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
                show_info("已导出", f"当前配色已导出到：\n{path}", parent=win)
            except Exception as e:
                show_error("导出失败", str(e), parent=win)

        def import_theme():
            from tkinter import filedialog
            path = filedialog.askopenfilename(
                parent=win, title="导入配色", filetypes=[("JSON", "*.json")])
            if not path:
                return
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8"))
                if not isinstance(data, dict) or any(k not in data for k in _THEME_KEYS):
                    raise ValueError("缺少必要配色字段")
                data["dark"] = bool(data.get("dark", True))
                data.setdefault("label", "🎨 自定义")
                data.setdefault("STRIP", (data["CYAN"], data["BORDER"]))
                THEMES["custom"] = {k: data[k] for k in
                                    list(_THEME_KEYS) + ["dark", "label", "STRIP"] if k in data}
                custom_file = Path.home() / ".unified_toolbox_theme_custom.json"
                custom_file.write_text(json.dumps(THEMES["custom"], ensure_ascii=False, indent=1),
                                       encoding="utf-8")
            except Exception as e:
                show_error("导入失败", f"配色文件无效：\n{e}", parent=win)
                return
            self._apply_theme_live("custom")
            theme_var.set("custom")
            show_info("已导入", "自定义配色已应用，「保存」后长期生效", parent=win)

        tk.Button(te_row, text="⬆ 导出当前配色", bg=PANEL2, fg=TEXT2, font=(FONT_UI, 8),
                  bd=0, relief="flat", cursor="hand2", command=export_theme).pack(side="left")
        tk.Button(te_row, text="⬇ 导入配色文件", bg=PANEL2, fg=CYAN, font=(FONT_UI, 8),
                  bd=0, relief="flat", cursor="hand2", command=import_theme).pack(side="left", padx=(8, 0))

        # ── 开机自启 ──
        section("◈ 常规")
        f1 = card()
        auto_var = tk.BooleanVar(value=get_autostart())
        cb = tk.Checkbutton(f1, text=T("开机自动启动 统一工具箱"), variable=auto_var,
                            bg=PANEL, fg=TEXT, selectcolor=PANEL3, activebackground=PANEL,
                            activeforeground=CYAN, font=(FONT_UI, 10), bd=0,
                            highlightthickness=0, cursor="hand2")
        cb.pack(anchor="w", padx=12, pady=10)
        # 启动时最大化（不想每次手动点最大化就勾上）
        max_var = tk.BooleanVar(value=bool(SETTINGS.get("start_maximized", False)))
        tk.Checkbutton(f1, text="启动时最大化窗口", variable=max_var,
                       bg=PANEL, fg=TEXT, selectcolor=PANEL3, activebackground=PANEL,
                       activeforeground=CYAN, font=(FONT_UI, 10), bd=0,
                       highlightthickness=0, cursor="hand2").pack(
            anchor="w", padx=12, pady=(0, 2))
        tk.Label(f1, text="不勾选也会记住上次退出时的最大化状态（保存后下次启动生效）",
                 bg=PANEL, fg=MUTED, font=(FONT_UI, 8)).pack(anchor="w", padx=12, pady=(0, 8))
        # 界面语言
        lang_row = tk.Frame(f1, bg=PANEL)
        lang_row.pack(anchor="w", padx=12, pady=(0, 10))
        tk.Label(lang_row, text="Language / 语言：", bg=PANEL, fg=TEXT,
                 font=(FONT_UI, 9)).pack(side="left")
        lang_var = tk.StringVar(value=SETTINGS.get("lang", "zh"))
        tk.OptionMenu(lang_row, lang_var, "zh", "en").pack(side="left", padx=(6, 0))
        tk.Label(f1, text="语言切换在重启后完全生效（当前为部分界面翻译）",
                 bg=PANEL, fg=MUTED, font=(FONT_UI, 8)).pack(anchor="w", padx=12, pady=(0, 8))
        hint = tk.Label(f1, text="", bg=PANEL, fg=ORANGE, font=(FONT_UI, 8))
        hint.pack(anchor="w", padx=12, pady=(0, 8))

        # ── 关闭行为 ──
        section("◈ 关闭主窗口时")
        f2 = card()
        close_var = tk.StringVar(value=SETTINGS.get("close_action", "tray"))
        for txt, val in (("最小化到系统托盘（推荐，可从托盘退出）", "tray"),
                         ("直接退出程序", "exit")):
            tk.Radiobutton(f2, text=txt, value=val, variable=close_var,
                           bg=PANEL, fg=TEXT, selectcolor=PANEL3,
                           activebackground=PANEL, activeforeground=CYAN,
                           font=(FONT_UI, 9), bd=0, highlightthickness=0,
                           cursor="hand2").pack(anchor="w", padx=12, pady=3)
        tk.Frame(f2, bg=PANEL, height=6).pack()

        # ── 剪贴板 ──
        section("◈ 剪贴板")
        f3 = card()
        hk = (SETTINGS.get("hotkey_vk", "V") or "V").upper()
        tk.Label(f3, text=f"全局热键：Ctrl + Alt + {hk} 剪贴板面板 · Ctrl + Alt + T 窗口置顶"
                          "（任意程序中生效）",
                 bg=PANEL, fg=TEXT2, font=(FONT_UI, 9)).pack(anchor="w", padx=12, pady=(10, 2))
        size_lbl = tk.Label(f3, text="", bg=PANEL, fg=TEXT2, font=(FONT_UI, 9))
        size_lbl.pack(anchor="w", padx=12, pady=(2, 4))

        def cache_size():
            total = 0
            try:
                if CLIP_IMG_DIR.exists():
                    for f in CLIP_IMG_DIR.iterdir():
                        try: total += f.stat().st_size
                        except OSError: pass
            except OSError:
                pass
            return total

        def refresh_cache_lbl():
            size_lbl.config(text=f"图片缓存目录：{CLIP_IMG_DIR}（{kb(cache_size())}）")
        refresh_cache_lbl()

        def clear_cache():
            # 只删本程序写入的 clip_<hex>.png，不再无差别清空整个缓存目录
            n = purge_clip_image_cache()
            refresh_cache_lbl()
            show_info("已清理", f"已清理 {n} 个缓存图片文件", parent=win)
        tk.Button(f3, text=T("🧹 清理图片缓存"), bg=PANEL2, fg=ORANGE, font=(FONT_UI, 9),
                  bd=0, relief="flat", cursor="hand2",
                  command=clear_cache).pack(anchor="w", padx=12, pady=(2, 10))
        # 隐私：疑似密码/令牌跳过记录 + 退出清空历史
        priv1 = tk.BooleanVar(value=SETTINGS.get("clip_skip_secrets", True))
        priv2 = tk.BooleanVar(value=SETTINGS.get("clip_clear_on_exit", False))
        tk.Checkbutton(f3, text="疑似密码/令牌自动跳过记录（推荐）", variable=priv1,
                       bg=PANEL, fg=TEXT, selectcolor=PANEL3, activebackground=PANEL,
                       activeforeground=CYAN, font=(FONT_UI, 9), bd=0,
                       highlightthickness=0, cursor="hand2").pack(anchor="w", padx=12, pady=2)
        tk.Checkbutton(f3, text="退出时清空剪贴板历史", variable=priv2,
                       bg=PANEL, fg=TEXT, selectcolor=PANEL3, activebackground=PANEL,
                       activeforeground=CYAN, font=(FONT_UI, 9), bd=0,
                       highlightthickness=0, cursor="hand2").pack(anchor="w", padx=12, pady=(2, 6))
        tk.Frame(f3, bg=PANEL, height=6).pack()

        # ── 定时任务 ──
        section("◈ 定时任务")
        f5 = card()
        sch1 = tk.BooleanVar(value=SETTINGS.get("sch_clean_enabled", False))
        sch2 = tk.BooleanVar(value=SETTINGS.get("sch_rest_enabled", False))
        sch1_h = tk.IntVar(value=_as_int(SETTINGS.get("sch_clean_hours"), 168, lo=1, hi=720))
        sch2_m = tk.IntVar(value=_as_int(SETTINGS.get("sch_rest_minutes"), 45, lo=5, hi=240))
        r1 = tk.Frame(f5, bg=PANEL); r1.pack(fill="x", padx=12, pady=3)
        tk.Checkbutton(r1, text="定时清理系统垃圾（静默执行，写审计日志）", variable=sch1,
                       bg=PANEL, fg=TEXT, selectcolor=PANEL3, activebackground=PANEL,
                       activeforeground=CYAN, font=(FONT_UI, 9), bd=0,
                       highlightthickness=0, cursor="hand2").pack(side="left")
        tk.Label(r1, text="每", bg=PANEL, fg=TEXT2, font=(FONT_UI, 9)).pack(side="left", padx=(8, 2))
        tk.Spinbox(r1, from_=1, to=720, width=4, textvariable=sch1_h,
                   bg=PANEL2, fg=TEXT, buttonbackground=PANEL2, relief="flat",
                   insertbackground=TEXT).pack(side="left")
        tk.Label(r1, text="小时", bg=PANEL, fg=TEXT2, font=(FONT_UI, 9)).pack(side="left", padx=(2, 0))
        r2 = tk.Frame(f5, bg=PANEL); r2.pack(fill="x", padx=12, pady=(3, 8))
        tk.Checkbutton(r2, text="休息提醒（护眼）", variable=sch2,
                       bg=PANEL, fg=TEXT, selectcolor=PANEL3, activebackground=PANEL,
                       activeforeground=CYAN, font=(FONT_UI, 9), bd=0,
                       highlightthickness=0, cursor="hand2").pack(side="left")
        tk.Label(r2, text="每", bg=PANEL, fg=TEXT2, font=(FONT_UI, 9)).pack(side="left", padx=(8, 2))
        tk.Spinbox(r2, from_=5, to=240, width=4, textvariable=sch2_m,
                   bg=PANEL2, fg=TEXT, buttonbackground=PANEL2, relief="flat",
                   insertbackground=TEXT).pack(side="left")
        tk.Label(r2, text="分钟", bg=PANEL, fg=TEXT2, font=(FONT_UI, 9)).pack(side="left", padx=(2, 0))

        # ── 关于 / 在线更新 ──
        section("◈ 关于")
        f4 = card()
        tk.Label(f4, text=f"{APP_NAME}  {APP_VERSION}   ·   设置保存在 {SETTINGS_FILE.name}",
                 bg=PANEL, fg=MUTED, font=(FONT_MONO, 8)).pack(anchor="w", padx=12, pady=(8, 4))
        # 在线更新：默认关闭。填了 owner/repo 才会去查 GitHub Release。
        # 刻意做成"手动点按钮才联网"，不后台静默请求。
        up_row = tk.Frame(f4, bg=PANEL)
        up_row.pack(fill="x", padx=12, pady=(0, 2))
        tk.Label(up_row, text="更新源", bg=PANEL, fg=TEXT2,
                 font=(FONT_UI, 9)).pack(side="left")
        repo_var = tk.StringVar(value=(SETTINGS.get("update_repo", "") or "").strip()
                                or UPDATE_REPO_DEFAULT)
        tk.Entry(up_row, textvariable=repo_var, bg=PANEL2, fg=TEXT,
                 font=(FONT_MONO, 9), relief="flat", insertbackground=CYAN,
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=CYAN).pack(side="left", fill="x", expand=True,
                                           padx=(6, 6), ipady=3)
        tk.Button(up_row, text="🔎 检查更新", bg=PANEL2, fg=CYAN, font=(FONT_UI, 9),
                  bd=0, relief="flat", cursor="hand2",
                  command=lambda: self.check_update(repo_var.get())).pack(side="left")
        tk.Label(f4, text="填 owner/repo（如 myname/toolbox）；国内建议填 gitee:owner/repo。"
                          "留空则用内置更新源；只在点按钮时联网",
                 bg=PANEL, fg=MUTED, font=(FONT_UI, 8)).pack(anchor="w", padx=12, pady=(0, 8))

        # ── 底部按钮（btns 已在开头创建并固定到底部） ──
        def _clamp_spin(var, lo, hi, default):
            """Spinbox 被清空/输入非数字时 get() 会抛 TclError，这里统一兜底。"""
            try:
                return _as_int(var.get(), default, lo=lo, hi=hi)
            except Exception:
                return default

        def save():
            err = ""
            if auto_var.get() != get_autostart():
                ok, err = set_autostart(auto_var.get())
                if not ok:
                    hint.config(text=f"自启设置失败：{err}")
            SETTINGS["close_action"] = close_var.get()
            SETTINGS["update_repo"] = repo_var.get().strip()
            SETTINGS["start_maximized"] = max_var.get()
            # 让勾选框双向即时生效，避免和"上次是否最大化"打架：
            # 勾上就现在最大化；取消勾且当前正最大化就还原成窗口态
            try:
                if max_var.get() and self.root.state() != "zoomed":
                    self.root.state("zoomed")
                elif not max_var.get() and self.root.state() == "zoomed":
                    self.root.state("normal")
                    SETTINGS["maximized"] = False
            except Exception:
                pass
            SETTINGS["theme"] = theme_var.get()
            SETTINGS["lang"] = lang_var.get()
            SETTINGS["clip_skip_secrets"] = priv1.get()
            SETTINGS["clip_clear_on_exit"] = priv2.get()
            SETTINGS["sch_clean_enabled"] = sch1.get()
            SETTINGS["sch_clean_hours"] = _clamp_spin(sch1_h, 1, 720, 168)
            SETTINGS["sch_rest_enabled"] = sch2.get()
            SETTINGS["sch_rest_minutes"] = _clamp_spin(sch2_m, 5, 240, 45)
            save_settings()
            self._reset_schedule()
            self._settings_theme_at_open = None
            if not err:
                win.destroy()
                show_info(T("已保存"), T("设置已保存并即时生效"))
        def cancel():
            # 还原为打开设置中心时的主题（预览未保存的切换作废）
            self._settings_theme_at_open = None
            if theme_var.get() != saved_theme:
                self._apply_theme_live(saved_theme)
                theme_var.set(saved_theme)
                return          # _apply_theme_live 会重建本窗口，别再 destroy 旧窗口
            win.destroy()
        tk.Button(btns, text="✔ " + T("保存"), bg=CYAN, fg=BG, font=(FONT_UI, 10, "bold"),
                  bd=0, relief="flat", cursor="hand2", padx=18, pady=3,
                  command=save).pack(side="right")
        tk.Button(btns, text=T("取消"), bg=PANEL2, fg=TEXT2, font=(FONT_UI, 10),
                  bd=0, relief="flat", cursor="hand2", padx=14, pady=3,
                  command=cancel).pack(side="right", padx=(0, 8))
        # 点 X 等同「取消」：否则预览中的主题会残留，且 _settings_theme_at_open 不会清掉
        win.protocol("WM_DELETE_WINDOW", cancel)

        # ── 尺寸：开成"普通窗口"，不再贴着屏幕高度 ──
        # 内容比窗口高时交给 _ScrollArea 的滚动条（保存/取消已固定在底部，始终可见）；
        # 想一次看全的用户直接把窗口拉大即可（可拉伸，宽度下限取内容自然宽度）。
        win.update_idletasks()
        try:
            form_w = form.winfo_reqwidth()
            form_h = form.winfo_reqheight()
            bar_h = btns.winfo_reqheight() + 24
            avail_w = max(380, win.winfo_screenwidth() - 80)
            avail_h = max(320, win.winfo_screenheight() - 140)
            # 常规窗口高度：约屏幕的 2/3，至少给 520，最多不超过屏幕可用高度
            normal_h = min(avail_h, max(520, int(win.winfo_screenheight() * 0.66)))
            width = max(470, min(form_w + 46, avail_w))
            height = min(form_h + bar_h, normal_h)
        except Exception:
            width, height = 470, 680
        win.resizable(True, True)
        # 宽度下限取内容自然宽度，避免把标签挤到横向截断（表单只纵向滚动）
        win.minsize(width, 300)
        win.geometry(f"{width}x{height}")
        win.update_idletasks()
        # 居中于主窗口（越界收敛到屏幕内）
        try:
            x = self.root.winfo_x() + (self.root.winfo_width() - width) // 2
            y = self.root.winfo_y() + (self.root.winfo_height() - height) // 3
            x = max(0, min(x, win.winfo_screenwidth() - width - 8))
            y = max(0, min(y, win.winfo_screenheight() - height - 36))
            win.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _tick_clock(self):
        if self._closing:
            return
        self.clock_lbl.config(text=datetime.datetime.now().strftime("%H:%M:%S"))
        self.root.after(1000, self._tick_clock)

    def _switch(self, name):
        if self._closing:
            return
        if self._page_cleanup:
            self._page_cleanup()
            self._page_cleanup = None
        for m in self.modules.values():
            m.stop()
        for n, btn in self.tab_btns.items():
            btn.config(bg=PANEL2 if n == name else PANEL, fg=CYAN if n == name else TEXT2)
        # 活动页签底部电光蓝指示条
        try:
            if getattr(self, "_tab_ind", None) is None:
                self._tab_ind = tk.Frame(self.tab_frame, bg=CYAN, height=2,
                                         bd=0, highlightthickness=0)
            self._tab_ind.place(in_=self.tab_btns[name], relx=0, rely=1.0,
                                y=-1, relwidth=1.0, anchor="nw")
        except Exception:
            pass
        for w in self.body.winfo_children():
            w.destroy()

        canvas = tk.Canvas(self.body, bg=BG, highlightthickness=0)
        canvas.pack(side="left", fill="both", expand=True)
        # ttk 滚动条（Win 原生 tk.Scrollbar 忽略 bg 配色会渲染成白色，破坏深色主题）
        vsb = ttk.Scrollbar(self.body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y", padx=(0, 4))

        inner = tk.Frame(canvas, bg=BG)
        self._canvas = canvas
        self._inner = inner
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        mod = self.module(name)
        mod.body = inner
        mod.build()
        # Keep propagation enabled so async content can grow AND shrink.
        pending = [None]
        active = [True]
        def layout():
            pending[0] = None
            if not active[0] or self._closing:
                return
            width = max(1, canvas.winfo_width())
            height = max(1, canvas.winfo_height())
            content_height = max(height, inner.winfo_reqheight())
            canvas.itemconfigure(window_id, width=width, height=content_height)
            canvas.configure(scrollregion=(0, 0, width, content_height))
        def schedule(event=None):
            if active[0] and pending[0] is None:
                pending[0] = self.root.after_idle(layout)
        inner_id = inner.bind('<Configure>', schedule, add='+')
        canvas_id = canvas.bind('<Configure>', schedule, add='+')
        def wheel(event):
            if not active[0] or self._closing or not event.delta:
                return
            try:
                cur = self.root.winfo_containing(event.x_root, event.y_root)
                while cur is not None and cur not in (inner, canvas):
                    if cur.winfo_class() in ('Treeview', 'Text', 'Listbox', 'Canvas'):
                        return  # native/nested widget owns its scrolling
                    cur = cur.master
                if cur is None:
                    return
                canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
                return 'break'
            except Exception:
                return
        # Bind only this toplevel; never remove someone else's bind_all.
        wheel_id = self.root.bind('<MouseWheel>', wheel, add='+')
        def cleanup():
            active[0] = False
            if pending[0] is not None:
                try:
                    self.root.after_cancel(pending[0])
                except Exception:
                    pass
                pending[0] = None
            for widget, sequence, ident in ((inner, '<Configure>', inner_id),
                                             (canvas, '<Configure>', canvas_id),
                                             (self.root, '<MouseWheel>', wheel_id)):
                try:
                    widget.unbind(sequence, ident)
                except Exception:
                    pass
        self._page_cleanup = cleanup
        schedule()
        canvas.yview_moveto(0)

        self.current = mod
        mod.start()
        mod.on_show()
        # 切换渐入动画（克制：8步×18ms ≈ 150ms）
        try:
            fade_in(inner)
        except Exception:
            pass

    def _drain_ui_events(self):
        if self._closing:
            return
        actions = {'show': self._show_main, 'quick': self.show_quick_panel,
                   'pin': self.toggle_pin_action, 'settings': self.show_settings,
                   'quit': self._quit_app}
        for _ in range(64):
            try:
                action, value = self._ui_events.get_nowait()
            except queue.Empty:
                break
            try:
                if action == 'tray_ready':
                    self._tray_ready = value is self._tray_icon
                elif action == 'tray_stopped':
                    if value is self._tray_icon:
                        self._tray_ready = False
                        self._tray_icon = None
                        if self.root.state() == 'withdrawn':
                            self._show_main()
                elif action == 'quick':
                    self.show_quick_panel(value)
                elif action in actions:
                    actions[action]()
            except Exception:
                pass
            if self._closing:
                return
        self._event_timer = self.root.after(50, self._drain_ui_events)

    def _validated_geometry(self, value):
        # Validate syntax and constrain to the current virtual desktop.
        match = re.fullmatch(r'(\d{2,5})x(\d{2,5})(?:([+-]\d{1,6})([+-]\d{1,6}))?',
                             value if isinstance(value, str) else '')
        try:
            u32 = ctypes.windll.user32
            left, top, sw, sh = [u32.GetSystemMetrics(i) for i in (76, 77, 78, 79)]
            if sw <= 0 or sh <= 0:
                raise ValueError('No virtual desktop')
        except Exception:
            left, top = 0, 0
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = (int(match[1]), int(match[2])) if match else (1100, 900)
        w, h = max(1100, min(w, sw)), max(500, min(h, sh))
        x, y = (int(match[3] or left), int(match[4] or top)) if match else (left, top)
        x = min(max(x, left), max(left, left + sw - w))
        y = min(max(y, top), max(top, top + sh - h))
        return f'{w}x{h}{x:+d}{y:+d}'

    @staticmethod
    def _target_identity(hwnd):
        try:
            u32 = ctypes.windll.user32
            # HWND is pointer-sized on 64-bit Windows, never truncate it.
            u32.GetForegroundWindow.restype = ctypes.wintypes.HWND
            u32.IsWindow.argtypes = [ctypes.wintypes.HWND]
            u32.SetForegroundWindow.argtypes = [ctypes.wintypes.HWND]
            u32.GetWindowThreadProcessId.argtypes = [ctypes.wintypes.HWND,
                                                    ctypes.POINTER(ctypes.wintypes.DWORD)]
            if not hwnd or not u32.IsWindow(hwnd):
                return None
            pid = ctypes.wintypes.DWORD()
            tid = u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not tid or pid.value == os.getpid():
                return None
            return hwnd, pid.value, tid
        except Exception:
            return None



_SINGLETON_MUTEX = None   # 单实例锁句柄：进程存活期间必须持有


def main():
    # 更新重启时由替换批处理带上：旧实例刚退，互斥锁的释放可能比进程消失晚，
    # 这种情况下对锁做短暂重试，而不是立刻弹「已在运行」
    after_update = "--after-update" in sys.argv[1:]
    # 单实例锁：防止两个实例同时写剪贴板历史/设置互相覆盖。
    # 必须用 use_last_error=True 的 WinDLL 读错误码——ctypes 普通调用会干扰 last-error。
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    global _SINGLETON_MUTEX
    kernel32.OpenMutexW.restype = ctypes.c_void_p
    kernel32.OpenMutexW.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    # 用 OpenMutexW 探测是否已有实例：不依赖 last-error（ctypes 场景下不可靠）
    # 名字可用 UTB_MUTEX_NAME 覆盖（便于自动化测试或多配置并行）
    mutex_name = os.environ.get("UTB_MUTEX_NAME") or "Local\\统一工具箱.Singleton"
    existing = kernel32.OpenMutexW(0x00100000, 0, mutex_name)
    if existing:
        kernel32.CloseHandle(existing)
        freed = False
        if after_update:
            for _ in range(20):          # 最多等 10 秒
                time.sleep(0.5)
                existing = kernel32.OpenMutexW(0x00100000, 0, mutex_name)
                if not existing:
                    freed = True
                    break
                kernel32.CloseHandle(existing)
        if not freed:
            ctypes.windll.user32.MessageBoxW(
                None, "统一工具箱 已经在运行（请检查系统托盘）。",
                "统一工具箱 已在运行", 0x00000040)
            return
    _SINGLETON_MUTEX = kernel32.CreateMutexW(None, 0, mutex_name)
    root = tk.Tk()
    root.geometry("1100x900")
    root.minsize(1100, 500)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
