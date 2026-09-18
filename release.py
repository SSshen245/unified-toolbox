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
    --no-publish  不发布到 GitHub（默认装了 gh 且已登录就会自动发布）
"""
import hashlib
import os
import re
import shutil
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


def next_version(v):
    """算出下一个建议版本号："v3.7" -> "v3.8"，"v3.7.1" -> "v3.7.2"。"""
    m = re.match(r"^(v?)(\d+)(?:\.(\d+))?(?:\.(\d+))?$", str(v).strip())
    if not m:
        return str(v) + ".1"
    pre, major = m.group(1) or "", int(m.group(2))
    minor, patch = m.group(3), m.group(4)
    if patch is not None:
        return f"{pre}{major}.{minor}.{int(patch) + 1}"
    if minor is not None:
        return f"{pre}{major}.{int(minor) + 1}"
    return f"{pre}{major + 1}"


# 发布到 GitHub 时用的附件名，必须是纯 ASCII：
# gh 拿中文文件名当附件名会退化成 default.exe（实测踩过），
# 而且中文名在下载 URL 里会被百分号编码。
GH_ASSET_NAME = "UnifiedToolbox.exe"


def find_gh():
    """找 gh CLI：先看 PATH，再看本机便携安装位置。"""
    for cand in ("gh", "gh.exe"):
        found = shutil.which(cand)
        if found:
            return found
    extra = Path.home() / ".workbuddy" / "binaries" / "gh" / "bin" / "gh.exe"
    return str(extra) if extra.exists() else None


def origin_slug():
    """从 origin 远端解析出 owner/repo。"""
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:
        return None
    m = re.search(r"github\.com[:/]+([^/]+)/([^/\s]+?)(?:\.git)?/?$", url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def publish_to_github(tag, exe, notes_path, say):
    """把 exe 作为附件发布到 GitHub Release。返回 True/False。

    gh 需要能访问 github.com / uploads.github.com；本机 git 若配了代理，
    一并传给 gh（gh 不读 git 的 http.proxy，只认环境变量）。
    """
    gh = find_gh()
    if not gh:
        say("      跳过：没找到 gh CLI（装了 GitHub CLI 后可自动发布）")
        return False
    env = dict(os.environ)
    try:
        proxy = subprocess.run(["git", "config", "--get", "https.proxy"],
                               capture_output=True, text=True, timeout=10).stdout.strip()
        if proxy:
            env.setdefault("HTTPS_PROXY", proxy)
            env.setdefault("HTTP_PROXY", proxy)
    except Exception:
        pass

    slug = origin_slug()
    if not slug:
        say("      跳过：origin 不是 GitHub 仓库")
        return False

    # 先把代码推上去，否则 gh release create --target main 会把 tag 打在
    # 远端的旧提交上，发布的 exe 和仓库代码对不上。
    say("      推送代码到 GitHub…")
    try:
        git("push", "origin", "main")
        existing = subprocess.run(["git", "ls-remote", "--tags", "origin", tag],
                                  capture_output=True, text=True).stdout.strip()
        if existing:
            say(f"      tag {tag} 远端已存在，跳过推送")
        else:
            git("push", "origin", tag)
    except Exception as e:
        say(f"      发布中止：推送失败（{e}）")
        say("      网络通后再跑一次即可；代码没推上去不能发 Release，")
        say("      否则 --target main 会把 tag 打在远端旧提交上，exe 与源码对不上。")
        return False

    # 用 ASCII 名的副本上传（本地文件名保持中文不动）
    ascii_exe = exe.with_name(GH_ASSET_NAME)
    try:
        shutil.copy2(exe, ascii_exe)
    except Exception as e:
        say(f"      跳过：准备附件失败 {e}")
        return False
    try:
        exists = subprocess.run([gh, "release", "view", tag], env=env,
                                capture_output=True, text=True).returncode == 0
        if exists:
            cmd = [gh, "release", "upload", tag, str(ascii_exe), "--clobber"]
        else:
            cmd = [gh, "release", "create", tag, str(ascii_exe),
                   "--title", tag, "--target", "main", "--generate-notes"]
            if notes_path and Path(notes_path).exists():
                cmd += ["--notes-file", str(notes_path)]
        r = subprocess.run(cmd, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            say(f"      发布失败：{(r.stderr or r.stdout or '').strip()[:400]}")
            return False
        say(f"      已发布到 https://github.com/{slug}/releases/tag/{tag}")
        return True
    finally:
        ascii_exe.unlink(missing_ok=True)


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
    notes_file = None          # None = 用 gh --generate-notes 从提交自动生成
    say(f"项目版本：{version}")

    # ── 1. 单元测试（失败就别打包了）──
    if "--no-tests" in flags:
        say("[1/6] 跳过单元测试（--no-tests）")
    else:
        say("[1/6] 运行单元测试…")
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
        say("[2/6] 工作区干净，无需提交")
    elif "--no-commit" in flags:
        say("[2/6] 工作区有未提交改动，且指定了 --no-commit，已中止")
        say(status.strip())
        raise SystemExit(1)
    else:
        if not message:
            say("[2/6] 工作区有未提交改动：")
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
        say(f"[2/6] 已提交 {sha.strip()}：{message}")

    _, head = git("rev-parse", "--short", "HEAD")
    head = head.strip()

    # ── 3. 打 tag ──
    tag = version
    # run()/git() 返回的是 (returncode, stdout)，这里要的是 stdout
    _, existing_tags = git("tag", "-l", tag)
    if existing_tags.strip():
        # 同一个版本号重复发版：加时间戳，避免覆盖已有 tag
        tag = f"{version}-build.{time.strftime('%Y%m%d-%H%M')}"
        say(f"      注意：tag {version} 已存在，本次改用 {tag}")
        say(f"      建议：把 unified.py 里的 APP_VERSION 递增为 {next_version(version)} 再发版。")
        say("            在线更新的版本比较依赖这个号——重复发同一个号，")
        say("            老用户点「检查更新」会一直提示「已是最新版本」，收不到新包。")
    git("tag", "-a", tag, "-m", f"发版 {tag}")
    say(f"[3/6] 已打 tag：{tag}")

    if "--no-build" in flags:
        say("[4/6] 跳过打包（--no-build）")
        say("[5/6] 跳过生成交付包（--no-build）")
        say("\n完成（仅提交与打 tag）。")
        return

    # ── 4. 打包 exe ──
    say("[4/6] PyInstaller 打包中（约 25~35 秒，请稍候）…")
    # --log-level WARN：默认 INFO 会刷满整屏，双击运行时更该只看到关键信息
    r = subprocess.run([sys.executable, "-m", "PyInstaller", "统一工具箱.spec",
                        "--noconfirm", "--distpath", "dist", "--workpath", "build",
                        "--log-level", "WARN"],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        say("[失败] 打包失败：")
        for stream in (r.stdout, r.stderr):
            if stream and stream.strip():
                say(stream.strip()[-2000:])
        raise SystemExit(1)
    noise = [l for l in ((r.stdout or "") + (r.stderr or "")).splitlines() if l.strip()]
    for line in noise[-5:]:
        say("      " + line)
    exe = ROOT / "dist" / "统一工具箱.exe"
    if not exe.exists():
        say("[失败] 打包结束但没找到 dist\\统一工具箱.exe")
        raise SystemExit(1)
    say(f"      dist\\统一工具箱.exe  {human(exe.stat().st_size)}  md5={md5_of(exe)[:12]}")

    # ── 5. 生成交付包（内容来自已提交的 HEAD，所以先提交再打包）──
    say("[5/6] 生成交付包…")
    zip_path = ROOT / "dist" / "统一工具箱-源码.zip"
    git("archive", "--format=zip", "-o", str(zip_path), "HEAD")
    bundle_path = ROOT / "dist" / "统一工具箱.bundle"
    git("bundle", "create", str(bundle_path), "--all")

    # ── 6. 发布到 GitHub（装了 gh 且已登录就自动做）──
    published = False
    if "--no-publish" in flags:
        say("[6/6] 跳过发布（--no-publish）")
    else:
        say("[6/6] 发布到 GitHub Release…")
        published = publish_to_github(tag, exe, notes_file, say)

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
    if published:
        say("已发布到 GitHub Release；用户可用应用里的「检查更新」拿到新版。")
    else:
        say("未发布到 GitHub —— 用户暂时拿不到「检查更新」。")
        say("  · 装了 GitHub CLI 并 gh auth login 之后，再跑一次即可自动发布")
        say("  · 或手动：把 dist\\统一工具箱.exe 拖到 GitHub 的 Release 页面")
    say()
    say("发给最终用户：只需要 exe（可再带上 使用说明.txt），对方不需要 Python 或 git。")
    say("发给开发者：  发 bundle；对方 git clone 统一工具箱.bundle 目录名")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        say("\n已取消。")
        raise SystemExit(130)
