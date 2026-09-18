"""Regression tests for the defects found in the functionality audit.

Pure-function / filesystem level: no Tk window is created, so these run in the
normal `unittest discover -s tests` sweep.
"""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "unified" / "unified.py"

_spec = importlib.util.spec_from_file_location("utb_regression", SOURCE)
MODULE = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MODULE)


class ElevatedLogEncodingTests(unittest.TestCase):
    """`Out-File -Encoding unicode` writes UTF-16LE+BOM; reading it as gbk kept the
    NUL bytes so CREATED=/COUNT=/RP: never matched -> restore points were dead."""

    def _roundtrip(self, text, encoding, bom=b""):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "log.txt"
            p.write_bytes(bom + text.encode(encoding))
            return MODULE._read_elevated_log(p)

    def test_utf16_lines_are_readable(self):
        text = "CREATED=3-2\r\nRP: 2026/9/18 7:00:00\r\nCOUNT=3\r\n"
        out = self._roundtrip(text, "utf-16-le", b"\xff\xfe")
        lines = out.splitlines()
        self.assertTrue(any(l.startswith("CREATED=") for l in lines), lines)
        self.assertTrue(any(l.startswith("COUNT=") for l in lines), lines)
        self.assertEqual(sum(1 for l in lines if l.startswith("RP: ")), 1, lines)

    def test_big_endian_bom(self):
        out = self._roundtrip("COUNT=7\r\n", "utf-16-be", b"\xfe\xff")
        self.assertIn("COUNT=7", out)

    def test_utf8_sig_bom(self):
        out = self._roundtrip("COUNT=9\r\n", "utf-8", b"\xef\xbb\xbf")
        self.assertIn("COUNT=9", out)

    def test_plain_gbk_still_readable(self):
        out = self._roundtrip("COUNT=1\r\n", "gbk")
        self.assertIn("COUNT=1", out)

    def test_missing_file_is_empty(self):
        self.assertEqual(MODULE._read_elevated_log(Path("Z:/nope/missing.txt")), "")


class IndexSkipTests(unittest.TestCase):
    """skip_prefixes were never passed AND were matched with startswith against an
    absolute path, so nothing was ever skipped."""

    FRAGMENTS = ("\\Windows\\WinSxS", "\\Windows\\Installer", "$Recycle.Bin",
                 "node_modules", "__pycache__", "\\AppData\\Local\\Temp",
                 "\\AppData\\Local\\Microsoft", "\\AppData\\Local\\Packages")

    def _skips(self):
        return [tuple(p.lower() for p in f.split("\\") if p)
                for f in self.FRAGMENTS]

    def test_skipped_paths(self):
        for path in (r"C:\Windows\WinSxS\amd64\x.dll",
                     r"C:\Windows\Installer\a.msi",
                     r"D:\$Recycle.Bin\S-1-5-21",
                     r"D:\proj\web\node_modules\react\index.js",
                     r"D:\proj\__pycache__\x.pyc",
                     r"C:\Users\me\AppData\Local\Temp\a.tmp",
                     r"C:\Users\me\AppData\Local\Packages\App\x"):
            self.assertTrue(MODULE._path_has_segments(path.lower(), self._skips()),
                            f"{path} should be skipped")

    def test_normal_paths_survive(self):
        for path in (r"C:\Windows\System32\drivers\etc\hosts",
                     r"D:\work\temp\notes.txt",
                     r"D:\work\microsoft\doc.txt",
                     r"D:\work\AppData\Roaming\x",
                     r"D:\code\node_modules_like\x"):
            self.assertFalse(MODULE._path_has_segments(path.lower(), self._skips()),
                             f"{path} must NOT be skipped")

    def test_build_file_index_honours_skip_prefixes(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / "keep").mkdir()
            (base / "keep" / "a.txt").write_text("x", encoding="utf-8")
            (base / "node_modules").mkdir()
            (base / "node_modules" / "junk.txt").write_text("x", encoding="utf-8")
            (base / "__pycache__").mkdir()
            (base / "__pycache__" / "j.pyc").write_text("x", encoding="utf-8")

            plain = MODULE.build_file_index([str(base)])
            skipped = MODULE.build_file_index([str(base)],
                                              skip_prefixes=("node_modules", "__pycache__"))

            self.assertTrue(any("node_modules" in e for e in plain), plain)
            self.assertFalse(any("node_modules" in e for e in skipped), skipped)
            self.assertFalse(any("__pycache__" in e for e in skipped), skipped)
            self.assertTrue(any(e.endswith("a.txt") for e in skipped), skipped)


class DiskHealthMappingTests(unittest.TestCase):
    """SMART rows are per physical disk but volumes were matched by index, so a
    second volume showed another disk's health (or nothing)."""

    def setUp(self):
        self.health = [{"name": "Disk0", "health": "Healthy", "letters": "C,D"},
                       {"name": "Disk1", "health": "Warning", "letters": "E"}]

    def test_match_by_drive_letter(self):
        self.assertEqual(MODULE._health_for_mount(self.health, "C:\\")["name"], "Disk0")
        self.assertEqual(MODULE._health_for_mount(self.health, "D:\\")["name"], "Disk0")
        self.assertEqual(MODULE._health_for_mount(self.health, "E:\\")["name"], "Disk1")

    def test_the_old_index_bug_case(self):
        # one physical disk, two volumes: old code asked for health[1] -> None,
        # or on a 2-disk machine -> the *other* disk's health
        one = [{"name": "OnlyDisk", "health": "Healthy", "letters": "C,D"}]
        self.assertEqual(MODULE._health_for_mount(one, "D:\\", 1, 2)["name"], "OnlyDisk")

    def test_unknown_letter_is_not_guessed(self):
        self.assertIsNone(MODULE._health_for_mount(self.health, "Z:\\"))
        self.assertIsNone(MODULE._health_for_mount(self.health, None))

    def test_index_fallback_only_when_1to1(self):
        no_letters = [{"name": "A", "letters": ""}, {"name": "B", "letters": ""}]
        # 2 volumes / 2 disks -> unambiguous, fallback allowed
        self.assertEqual(MODULE._health_for_mount(no_letters, "C:\\", 1, 2)["name"], "B")
        # 2 volumes / 1 disk -> ambiguous, must NOT guess
        self.assertIsNone(MODULE._health_for_mount(no_letters[:1], "D:\\", 1, 2))


class ProcessNameGuardTests(unittest.TestCase):
    def test_case_insensitive_and_unknown(self):
        self.assertTrue(MODULE._same_proc_name("chrome.exe", "CHROME.EXE"))
        self.assertTrue(MODULE._same_proc_name("", "chrome.exe"))
        self.assertTrue(MODULE._same_proc_name("chrome.exe", "?"))
        self.assertFalse(MODULE._same_proc_name("explorer.exe", "chrome.exe"))


class RenameEngineTests(unittest.TestCase):
    def _plan(self, names, **rules):
        base = dict(prefix="", suffix="", find="", repl="", use_regex=False,
                    seq_start=1, seq_digits=2, seq_pos="none", case="keep",
                    keep_ext=True)
        base.update(rules)
        return MODULE.plan_rename(names, existing={n.lower() for n in names}, **base)

    def _pairs(self, plan):
        return [(o, n) for o, n, e in plan if not e and o != n]

    def test_case_only_rename_works(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "readme.md").write_text("x", encoding="utf-8")
            names = sorted(os.listdir(folder))
            done, failed, _ = MODULE.apply_rename(folder, self._pairs(self._plan(names, case="upper")))
            self.assertEqual((done, failed), (1, []))
            # keep_ext=True keeps the extension, only the stem is re-cased
            self.assertEqual(os.listdir(folder), ["README.md"])

    def test_apply_then_undo_round_trips(self):
        with tempfile.TemporaryDirectory() as folder:
            for n in ("a.txt", "b.txt"):
                Path(folder, n).write_text("x", encoding="utf-8")
            names = sorted(os.listdir(folder))
            done, _, record = MODULE.apply_rename(
                folder, self._pairs(self._plan(names, prefix="new_")))
            self.assertEqual(done, 2)
            MODULE.undo_rename(folder, record)
            self.assertEqual(sorted(os.listdir(folder)), ["a.txt", "b.txt"])

    def test_undo_record_is_names_only_so_callers_must_pin_the_folder(self):
        """Documents why the dialog now stores the folder alongside the record:
        the record alone is ambiguous across directories."""
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            Path(a, "a.txt").write_text("A", encoding="utf-8")
            Path(b, "RENAMED_a.txt").write_text("B-important", encoding="utf-8")
            _, _, record = MODULE.apply_rename(a, self._pairs(self._plan(["a.txt"], prefix="RENAMED_")))
            self.assertEqual(record, [("RENAMED_a.txt", "a.txt")])
            # running the record against the wrong folder renames an unrelated file
            ok, _ = MODULE.undo_rename(b, record)
            self.assertEqual(ok, 1)
            self.assertEqual(sorted(os.listdir(b)), ["a.txt"])


class ImageCachePurgeTests(unittest.TestCase):
    def test_only_own_clip_files_are_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            original = MODULE.CLIP_IMG_DIR
            MODULE.CLIP_IMG_DIR = Path(folder)
            try:
                mine = Path(folder, "clip_" + "a" * 32 + ".png")
                mine.write_bytes(b"x")
                other = Path(folder, "notes.txt")
                other.write_text("keep me", encoding="utf-8")
                short = Path(folder, "clip_abc.png")
                short.write_bytes(b"x")
                self.assertEqual(MODULE.purge_clip_image_cache(), 1)
                self.assertFalse(mine.exists())
                self.assertTrue(other.exists(), "unrelated file must survive")
                self.assertTrue(short.exists(), "non-matching clip name must survive")
            finally:
                MODULE.CLIP_IMG_DIR = original

    def test_missing_dir_is_not_an_error(self):
        original = MODULE.CLIP_IMG_DIR
        MODULE.CLIP_IMG_DIR = Path("Z:/definitely/not/here")
        try:
            self.assertEqual(MODULE.purge_clip_image_cache(), 0)
        finally:
            MODULE.CLIP_IMG_DIR = original


class SafeIntTests(unittest.TestCase):
    """A hand-edited settings file with null/garbage used to raise inside the 30s
    scheduler callback, permanently killing the scheduled-task timer."""

    def test_bad_values_fall_back_to_default(self):
        for bad in (None, "", "abc", "12x", [], {}, object()):
            self.assertEqual(MODULE._as_int(bad, 168), 168, f"value={bad!r}")

    def test_numeric_strings_and_floats(self):
        self.assertEqual(MODULE._as_int("45", 1), 45)
        self.assertEqual(MODULE._as_int("45.9", 1), 45)
        self.assertEqual(MODULE._as_int(45.9, 1), 45)

    def test_clamping(self):
        self.assertEqual(MODULE._as_int(0, 168, lo=1), 1)
        self.assertEqual(MODULE._as_int(999, 1, hi=720), 720)
        self.assertEqual(MODULE._as_int(50, 1, lo=5, hi=240), 50)


class UpdateCheckTests(unittest.TestCase):
    """Online update: version compare, ASCII-only constraints, offline safety."""

    def test_version_ordering(self):
        cases = [("v3.7", "v3.8", True), ("v3.7", "v3.10", True),
                 ("v3.10", "v3.9", False), ("v3.7", "3.7", False),
                 ("V3.7", "v3.7.1", True), ("v3.7", "v3.7", False),
                 ("v3.99", "v4", True), ("v3.7", "", False)]
        for current, latest, newer in cases:
            self.assertEqual(
                MODULE.version_key(latest) > MODULE.version_key(current), newer,
                f"{latest!r} should{' ' if newer else ' not '}be newer than {current!r}")

    def test_github_rate_limit_falls_back_to_gitee(self):
        """GitHub 403 时自动改查备用源（gitee:），不能把限流直接甩给用户。"""
        import json as _json
        import time as _time
        import urllib.error
        import urllib.request

        calls = []

        class Fake403(urllib.error.HTTPError):
            def __init__(self):
                super().__init__("https://api.github.com/x", 403, "rate limited",
                                 {"X-RateLimit-Reset": str(int(_time.time()) + 600)},
                                 None)

        class FakeResp:
            def __init__(self, payload):
                self._p = _json.dumps(payload).encode()

            def read(self):
                return self._p

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            host = req.full_url.split("/")[2]
            calls.append(host)
            if "github" in host:
                raise Fake403()
            return FakeResp({"tag_name": "v9.9", "assets": [
                {"name": "UnifiedToolbox.exe",
                 "browser_download_url": "https://gitee.com/o/r/releases/download/v9.9/UnifiedToolbox.exe"}]})

        with patch.object(MODULE.urllib.request, "urlopen", side_effect=fake_urlopen):
            tag, url, name, err = MODULE.fetch_latest_release(
                "SSshen245/unified-toolbox", use_cache=False)
        self.assertIn("api.github.com", calls)
        self.assertIn("gitee.com", calls)          # 兜底真的发生了
        self.assertEqual(tag, "v9.9")              # 拿到的是备用源的结果
        self.assertIn("gitee.com", (url or ""))
        self.assertIsNone(err)

    def test_gitee_source_never_falls_back_to_itself(self):
        """更新源本身就是 gitee: 时不能再兜底（会无限循环）。"""
        import urllib.error

        class Fake404(urllib.error.HTTPError):
            def __init__(self):
                super().__init__("https://gitee.com/x", 404, "nf", {}, None)

        with patch.object(MODULE.urllib.request, "urlopen",
                          side_effect=Fake404()):
            tag, url, name, err = MODULE.fetch_latest_release(
                "gitee:SSshen245/unified-toolbox", use_cache=False)
        self.assertIsNone(tag)
        self.assertIn("找不到仓库", err)

    def test_swapper_is_pure_ascii(self):
        """cmd.exe reads a .cmd using the OEM codepage; one non-ASCII byte would
        corrupt the Chinese exe path passed via %~1/%~2."""
        script = MODULE.write_update_swapper()
        try:
            raw = script.read_bytes()
            self.assertTrue(all(b < 128 for b in raw),
                            "the swapper script must stay ASCII-only")
            text = raw.decode("ascii")
            for needed in ("tasklist", "copy /y", "%~1", "%~2", "%~nx2",
                           "--after-update"):
                self.assertIn(needed, text)
        finally:
            script.unlink(missing_ok=True)

    def test_update_user_agent_is_latin1_safe(self):
        """HTTP headers are latin-1; using APP_NAME (Chinese) made urllib raise
        "'latin-1' codec can't encode characters"."""
        ua = MODULE._UPDATE_UA["User-Agent"]
        ua.encode("ascii")          # would raise UnicodeEncodeError otherwise

    def test_builtin_update_source_format(self):
        """UPDATE_REPO_DEFAULT ships inside the exe, so it must stay a valid
        `owner/repo` string or every user's 检查更新 breaks."""
        self.assertRegex(MODULE.UPDATE_REPO_DEFAULT, r"^[^/\s]+/[^/\s]+$")

    def test_unconfigured_repo_is_a_message_not_a_crash(self):
        """Must return early without touching the network (keeps tests offline)."""
        for bad in ("", "   ", "no-slash", "/", None):
            tag, url, name, err = MODULE.fetch_latest_release(bad)
            self.assertIsNone(tag)
            self.assertIn("未配置更新源", err or "")

    def test_gitee_source_format_is_validated_offline(self):
        """`gitee:owner/repo` is the China-friendly source; a malformed one must be
        rejected with a clear message instead of a network call."""
        for bad in ("gitee:", "gitee:onlyowner", "gitee:/"):
            tag, url, name, err = MODULE.fetch_latest_release(bad)
            self.assertIsNone(tag)
            self.assertIn("gitee:owner/repo", err or "")


class SettingsDefaultsTests(unittest.TestCase):
    def test_every_settings_key_used_in_code_is_registered(self):
        """Keys missing from DEFAULT_SETTINGS are silently dropped by load_settings,
        which is how float_geo's position memory died."""
        import ast
        src = SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(src)
        defaults = None
        for node in tree.body:
            if (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "DEFAULT_SETTINGS"
                            for t in node.targets)):
                defaults = {k.value for k in node.value.keys}
        self.assertIsNotNone(defaults)
        used = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                    and node.value.id == "SETTINGS"
                    and isinstance(node.slice, ast.Constant)
                    and isinstance(node.slice.value, str)):
                used.add(node.slice.value)
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get" and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "SETTINGS" and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                used.add(node.args[0].value)
        self.assertEqual(sorted(used - defaults), [],
                         "these SETTINGS keys would be dropped on restart")


if __name__ == "__main__":
    unittest.main()
