"""Release-tooling regression tests: no network, no git commands."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_ORIGINAL_CWD = os.getcwd()
try:
    _spec = importlib.util.spec_from_file_location("utb_release", ROOT / "release.py")
    RELEASE = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(RELEASE)
finally:
    os.chdir(_ORIGINAL_CWD)


class GiteeUploadFormTests(unittest.TestCase):
    """The .sha256 attachment must not reuse the exe's upload filename."""

    def test_attachment_filenames_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            exe = Path(folder) / "UnifiedToolbox.exe"
            exe.write_bytes(b"MZ")
            sha = Path(folder) / "UnifiedToolbox.exe.sha256"
            sha.write_text("deadbeef  UnifiedToolbox.exe\n", encoding="ascii")

            exe_body, content_type = RELEASE._gitee_file_form("token", exe)
            sha_body, _ = RELEASE._gitee_file_form("token", sha)

        self.assertIn(b'filename="UnifiedToolbox.exe"', exe_body)
        self.assertIn(b'filename="UnifiedToolbox.exe.sha256"', sha_body)
        self.assertNotIn(b'filename="UnifiedToolbox.exe"\r\n', sha_body)
        self.assertIn(b"deadbeef  UnifiedToolbox.exe", sha_body)
        self.assertIn("multipart/form-data; boundary=", content_type)


if __name__ == "__main__":
    unittest.main()
