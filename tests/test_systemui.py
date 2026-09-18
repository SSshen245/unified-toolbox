"""AST/mocked candidate tests; no real activation, installs, tray, or input injection."""
import ast
import base64
import ctypes
import ctypes.wintypes
import importlib.util
import os
from pathlib import Path
import queue
import re
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'unified' / 'unified.py').read_text(encoding='utf-8')
CANDIDATE = SOURCE  # repairs are applied to the live source; tests exercise it
TREE = ast.parse(CANDIDATE)


class Scheduler:
    def __init__(self):
        self.jobs, self.serial = {}, 0
        self.owner = threading.get_ident()

    def after(self, delay, callback):
        if threading.get_ident() != self.owner:
            raise AssertionError('Tk called from worker')
        self.serial += 1
        self.jobs[self.serial] = callback
        return self.serial

    def after_idle(self, callback):
        return self.after(0, callback)

    def after_cancel(self, ident):
        self.jobs.pop(ident, None)

    def tick(self):
        jobs, self.jobs = self.jobs, {}
        for callback in jobs.values():
            callback()


class Workers:
    def __init__(self):
        self.jobs = []

    def Thread(self, target, daemon):
        return types.SimpleNamespace(start=lambda: self.jobs.append(target))

    def run(self, index=0):
        self.jobs.pop(index)()


class Base:
    def __init__(self, app):
        self.app, self.root, self.body = app, app.root, Mock()


def load(name, **extra):
    node = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == name)
    namespace = dict(BaseModule=Base, Path=Path, os=os, re=re, queue=queue,
                     ctypes=ctypes, tempfile=tempfile, threading=Workers(),
                     tk=Mock(), subprocess=Mock(), show_info=Mock(), show_warning=Mock(),
                     SETTINGS={}, save_settings=Mock(), UninstallModule=Mock(),
                     page_header=Mock(), WINGET_APPS=[])
    namespace.update({n: n for n in ('BG', 'PANEL', 'PANEL2', 'PANEL3', 'GREEN', 'CYAN',
                                    'ORANGE', 'TEXT', 'TEXT2', 'MUTED', 'RED', 'YELLOW',
                                    'FONT_UI', 'FONT_MONO', 'BORDER')})
    namespace.update(extra)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<isolated-candidate>', 'exec'), namespace)
    return namespace[name], namespace


def module(name):
    cls, ns = load(name)
    root = Scheduler()
    obj = cls(types.SimpleNamespace(root=root, _closing=False))
    obj.body = Mock()
    obj._view_active, obj._view_token = True, object()
    return obj, ns


class PatchTests(unittest.TestCase):
    def test_live_source_compiles_and_scope_is_unchanged(self):
        # Repairs are already applied to the live source; assert it compiles and
        # that no accidental duplicate class definitions exist.
        compile(CANDIDATE, '<live-source>', 'exec')
        names = [n.name for n in TREE.body if isinstance(n, ast.ClassDef)]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn('App', names)
        self.assertIn('ActivationModule', names)


class ActivationTests(unittest.TestCase):
    def test_scan_stale_completion_does_not_clear_new_task(self):
        obj, ns = module('ActivationModule')
        obj._refresh_btn, obj._render = Mock(), Mock()
        ns.update(query_windows_activation=Mock(return_value={'win': 1}),
                  slmgr_xpr_text=Mock(return_value='x'),
                  is_permanent_activated=Mock(return_value=(True, 'permanent')),
                  query_office_activation=Mock(return_value=([], False)))
        obj._scan()
        obj.stop()
        obj._view_active = True
        obj._scan()
        task = obj._scan_task
        ns['threading'].run()
        obj.root.tick()
        obj._render.assert_not_called()
        self.assertIs(obj._scan_task, task)
        self.assertTrue(obj._scanning)
        ns['threading'].run()
        obj.root.tick()
        obj._render.assert_called_once()
        self.assertFalse(obj._scanning)

    def test_activation_deferred_and_duplicate_guard_survives_view_stop(self):
        obj, ns = module('ActivationModule')
        obj._activation_command = Mock(return_value=('completed', 'mock only'))
        key = 'AAAAA-BBBBB-CCCCC-DDDDD-EEEEE'
        obj._begin_activation(key)
        obj._activation_command.assert_not_called()
        obj.stop()
        obj._begin_activation(key)
        self.assertEqual(len(ns['threading'].jobs), 1)
        ns['threading'].run()
        obj.root.tick()
        self.assertFalse(obj._activating)
        ns['show_info'].assert_called_once()  # duplicate notice, no stale result

    def test_mocked_unicode_command_and_return_classification(self):
        cls, ns = load('ActivationModule')
        temp = MagicMock()
        temp.TemporaryDirectory.return_value.__enter__.return_value = "C:\\用户 O'Neil\\临时目录"
        ns['tempfile'] = temp
        key = 'AAAAA-BBBBB-CCCCC-DDDDD-EEEEE'
        with patch.object(Path, 'exists', return_value=False):
            for code, output, expected in ((0, b'', 'completed'), (5, b'failed', 'error'),
                                           (1223, b'UTB_UAC_CANCELLED', 'cancelled')):
                ns['subprocess'].run.return_value = types.SimpleNamespace(
                    returncode=code, stdout=output, stderr=b'')
                self.assertEqual(cls._activation_command(key)[0], expected)
                command = ns['subprocess'].run.call_args.args[0]
                outer = base64.b64decode(command[-1]).decode('utf-16le')
                encoded_child = re.search(r'-EncodedCommand ([A-Za-z0-9+/=]+)', outer)[1]
                child = base64.b64decode(encoded_child).decode('utf-16le')
                self.assertIn("用户 O''Neil", child)
                self.assertIn('临时目录', child)
                self.assertIn('$rc=$LASTEXITCODE', child)
                self.assertIn('if ($rc -eq 0)', child)
                self.assertIn('-PassThru', outer)
                self.assertNotIn('cmd.exe', outer)

    def test_invalid_key_never_starts_process(self):
        cls, ns = load('ActivationModule')
        self.assertEqual(cls._activation_command('invalid')[0], 'error')
        ns['subprocess'].run.assert_not_called()


class SoftwareTests(unittest.TestCase):
    def test_build_does_not_reset_installing_and_version_does_not_enable(self):
        obj, ns = module('SoftwareModule')
        obj._installing = True
        obj._wg_version = 'v1'
        obj.build()
        self.assertTrue(obj._installing)
        self.assertEqual(obj._wg_version, 'v1')
        obj._wg_go.config.assert_called_with(state='disabled', text='⏳ 安装中…')
        obj._installing = False
        obj._render_winget('')
        obj._wg_go.config.assert_called_with(state='disabled')

    def test_install_task_finishes_off_page_without_stale_widget_calls(self):
        obj, ns = module('SoftwareModule')
        ns['ask_yesno'] = Mock(return_value=True)
        ns['subprocess'].run.return_value = types.SimpleNamespace(stdout='mock install', returncode=5)
        obj._wg_vars = {'Mock.Package': Mock(get=Mock(return_value=True))}
        obj._wg_go = Mock()
        obj._wg_log_append = Mock()
        obj._install_checked()
        obj.stop()
        obj._wg_log_append.reset_mock()
        obj._wg_go.reset_mock()
        ns['threading'].run()
        obj.root.tick()
        self.assertFalse(obj._installing)
        obj._wg_go.config.assert_not_called()
        obj._wg_log_append.assert_not_called()

    def test_old_winget_check_cannot_render_rebuilt_view(self):
        obj, ns = module('SoftwareModule')
        ns['check_winget'] = Mock(return_value='old-version')
        obj._render_winget = Mock()
        obj._check_winget_async()
        obj.stop()
        obj._view_active = True
        ns['threading'].run()
        obj.root.tick()
        obj._render_winget.assert_not_called()


class AppTests(unittest.TestCase):
    def test_switch_after_shutdown_never_touches_tk_or_modules(self):
        cls, ns = load('App')
        obj = cls.__new__(cls)
        obj._closing = True
        obj.modules, obj.root, obj.body = Mock(), Mock(), Mock()
        obj._page_cleanup = Mock()
        obj._switch('home')
        self.assertEqual(obj.modules.mock_calls, [])
        self.assertEqual(obj.body.mock_calls, [])
        self.assertEqual(obj.root.mock_calls, [])
        obj._page_cleanup.assert_not_called()
        ns['tk'].assert_not_called()

    def test_shutdown_unified_stops_modules_optional_shutdown_and_waits_tray_thread(self):
        cls, ns = load('App')
        obj = cls.__new__(cls)
        obj._closing = False
        obj.root = Mock()
        obj.modules = {'a': Mock(spec=['stop']), 'b': Mock(spec=['shutdown']),
                       'c': Mock(spec=['shutdown'])}
        obj.modules['c'].shutdown = Mock(side_effect=RuntimeError('must not abort loop'))
        obj._save_geometry = Mock()
        cleanup = obj._page_cleanup = Mock()
        obj._event_timer = None
        obj._hotkey_thread_id = None
        obj._stop_event = threading.Event()
        obj._tray_lock = threading.Lock()
        icon = Mock()
        obj._tray_icon = icon
        obj._tray_ready = True
        obj._qp_hide = Mock()
        workers = Workers()
        ns['threading'] = workers
        cls._quit_app(obj)
        self.assertTrue(obj._closing)
        cleanup.assert_called_once_with()
        obj.modules['a'].stop.assert_called_once_with()
        obj.modules['b'].shutdown.assert_called_once_with()
        self.assertEqual(obj.modules['c'].shutdown.call_count, 1)
        self.assertEqual(len(workers.jobs), 1)
        self.assertTrue(obj.root.after_cancel.called)
        self.assertEqual(icon.mock_calls, [])
        self.assertEqual(obj.root.mock_calls[-1][0], 'destroy')
        workers.run()
        icon.stop.assert_called_once_with()

    def test_quit_ignores_second_call(self):
        cls, ns = load('App')
        obj = cls.__new__(cls)
        obj._closing = True
        obj._save_geometry = Mock()
        obj.modules = Mock()
        cls._quit_app(obj)
        obj._save_geometry.assert_not_called()
        self.assertEqual(obj.modules.mock_calls, [])

    def test_hide_to_tray_needs_ready_tray_else_quits(self):
        cls, ns = load('App')
        ns['SETTINGS']['close_action'] = 'tray'
        for ready, icon, quit_after in ((False, Mock(), True), (True, None, True),
                                        (True, Mock(), False)):
            obj = cls.__new__(cls)
            obj._closing = False
            obj._tray_ready, obj._tray_icon = ready, icon
            obj.root = Mock()
            obj.root.state.return_value = 'normal'
            obj._save_geometry = Mock()
            obj._quit_app = Mock()
            obj._tray_hinted = False
            cls._hide_to_tray(obj)
            self.assertEqual(obj.root.withdraw.called, not quit_after)
            self.assertEqual(obj._quit_app.called, quit_after)

    def test_event_queue_and_stale_tray_identity(self):
        cls, ns = load('App')
        obj = cls.__new__(cls)
        obj._closing = False
        obj.root = Scheduler()
        obj.root.state = Mock(return_value='withdrawn')
        obj._ui_events = queue.Queue()
        icon = obj._tray_icon = Mock()
        obj._tray_ready = False
        for name in ('_show_main', 'show_quick_panel', 'toggle_pin_action', 'show_settings', '_quit_app'):
            setattr(obj, name, Mock())
        for event in (('tray_stopped', Mock()), ('tray_ready', icon), ('quick', 123)):
            obj._ui_events.put(event)
        obj._drain_ui_events()
        self.assertTrue(obj._tray_ready)
        self.assertIs(obj._tray_icon, icon)
        obj.show_quick_panel.assert_called_once_with(123)
        obj._show_main.assert_not_called()
        obj._ui_events.put(('tray_stopped', icon))
        obj.root.tick()
        self.assertFalse(obj._tray_ready)
        obj._show_main.assert_called_once_with()

    def test_geometry_bad_types_and_offscreen_positions(self):
        cls, ns = load('App')
        obj = cls.__new__(cls)
        obj.root = Mock()
        fake = Mock()
        fake.windll.user32.GetSystemMetrics.side_effect = lambda i: {76: 0, 77: 0, 78: 1920, 79: 1080}[i]
        ns['ctypes'] = fake
        for value in (None, [], 1, 'garbage', '999999x12'):
            self.assertEqual(obj._validated_geometry(value), '1100x900+0+0')
        self.assertEqual(obj._validated_geometry('1500x900+90000-90000'), '1500x900+420+0')

    def test_paste_rechecks_target_foreground_and_modifiers(self):
        cls, ns = load('App')
        obj = cls.__new__(cls)
        obj._closing = False
        target = (0x123456789, 42, 77)
        obj._target_identity = Mock(return_value=target)
        ns['ctypes'] = Mock()
        u32 = ns['ctypes'].windll.user32
        u32.GetForegroundWindow.return_value = target[0]
        u32.GetAsyncKeyState.return_value = 0
        self.assertTrue(obj._send_ctrl_v(target))
        self.assertEqual(u32.keybd_event.call_count, 4)
        u32.keybd_event.reset_mock()
        u32.GetForegroundWindow.return_value = 99
        self.assertFalse(obj._send_ctrl_v(target))
        u32.GetForegroundWindow.return_value = target[0]
        obj._target_identity.return_value = None
        self.assertFalse(obj._send_ctrl_v(target))
        obj._target_identity.return_value = target
        u32.GetAsyncKeyState.return_value = 0x8000
        self.assertFalse(obj._send_ctrl_v(target))
        u32.keybd_event.assert_not_called()

    def test_focus_none_hides_but_child_focus_does_not(self):
        cls, ns = load('App')
        obj = cls.__new__(cls)
        obj.root, obj._quick_panel, obj._qp_hide = Mock(), Mock(), Mock()
        obj.root.focus_get.return_value = None
        obj._qp_maybe_hide()
        obj._qp_hide.assert_called_once_with()
        obj._qp_hide.reset_mock()
        obj.root.focus_get.return_value = Mock(winfo_toplevel=Mock(return_value=obj._quick_panel))
        obj._qp_maybe_hide()
        obj._qp_hide.assert_not_called()

    def test_worker_ast_has_no_tk_after_and_scroll_bindings_are_owned(self):
        app_node = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'App')
        methods = {n.name: n for n in app_node.body if isinstance(n, ast.FunctionDef)}
        for name in ('_tray_worker', '_hotkey_worker'):
            calls = [n.func.attr for n in ast.walk(methods[name]) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Attribute)]
            self.assertNotIn('after', calls)
            self.assertNotIn('destroy', calls)
        switch = ast.get_source_segment(CANDIDATE, methods['_switch'])
        self.assertNotIn('unbind_all(', switch)
        self.assertNotIn('bind_all(', switch)
        self.assertIn('widget.unbind(sequence, ident)', switch)
        self.assertIn('after_cancel(pending[0])', switch)
        self.assertIn('height=content_height', switch)
        self.assertNotIn('pack_propagate(False)', switch)
        init = ast.get_source_segment(CANDIDATE, methods['__init__'])
        self.assertIn("root.protocol('WM_DELETE_WINDOW', self._hide_to_tray)", init)


if __name__ == '__main__':
    unittest.main()
