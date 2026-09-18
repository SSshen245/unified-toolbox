# -*- coding: utf-8 -*-
"""一键发版：跑测试 → 提交 → 打 tag → 打包 exe → 生成交付包。

用法：
    双击 发版.cmd
    或  venv\\Scripts\\python.exe 发版.py ["提交说明"]

产物全部落在 dist\\ ：
    统一工具箱.exe            给最终用户（双击即用，不需要 Python / git）
    统一工具箱-源码.zip        给开发者（只含受跟踪文件，不含 .git）
    统一工具箱.bundle         给开发者（单个文件装下完整 git 历史，可 clone）

选项：
    --no-tests    跳过单元测试
    --no-commit   工作区脏时直接报错退出，不自动提交
    --no-build    只提交 + 打 tag，不打包（改完想先提交、稍后再发版时用）
"""
import hashlib
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

# 控制台可能是 cp936：保留原编码但不要因为个别字符编码失败而崩
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass


def say(msg=""):
    print(msg, flush=True)


def run(cmd, check=True, capture=True):
    """跑一条命令，返回 (returncode, stdout)。"""
    r = subprocess.run(cmd, capture_output=capture, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        say(f"\n[失败] 命令返回 {r.returncode}: {' '.join(map(str, cmd))}")
        if r.stdout:
            say(r.stdout.strip()[-1500:])
        if r.stderr:
            say(r.stderr.strip()[-1500:])
        raise SystemExit(1)
    return r.returncode, (r.stdout or "")


def git(*args, check=True):
    return run(["git", *args], check=check)


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def md5_of(path):
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_version():
    text = (ROOT / "unified" / "unified.py").read_text(encoding="utf-8")
    m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', text, re.M)
    if not m:
        say("[失败] 在 unified/unified.py 里找不到 APP_VERSION")
        raise SystemExit(1)
    return m.group(1)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    message = args[0] if args else ""

    say("=" * 64)
    say("  统一工具箱 · 一键发版")
    say("=" * 64)

    # ── 0. 环境自检 ──
    if not (ROOT / ".git").is_dir():
        say("[失败] 当前目录不是 git 仓库")
        raise SystemExit(1)
    if not (ROOT / "unified" / "unified.py").exists():
        say("[失败] 找不到 unified/unified.py，请把本脚本放在项目根目录")
        raise SystemExit(1)

    version = read_version()
    say(f"项目版本：{version}")

    # ── 1. 单元测试（失败就别打包了）──
    if "--no-tests" in flags:
        say("[1/5] 跳过单元测试（--no-tests）")
    else:
        say("[1/5] 运行单元测试…")
        # 注意：unittest 把汇总写到 stderr，所以两个流都要看；判定用退出码最可靠
        r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        combined = (r.stdout or "") + (r.stderr or "")
        for line in [l for l in combined.strip().splitlines() if l.strip()][-3:]:
            say("      " + line)
        if r.returncode != 0:
            say("[失败] 单元测试没通过，已中止发版")
            raise SystemExit(1)

    # ── 2. 提交 ──
    _, status = git("status", "--porcelain")
    dirty = bool(status.strip())
    if not dirty:
        say("[2/5] 工作区干净，无需提交")
    elif "--no-commit" in flags:
        say("[2/5] 工作区有未提交改动，且指定了 --no-commit，已中止")
        say(status.strip())
        raise SystemExit(1)
    else:
        if not message:
            say("[2/5] 工作区有未提交改动：")
            for line in status.strip().splitlines()[:15]:
                say("      " + line)
            try:
                message = input("\n      请输入本次提交说明（直接回车用默认）: ").strip()
            except EOFError:
                message = ""
        if not message:
            message = f"发版 {version}"
        git("add", "-A")
        git("commit", "-m", message)
        _, sha = git("rev-parse", "--short", "HEAD")
        say(f"[2/5] 已提交 {sha.strip()}：{message}")

    _, head = git("rev-parse", "--short", "HEAD")
    head = head.strip()

    # ── 3. 打 tag ──
    tag = version
    exists, _ = git("tag", "-l", tag)
    if exists.strip():
        # 同一个版本号重复发版：加时间戳，避免覆盖已有 tag
        tag = f"{version}-build.{time.strftime('%Y%m%d-%H%M')}"
        say(f"      提示：tag {version} 已存在（建议在 unified.py 里递增 APP_VERSION）")
    git("tag", "-a", tag, "-m", f"发版 {tag}")
    say(f"[3/5] 已打 tag：{tag}")

    if "--no-build" in flags:
        say("[4/5] 跳过打包（--no-build）")
        say("[5/5] 跳过生成交付包（--no-build）")
        say("\n完成（仅提交与打 tag）。")
        return

    # ── 4. 打包 exe ──
    say("[4/5] PyInstaller 打包中（约 25~35 秒）…")
    run([sys.executable, "-m", "PyInstaller", "统一工具箱.spec",
         "--noconfirm", "--distpath", "dist", "--workpath", "build"],
        capture=False)
    exe = ROOT / "dist" / "统一工具箱.exe"
    if not exe.exists():
        say("[失败] 打包结束但没找到 dist\\统一工具箱.exe")
        raise SystemExit(1)
    say(f"      dist\\统一工具箱.exe  {human(exe.stat().st_size)}  md5={md5_of(exe)[:12]}")

    # ── 5. 生成交付包（内容来自已提交的 HEAD，所以先提交再打包）──
    say("[5/5] 生成交付包…")
    zip_path = ROOT / "dist" / "统一工具箱-源码.zip"
    git("archive", "--format=zip", "-o", str(zip_path), "HEAD")
    bundle_path = ROOT / "dist" / "统一工具箱.bundle"
    git("bundle", "create", str(bundle_path), "--all")

    say()
    say("=" * 64)
    say(f"  发版完成 · {tag} · 提交 {head}")
    say("=" * 64)
    say()
    say("dist\\ 里现在有三样东西：")
    say(f"  统一工具箱.exe          {human(exe.stat().st_size):>9}   给用户，双击即用")
    say(f"  统一工具箱-源码.zip      {human(zip_path.stat().st_size):>9}   给开发者，无 .git")
    say(f"  统一工具箱.bundle       {human(bundle_path.stat().st_size):>9}   给开发者，含完整历史")
    say()
    say("发给最终用户：只需要 exe（可再带上 使用说明.txt），对方不需要 Python 或 git。")
    say("发给开发者：  发 bundle；对方 git clone 统一工具箱.bundle 目录名")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        say("\n已取消。")
        raise SystemExit(130)
