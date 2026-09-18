"""Regression tests for uninstall scan against the live source; no GUI or real registry access."""
import ast
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "unified" / "unified.py"
MISSING = object()


def load_scan_reg():
    # Extract the actual method without running application-level startup code.
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == "UninstallModule")
    method = next(node for node in cls.body
                  if isinstance(node, ast.FunctionDef) and node.name == "_scan_reg")
    namespace = {"queue": types.SimpleNamespace()}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(SOURCE), "exec"),
         namespace)
    return namespace["_scan_reg"]


class FakeRegistry(types.ModuleType):
    HKEY_LOCAL_MACHINE = "HKLM"
    HKEY_CURRENT_USER = "HKCU"

    def __init__(self, size):
        super().__init__("winreg")
        self.root = object()
        self.app = object()
        self.opened = False
        self.closed = False
        self.events = []
        self.values = {"DisplayName": "Test App", "UninstallString": "uninstall.exe"}
        if size is not MISSING:
            self.values["EstimatedSize"] = size

    def OpenKey(self, parent, key):
        if parent is self.root:
            return self.app
        if self.opened:
            raise FileNotFoundError(key)
        self.opened = True
        return self.root

    def QueryInfoKey(self, handle):
        return (1, 0, 0)

    def EnumKey(self, handle, index):
        return "TestApp"

    def QueryValueEx(self, handle, name):
        self.events.append(("query", name))
        if self.closed:
            raise OSError("Registry handle already closed")
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], 1

    def CloseKey(self, handle):
        if handle is self.app:
            self.events.append(("close", None))
            self.closed = True


class UninstallSizeTests(unittest.TestCase):
    def check_size(self, value, expected):
        registry = FakeRegistry(value)
        model = types.SimpleNamespace(_all_apps=[], _fmt_date=lambda value: value)
        with patch.dict(sys.modules, {"winreg": registry}):
            apps = load_scan_reg()(model)
        # _scan_reg returns an immutable snapshot; it must not mutate shared state.
        self.assertEqual(model._all_apps, [])
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0]["size"], expected)
        self.assertTrue(registry.closed)
        self.assertLess(registry.events.index(("query", "EstimatedSize")),
                        registry.events.index(("close", None)))

    def test_existing_size_is_preserved(self):
        self.check_size(4096, 4096.0)

    def test_missing_size_defaults_to_zero(self):
        self.check_size(MISSING, 0.0)

    def test_invalid_size_defaults_to_zero(self):
        self.check_size("not-a-number", 0)


if __name__ == "__main__":
    unittest.main()
