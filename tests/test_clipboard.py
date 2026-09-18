"""ClipboardModule behaviour tests against the live source; no real clipboard/GUI."""
import ast
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock
import uuid


SOURCE = Path(__file__).resolve().parents[1] / "unified" / "unified.py"


def extract():
    node = next(n for n in ast.parse(SOURCE.read_text(encoding="utf-8")).body
                if isinstance(n, ast.ClassDef) and n.name == "ClipboardModule")
    methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    import datetime, queue
    namespace = dict(datetime=datetime, json=json, Path=Path, queue=queue,
                     threading=threading, uuid4_str=lambda: uuid.uuid4().hex,
                     SETTINGS={"clip_skip_secrets": False, "clip_clear_on_exit": False})
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(SOURCE), "exec"), namespace)
    cls = type("ClipboardUnderTest", (), {n.name: namespace[n.name] for n in methods})
    return cls, namespace


class ClipboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cls, self.env = extract()
        self.env["HISTORY_FILE"] = Path(self.temp.name) / "history.json"
        self.env["CLIP_IMG_DIR"] = Path(self.temp.name) / "images"
        self.cm = self.cls()
        self.cm.root = Mock()
        self.cm.root.after.side_effect = lambda *a: uuid.uuid4().hex
        self.cm._init_service()

    def test_stop_pauses_only_the_view_not_the_service(self):
        self.cm._render_after = "page-timer"
        self.cm.stop()
        self.cm.root.after_cancel.assert_called_with("page-timer")
        self.assertFalse(self.cm._stop_event.is_set())
        self.assertFalse(self.cm._page_active)

    def test_worker_event_is_persisted_by_main_thread(self):
        self.cm._load_history()
        stamp = "2026-09-18T10:00:00+08:00"
        self.cm._capture_q.put(("txt", "from hidden page", "", stamp))
        self.cm._drain_captures()
        self.assertEqual(self.cm.history[0]["text"], "from hidden page")
        self.assertEqual(self.cm.history[0]["time"], stamp)
        persisted = json.loads(self.env["HISTORY_FILE"].read_text(encoding="utf-8"))
        self.assertEqual(persisted[0]["text"], "from hidden page")

    def test_rebuild_keeps_history_and_single_service_state(self):
        self.cm._load_history()
        self.cm._capture_q.put(("txt", "kept", "", "2026-09-18T10:00:00+08:00"))
        self.cm._drain_captures()
        history, stop_event = self.cm.history, self.cm._stop_event
        self.cm._init_service()
        self.cm._load_history()
        self.assertIs(self.cm.history, history)
        self.assertIs(self.cm._stop_event, stop_event)
        self.assertEqual(self.cm.history[0]["text"], "kept")

    def test_normalization_drops_broken_entries_and_reassigns_duplicate_ids(self):
        raw = [{"text": "ok", "id": "a", "pinned": True},
               "not-a-dict", {"id": "x"}, {"text": "ok", "id": "a"}]
        result = self.cm._normalize_history(raw)
        # Broken entries dropped; duplicate id 'a' gets a fresh unique id.
        self.assertEqual([h["id"] for h in result], ["a", result[1]["id"]])
        self.assertNotEqual(result[0]["id"], result[1]["id"])
        self.assertTrue(result[0]["pinned"])


if __name__ == "__main__":
    unittest.main()
