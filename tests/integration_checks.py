"""Manual integration checks: real module + real Tk where safe. Not part of discovery.

Run: venv\\Scripts\\python.exe tests\\integration_checks.py
Covers lazy module loading, single-instance mutex, page switching, clipboard
capture persistence and OCR. No destructive system operations.
"""
import ctypes
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import tkinter as tk
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "unified" / "unified.py"
results = []


def check(name, fn):
    try:
        detail = fn()
    except Exception as exc:  # noqa: BLE001 - report and continue
        results.append((name, False, f"{type(exc).__name__}: {exc}"))
        print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
    else:
        results.append((name, True, detail or ""))
        print(f"[PASS] {name}: {detail or ''}")


def load_module():
    spec = importlib.util.spec_from_file_location("utb_integration", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def isolate(module, folder):
    """Point every per-user state file at a temp folder, and reset SETTINGS.

    These checks construct a real App, and App._quit_app() -> _save_geometry() ->
    save_settings() writes the live settings file. Without this, simply running
    the checks rewrote the developer's own ~/.unified_toolbox_settings.json and
    reset their remembered window size.
    """
    folder = Path(folder)
    module.SETTINGS_FILE = folder / "settings.json"
    module.HISTORY_FILE = folder / "history.json"
    module.CLIP_IMG_DIR = folder / "cache"
    module.INDEX_FILE = folder / "index.gz"
    module.SNIPPETS_FILE = folder / "snippets.json"
    module.CleanupModule._CLEAN_LOG = folder / "clean_log.txt"
    if isinstance(getattr(module.LaunchModule, "LAUNCH_FILE", None), Path):
        module.LaunchModule.LAUNCH_FILE = folder / "quicklaunch.json"
    module.SETTINGS.clear()
    module.SETTINGS.update(module.DEFAULT_SETTINGS)
    return folder


def lazy_loading():
    module = load_module()
    module.App._setup_tray_and_hotkey = lambda self: None
    module.enable_dark_title_bar = lambda window: None
    with tempfile.TemporaryDirectory() as folder:
        isolate(module, folder)
        root = tk.Tk()
        root.withdraw()
        errors = []
        root.report_callback_exception = lambda *a: errors.append(repr(a[1]))
        app = module.App(root)
        root.withdraw()
        start = set(app.modules)
        total = len(app._module_classes)
        assert start == {"home", "clipboard"}, start
        assert total == 8, total
        app._switch("space")
        assert set(app.modules) == start | {"space"}, set(app.modules)
        app._switch("hardware")
        assert set(app.modules) == start | {"space", "hardware"}, set(app.modules)
        root.after(300, root.quit)
        root.mainloop()
        app._quit_app()
        assert not errors, errors
        return f"startup creates {sorted(start)} of {total}; pages created on demand"


def single_instance():
    # A separate process holds the named mutex while we assert the guard refuses to start.
    # A unique name keeps the check independent from any real running instance.
    mutex_name = "Local\\utb_test_" + uuid.uuid4().hex
    os.environ["UTB_MUTEX_NAME"] = mutex_name
    holder = (
        "import ctypes, os, time\n"
        "k32 = ctypes.WinDLL('kernel32', use_last_error=True)\n"
        "k32.CreateMutexW.restype = ctypes.c_void_p\n"
        "k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]\n"
        "handle = k32.CreateMutexW(None, 0, os.environ['UTB_MUTEX_NAME'])\n"
        "assert handle, 'holder could not create the mutex'\n"
        "print('HELD', flush=True)\n"
        "time.sleep(20)\n"
    )
    env = dict(os.environ, UTB_MUTEX_NAME=mutex_name)
    proc = subprocess.Popen([sys.executable, "-c", holder], stdout=subprocess.PIPE, env=env)
    try:
        assert b"HELD" in proc.stdout.readline(), "holder did not acquire the mutex"
        time.sleep(0.5)
        module = load_module()
        messages, forwarded = [], []
        module.ctypes.windll.user32.MessageBoxW = lambda *a: messages.append(a[1]) or 0
        original_app = module.App
        module.App = lambda *a: forwarded.append(1)
        try:
            module.main()
        finally:
            module.App = original_app
        assert not forwarded, "App must not start while another instance holds the lock"
        assert messages and "已经在运行" in messages[0], messages
        return f"second instance refused; notice={messages[0][:20]}..."
    finally:
        proc.kill()
        proc.wait(timeout=10)
        # PyInstaller/Python may need a moment to release the kernel object.
        time.sleep(0.5)


def clipboard_switch():
    module = load_module()
    module.App._setup_tray_and_hotkey = lambda self: None
    module.enable_dark_title_bar = lambda window: None
    with tempfile.TemporaryDirectory() as folder:
        isolate(module, folder)
        sample = ["initial"]
        module.clip_get_text = lambda: sample[0]
        module.clip_get_dib = lambda: None
        root = tk.Tk()
        root.withdraw()
        errors = []
        root.report_callback_exception = lambda *a: errors.append(repr(a[1]))
        app = module.App(root)
        root.withdraw()
        cm = app.module("clipboard")
        done = []

        def leave():
            app._switch("home")
            sample[0] = "hidden-page-record"

        def verify():
            data = json.loads(module.HISTORY_FILE.read_text(encoding="utf-8"))
            assert any(h["text"] == "hidden-page-record" for h in data), data
            history, worker = cm.history, cm._clip_thread
            app._switch("clipboard")
            assert cm.history is history and cm._clip_thread is worker
            done.append(True)

        root.after(100, lambda: app._switch("clipboard"))
        root.after(500, leave)
        root.after(3000, verify)
        root.after(3600, root.quit)
        root.mainloop()
        app._quit_app()
        assert not errors, errors
        assert done == [True]
        return "capture continues while another page is shown; history preserved"


def ocr_recognition():
    module = load_module()
    from PIL import Image, ImageDraw, ImageFont
    with tempfile.TemporaryDirectory() as folder:
        image = Path(folder) / "sample.png"
        picture = Image.new("RGB", (560, 160), "white")
        draw = ImageDraw.Draw(picture)
        font_path = Path(r"C:\Windows\Fonts\arial.ttf")
        font = ImageFont.truetype(str(font_path), 48) if font_path.exists() else ImageFont.load_default()
        draw.text((24, 50), "HELLO 12345", fill="black", font=font)
        picture.save(image)
        text, err = module.ocr_image_text(image)
        if err:
            raise AssertionError(f"OCR error: {err[:200]}")
        assert "HELLO" in text.upper(), text
        return f"recognised {text!r}"


def dialog_layout():
    """Regression: no dialog may hide its action buttons behind a fixed height.

    Dialogs used to force a geometry smaller than their packed content, so the
    packer silently dropped the trailing action buttons and there was no way to
    scroll to them (settings needed ~962px in a locked 470x680 window).
    """
    module = load_module()
    for name in ("show_info", "show_warning", "show_error", "show_success"):
        setattr(module, name, lambda *a, **k: None)
    module.ask_yesno = lambda *a, **k: False
    module.enable_dark_title_bar = lambda window: None
    module.check_winget = lambda: "v1.0"
    module.App._setup_tray_and_hotkey = lambda self: None
    # 不把 App 的落盘路径留在用户真实配置上：_quit_app -> _save_geometry ->
    # save_settings() 会直接把 ~/.unified_toolbox_settings.json 覆写成默认值
    isolate(module, tempfile.mkdtemp(prefix="utb_check_"))
    root = tk.Tk()
    root.geometry("1100x900+40+20")
    app = module.App(root)
    root.update()

    def settle(times=6):
        for _ in range(times):
            root.update()

    def descendants(win, cls=None):
        found = []

        def walk(w):
            for c in w.winfo_children():
                if cls is None or c.winfo_class() == cls:
                    found.append(c)
                walk(c)

        walk(win)
        return found

    def unreachable(win):
        # A widget the packer could not place is left unmapped (Menu popups are
        # created lazily and legitimately unmapped, so they are excluded).
        lost = []
        for c in descendants(win):
            if not c.winfo_ismapped() and c.winfo_class() != "Menu":
                try:
                    detail = f"{c.winfo_class()}('{c.cget('text')}')"
                except Exception:
                    detail = c.winfo_class()
                lost.append(detail)
        return lost

    def newest():
        wins = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
        assert wins, "dialog did not open"
        return wins[-1]

    checked, problems = [], []
    openers = [
        ("locks", lambda: app.module("space")._locks_dialog()),
        ("restore", lambda: app.module("space")._restore_dialog()),
        ("driver", lambda: app.module("verify")._driver_dialog()),
        ("settings", app.show_settings),
    ]
    for name, opener in openers:
        opener()
        win = app._settings_win if name == "settings" else newest()
        settle()
        lost = unreachable(win)
        if lost:
            problems.append(f"{name}: {len(lost)} unreachable -> {lost[:6]}")
        checked.append(f"{name} {win.winfo_width()}x{win.winfo_height()}")
        if name == "settings":
            # freeze the form: the scrollbar must appear and the buttons stay put
            win.geometry("524x430")
            settle()
            bars = descendants(win, "TScrollbar")
            canvases = descendants(win, "Canvas")
            if not bars or not any(b.winfo_ismapped() for b in bars):
                problems.append("settings(small): no scrollbar -> content unreachable")
            else:
                canvas = canvases[0]
                before = canvas.yview()
                canvas.yview_scroll(6, "units")
                settle(4)
                if canvas.yview() == before:
                    problems.append("settings(small): scrolling had no effect")
            # the 保存 button must still be inside the shrunk window
            save = [b for b in descendants(win, "Button")
                    if "保存" in str(b.cget("text"))]
            if not save:
                problems.append("settings: 保存 button missing")
            elif save[0].winfo_rooty() + save[0].winfo_height() > \
                    win.winfo_rooty() + win.winfo_height():
                problems.append("settings: 保存 button outside the window")
        win.destroy()
        settle(2)

    app._quit_app()
    assert not problems, problems
    return "; ".join(checked)


def window_state():
    """Maximised state must survive a restart.

    _save_geometry used to return early while maximised, so the app never learned
    that the user wanted a maximised window and always reopened at the small
    windowed size (1100x906 on a 1080p screen) — reported as "opens half screen".
    """
    module = load_module()
    module.enable_dark_title_bar = lambda window: None
    module.App._setup_tray_and_hotkey = lambda self: None
    with tempfile.TemporaryDirectory() as folder:
        isolate(module, folder)
        module.SETTINGS_FILE.write_text(json.dumps({
            "geometry": "1100x906+439+0", "maximized": True, "start_maximized": False,
        }), encoding="utf-8")
        module.load_settings()
        root = tk.Tk()
        root.geometry("1100x900")
        app = module.App(root)
        for _ in range(12):
            root.update()
        state = root.state()
        assert state == "zoomed", f"maximised state not restored, got {state!r}"
        app._save_geometry()
        saved = json.loads(module.SETTINGS_FILE.read_text(encoding="utf-8"))
        assert saved.get("geometry") == "1100x906+439+0", saved
        assert saved.get("maximized") is True, saved
        app._quit_app()
        return (f"reopened {state}; windowed geometry kept as {saved['geometry']}")


def main():
    check("lazy module loading", lazy_loading)
    check("single instance mutex", single_instance)
    check("clipboard capture on hidden page", clipboard_switch)
    check("OCR recognition", ocr_recognition)
    check("dialog layout keeps buttons reachable", dialog_layout)
    check("window state survives restart", window_state)
    failed = [name for name, ok, _ in results if not ok]
    print("\nSUMMARY:", f"{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
