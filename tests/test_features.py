"""Feature tests against the live source; no GUI or real OCR/registry access."""
import ast
from pathlib import Path
import sys
import types
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "unified" / "unified.py"


def load_names(*names):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    wanted = set(names) | {"_STRINGS_EN"}
    nodes = []
    for n in tree.body:
        if isinstance(n, ast.ClassDef) and n.name == "ClipboardModule":
            nodes += [m for m in n.body if isinstance(m, (ast.FunctionDef, ast.Assign))
                      and (m.name in names if isinstance(m, ast.FunctionDef)
                           else any(isinstance(t, ast.Name) and t.id in wanted
                                    for t in m.targets))]
        elif isinstance(n, (ast.FunctionDef, ast.Assign)) and (
                n.name in names if isinstance(n, ast.FunctionDef)
                else any(isinstance(t, ast.Name) and t.id in wanted for t in n.targets)):
            nodes.append(n)
    ns = {"re": __import__("re"), "SETTINGS": {}, "Path": Path,
          "os": __import__("os"), "tempfile": __import__("tempfile"),
          "subprocess": __import__("subprocess")}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), ns)
    return ns


class SecretFilterTests(unittest.TestCase):
    def setUp(self):
        self.ns = load_names("_looks_secret", "_SECRET_RE")
        self.cls = type("C", (), {"_SECRET_RE": self.ns["_SECRET_RE"],
                                  "_looks_secret": self.ns["_looks_secret"]})

    def check(self, text):
        return self.cls._looks_secret(text)

    def test_password_kv_detected(self):
        for s in ("password: hunter2", "TOKEN=abc123", "api_key: sk-xxx",
                  "我的密码：abc123", "数据库密码 = p@ss"):
            self.assertTrue(self.check(s), s)

    def test_common_token_prefixes_detected(self):
        for s in ("sk-abcdefghijklmnopqrstuvwxyz", "ghp_" + "a" * 36,
                  "AKIA" + "A" * 16 + "x", "xoxb-" + "a" * 20,
                  "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4"):
            self.assertTrue(self.check(s), s)

    def test_long_hex_detected(self):
        self.assertTrue(self.check("deadbeef" * 8))   # 64 hex chars

    def test_normal_text_not_flagged(self):
        for s in ("hello world", "https://example.com/page",
                  "会议纪要：明天上午十点开会", "def add(a, b): return a + b",
                  "TODO: fix the login page styling"):
            self.assertFalse(self.check(s), s)


class TranslationTests(unittest.TestCase):
    def test_zh_returns_original(self):
        ns = load_names("T")
        ns["SETTINGS"]["lang"] = "zh"
        self.assertEqual(ns["T"]("设置中心"), "设置中心")

    def test_en_translates_known_keys(self):
        ns = load_names("T")
        ns["SETTINGS"]["lang"] = "en"
        self.assertEqual(ns["T"]("设置中心"), "Settings")
        self.assertEqual(ns["T"]("退出"), "Exit")

    def test_en_falls_back_for_unknown_keys(self):
        ns = load_names("T")
        ns["SETTINGS"]["lang"] = "en"
        self.assertEqual(ns["T"]("某个未翻译的句子"), "某个未翻译的句子")


class LazyModulesTests(unittest.TestCase):
    def test_app_init_does_not_instantiate_all_modules(self):
        src = SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(src)
        app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "App")
        init = next(n for n in app.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
        for node in ast.walk(init):
            if isinstance(node, ast.For) and isinstance(node.iter, ast.Name):
                self.assertNotEqual(node.iter.id, "MODULES",
                                    "App.__init__ must not instantiate all modules")
        self.assertIn("self._module_classes", src)
        self.assertIn("def module(self, name):", src)

    def test_mutex_guards_second_instance(self):
        src = SOURCE.read_text(encoding="utf-8")
        main_fn = next(n for n in ast.parse(src).body
                       if isinstance(n, ast.FunctionDef) and n.name == "main")
        text = ast.get_source_segment(src, main_fn)
        self.assertIn("CreateMutexW", text)
        # 实现已改为 OpenMutexW 探测（CreateMutexW 的返回码在 ctypes 下不可靠），
        # 因此不再依赖 ERROR_ALREADY_EXISTS；真实行为由
        # integration_checks.single_instance 实测覆盖。
        self.assertIn("OpenMutexW", text)
        probe = text.index("OpenMutexW(0x00100000")
        self.assertLess(probe, text.index("App(root)"),
                        "second-instance probe must run before App starts")


class OcrValidationTests(unittest.TestCase):
    def test_missing_file_reported_without_spawning_process(self):
        ns = load_names("ocr_image_text", "_OCR_PS1")
        text, err = ns["ocr_image_text"](Path("Z:/definitely/missing.png"))
        self.assertEqual(text, "")
        self.assertIn("不存在", err)


if __name__ == "__main__":
    unittest.main()
