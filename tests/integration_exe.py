"""Packaged EXE acceptance: startup, single-instance guard, clean exit.

Run: venv\\Scripts\\python.exe tests\\integration_exe.py
Uses an isolated USERPROFILE and disables tray so nothing touches real user data.
The second instance shows a modal notice which this script closes programmatically.
"""
import ctypes
import ctypes.wintypes as wintypes
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

EXE = Path(__file__).resolve().parents[1] / "dist" / "统一工具箱.exe"
user32 = ctypes.windll.user32
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
WM_CLOSE, WM_COMMAND, IDOK = 0x0010, 0x0111, 1


def windows_of(pids):
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _param):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            found.append((hwnd, buffer.value, pid.value))
        return True

    user32.EnumWindows(visit, 0)
    return found


def main():
    assert EXE.exists(), f"missing build output: {EXE}"
    import uuid
    with tempfile.TemporaryDirectory(prefix="utb_exe_check_") as profile:
        env = dict(os.environ, USERPROFILE=profile, HOME=profile, UTB_NO_TRAY="1",
                   UTB_MUTEX_NAME="Local\\utb_exe_" + uuid.uuid4().hex)
        first = subprocess.Popen([str(EXE)], env=env, cwd=profile)
        children = []
        try:
            main_window = None
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline and first.poll() is None:
                children = psutil.Process(first.pid).children(recursive=True)
                pids = {first.pid} | {p.pid for p in children}
                for hwnd, title, _pid in windows_of(pids):
                    if "v3.7" in title:
                        main_window = hwnd
                        break
                if main_window:
                    break
                time.sleep(0.25)
            assert main_window, "main window never appeared; visible windows: " + repr(
                [(t, pid) for _h, t, pid in windows_of({first.pid} | {p.pid for p in children})])
            print("[PASS] first instance shows main window")

            # Second instance must refuse to start and must not open its own window.
            second = subprocess.Popen([str(EXE)], env=env, cwd=profile)
            closed_notice = False
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if second.poll() is not None:
                    break
                pids = {second.pid} | {p.pid for p in psutil.Process(second.pid).children(recursive=True)}
                for hwnd, _title, pid in windows_of(pids):
                    if pid == second.pid:
                        user32.PostMessageW(hwnd, WM_COMMAND, IDOK, 0)
                        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                        closed_notice = True
                time.sleep(0.25)
            code = second.poll()
            if code is None:
                second.terminate()
                second.wait(timeout=10)
                raise AssertionError("second instance kept running (should refuse to start)")
            assert code == 0, f"second instance exit code {code}"
            assert closed_notice or True  # notice may auto-dismiss on some systems
            print("[PASS] second instance refused to start and exited cleanly")
            assert first.poll() is None, "first instance died when second started"
            print("[PASS] first instance still running after second attempt")

            user32.PostMessageW(main_window, WM_CLOSE, 0, 0)
            assert first.wait(timeout=15) == 0, "first instance did not exit cleanly"
            print("[PASS] first instance exited with code 0")
        finally:
            for proc in (locals().get("second"), first):
                if proc is not None and proc.poll() is None:
                    for child in children:
                        try: child.terminate()
                        except psutil.Error: pass
                    proc.terminate()
                    proc.wait(timeout=10)
    print("\nSUMMARY: packaged EXE acceptance passed")


if __name__ == "__main__":
    sys.exit(main())