"""Rename regression tests using disposable files only."""
import ast
import os
from pathlib import Path
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "unified" / "unified.py"


class RenameTests(unittest.TestCase):
    def test_swap_undo_swap_undo(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        methods = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                   and n.name in ("apply_rename", "undo_rename")]
        namespace = {"os": os}
        exec(compile(ast.Module(body=methods, type_ignores=[]), str(SOURCE), "exec"),
             namespace)
        with tempfile.TemporaryDirectory(prefix="utb_rename_test_") as folder:
            root = Path(folder)
            (root / "A.txt").write_text("content A", encoding="utf-8")
            (root / "B.txt").write_text("content B", encoding="utf-8")
            for _ in range(2):
                count, failures, record = namespace["apply_rename"](
                    folder, [("A.txt", "B.txt"), ("B.txt", "A.txt")])
                self.assertEqual((count, failures), (2, []))
                self.assertEqual((root / "A.txt").read_text(), "content B")
                self.assertEqual((root / "B.txt").read_text(), "content A")
                self.assertEqual(namespace["undo_rename"](folder, record), (2, []))
                self.assertEqual((root / "A.txt").read_text(), "content A")
                self.assertEqual((root / "B.txt").read_text(), "content B")
                self.assertEqual(sorted(p.name for p in root.iterdir()), ["A.txt", "B.txt"])


if __name__ == "__main__":
    unittest.main()
