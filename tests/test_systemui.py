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

    def winfo_exists(self):
        if threading.get_ident() != self.owner:
            raise AssertionError('Tk called from worker')
        return True


class Workers:
    def __init__(self):
        self.jobs = []

    def Thread(self, target, daemon):
        return types.SimpleNamespace(start=lambda: self.jobs.append(target))

    def Event(self):
        return threading.Event()

    def run(self, index=0):
        self.jobs.pop(index)()


class Base:
    def __init__(self, app):
        self.app, self.root, self.body = app, app.root, Mock()


def load(name, **extra):
    node = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == name)
    # Shared module-level helpers live outside the class; compile them into the
    # isolated namespace so tests exercise the real implementations.
    helpers = [n for n in TREE.body
               if ((isinstance(n, ast.ClassDef) and n.name == '_WorkerFailure')
                   or (isinstance(n, ast.FunctionDef)
                       and n.name in ('run_in_background', 'make_secondary_button',
                                      'sort_treeview', 'parse_size')))]
    namespace = dict(BaseModule=Base, Path=Path, os=os, re=re, queue=queue,
                     ctypes=ctypes, tempfile=tempfile, threading=Workers(),
                     tk=Mock(), subprocess=Mock(), show_info=Mock(), show_warning=Mock(),
                     SETTINGS={}, save_settings=Mock(), UninstallModule=Mock(),
                     page_header=Mock(), WINGET_APPS=[])
    namespace.update({n: n for n in ('BG', 'PANEL', 'PANEL2', 'PANEL3', 'GREEN', 'CYAN',
                                    'ORANGE', 'TEXT', 'TEXT2', 'MUTED', 'RED', 'YELLOW',
                                    'FONT_UI', 'FONT_MONO', 'BORDER')})
    namespace.update(extra)
    exec(compile(ast.Module(body=helpers + [node], type_ignores=[]),
                 '<isolated-candidate>', 'exec'), namespace)
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


class PollerView:
    """Minimal Tk stand-in: records after() callbacks and can be destroyed."""

    def __init__(self):
        self.jobs, self.alive = [], True

    def after(self, delay, callback):
        self.jobs.append(callback)
        return len(self.jobs)

    def winfo_exists(self):
        return self.alive

    def tick(self):
        jobs, self.jobs = self.jobs, []
        for callback in jobs:
            callback()


class PollerTests(unittest.TestCase):
    """The shared queue+after skeleton must stay the only hand-rolled one."""

    @staticmethod
    def _poller():
        workers = Workers()
        ns = {'queue': queue, 'threading': workers}
        nodes = [n for n in TREE.body
                 if ((isinstance(n, ast.ClassDef) and n.name == '_WorkerFailure')
                     or (isinstance(n, ast.FunctionDef) and n.name == 'run_in_background'))]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<poller>', 'exec'), ns)
        return ns['run_in_background'], workers

    def test_messages_arrive_in_order_and_loop_stops_itself(self):
        spawn, workers = self._poller()
        view, seen = PollerView(), []
        def work(report):
            report(1)
            report(2)
            report(3)
        spawn(view, work, seen.append, interval=10)
        self.assertEqual(len(view.jobs), 1)      # only the poll is scheduled
        self.assertEqual(len(workers.jobs), 1)   # exactly one daemon worker
        workers.run()
        view.tick()
        self.assertEqual(seen, [1, 2, 3])
        self.assertEqual(view.jobs, [])          # drained + finished = no repoll

    def test_stale_token_skips_delivery_and_scheduling(self):
        spawn, workers = self._poller()
        view, seen, ran = PollerView(), [], []
        def work(report):
            ran.append(True)
            report('stale')
        spawn(view, work, seen.append, interval=10, alive=lambda: False)
        workers.run()
        view.tick()
        self.assertEqual(seen, [])
        self.assertEqual(view.jobs, [])
        self.assertEqual(ran, [True])

    def test_destroyed_window_never_touches_handler(self):
        spawn, workers = self._poller()
        view, seen = PollerView(), []
        view.alive = False
        spawn(view, lambda report: report('late'), seen.append, interval=10)
        workers.run()
        view.tick()
        self.assertEqual(seen, [])
        self.assertEqual(view.jobs, [])

    def test_worker_exception_is_delivered_on_ui_thread(self):
        spawn, workers = self._poller()
        view, seen, errors = PollerView(), [], []
        def work(report):
            report('before')
            raise ValueError('boom')
        spawn(view, work, seen.append, interval=10, on_error=errors.append)
        workers.run()
        view.tick()
        self.assertEqual(seen, ['before'])
        self.assertEqual([str(e) for e in errors], ['boom'])
        self.assertEqual(view.jobs, [])

    def test_handler_can_stop_early(self):
        spawn, workers = self._poller()
        view, seen = PollerView(), []
        def handle(message):
            seen.append(message)
            return False
        def work(report):
            report(1)
            report(2)
        spawn(view, work, handle, interval=10)
        workers.run()
        view.tick()
        self.assertEqual(seen, [1])
        self.assertEqual(view.jobs, [])

    def test_only_the_shared_helper_creates_a_poll_loop(self):
        offenders = []
        for node in ast.walk(TREE):
            if not isinstance(node, ast.FunctionDef) or node.name == 'run_in_background':
                continue
            calls = set()
            for child in ast.walk(node):
                if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                        and isinstance(child.func.value, ast.Name)):
                    calls.add((child.func.value.id, child.func.attr))
            has_queue = ('queue', 'Queue') in calls
            has_get = any(attr == 'get_nowait' for _value, attr in calls)
            if has_queue and has_get:
                offenders.append(node.name)
        self.assertEqual(offenders, [])


class FakeButton:
    def __init__(self, **options):
        self.options = dict(options)
        self.packed = None
        self.bound = {}

    def pack(self, **options):
        self.packed = options

    def bind(self, sequence, callback):
        self.bound[sequence] = callback

    def config(self, **options):
        self.options.update(options)


class FakeTk:
    def __init__(self):
        self.buttons = []

    def Button(self, parent, **options):
        button = FakeButton(**options)
        button.parent = parent
        self.buttons.append(button)
        return button


class FakeTree:
    def __init__(self, rows):
        self.values = {iid: dict(columns) for iid, columns in rows}
        self.order = [iid for iid, _columns in rows]

    def get_children(self):
        return tuple(self.order)

    def set(self, iid, column):
        return self.values[iid][column]

    def move(self, iid, parent, index):
        self.order.remove(iid)
        self.order.insert(index, iid)


class WidgetFactoryTests(unittest.TestCase):
    """Buttons and Treeview sorting share one implementation each."""

    @staticmethod
    def _helpers():
        nodes = [n for n in TREE.body
                 if isinstance(n, ast.FunctionDef)
                 and n.name in ('make_secondary_button', 'sort_treeview')]
        namespace = {'tk': FakeTk(), 'FONT_UI': 'Microsoft YaHei UI',
                     'PANEL2': '#1b2230', 'PANEL3': '#232c3d',
                     'CYAN': '#22d3ee'}
        exec(compile(ast.Module(body=nodes, type_ignores=[]),
                     '<widget-helpers>', 'exec'), namespace)
        return namespace

    def test_secondary_button_uses_shared_style(self):
        make = self._helpers()['make_secondary_button']
        clicked = []
        button = make(object(), '扫描', lambda: clicked.append(True),
                      color='#ff0000', font_size=10)
        self.assertEqual(button.options['text'], '扫描')
        self.assertEqual(button.options['bg'], '#1b2230')
        self.assertEqual(button.options['fg'], '#ff0000')
        self.assertEqual(button.options['font'], ('Microsoft YaHei UI', 10))
        self.assertEqual(button.options['cursor'], 'hand2')
        self.assertEqual(button.packed,
                         {'side': 'left', 'padx': (0, 6), 'pady': 4})
        button.bound['<Enter>'](None)
        self.assertEqual(button.options['bg'], '#232c3d')
        button.bound['<Leave>'](None)
        self.assertEqual(button.options['bg'], '#1b2230')
        button.options['command']()
        self.assertEqual(clicked, [True])

    def test_sort_treeview_orders_rows_without_rebuilding(self):
        sort_treeview = self._helpers()['sort_treeview']
        tree = FakeTree([('a', {'name': 'beta', 'size': '2'}),
                         ('b', {'name': 'alpha', 'size': '1'}),
                         ('c', {'name': 'gamma', 'size': '10'})])
        sort_treeview(tree, 'name')
        self.assertEqual(tree.get_children(), ('b', 'a', 'c'))
        sort_treeview(tree, 'size', key=float, reverse=True)
        self.assertEqual(tree.get_children(), ('c', 'a', 'b'))

    def test_file_sort_parses_size_units(self):
        cls, _ns = load('FileModule')
        obj = object.__new__(cls)
        obj.tree = FakeTree([('a', {'名称': 'a', '大小': '900.0M'}),
                             ('b', {'名称': 'b', '大小': '1.2G'}),
                             ('c', {'名称': 'c', '大小': '5.0K'})])
        obj._sort('大小')
        self.assertEqual(obj.tree.get_children(), ('b', 'a', 'c'))
        obj._sort('名称')
        self.assertEqual(obj.tree.get_children(), ('a', 'b', 'c'))

    def test_process_sort_is_numeric_for_cpu_pid_memory(self):
        cls, _ns = load('HardwareModule')
        obj = object.__new__(cls)
        rows = [('a', {'名称': 'a', 'CPU%': '9.5', 'PID': '9', '内存': '900.0M'}),
                ('b', {'名称': 'b', 'CPU%': '10.5', 'PID': '100', '内存': '1.2G'}),
                ('c', {'名称': 'c', 'CPU%': '2.0', 'PID': '20', '内存': '5.0K'})]
        obj.procs_tree = FakeTree(rows)
        obj._sort_procs('CPU%')
        self.assertEqual(obj.procs_tree.get_children(), ('b', 'a', 'c'))
        obj._sort_procs('PID')
        self.assertEqual(obj.procs_tree.get_children(), ('b', 'c', 'a'))
        obj._sort_procs('内存')
        self.assertEqual(obj.procs_tree.get_children(), ('b', 'a', 'c'))
        obj._sort_procs('名称')
        self.assertEqual(obj.procs_tree.get_children(), ('a', 'b', 'c'))

    def test_button_factories_delegate_to_the_shared_helper(self):
        factories = [n for n in ast.walk(TREE)
                     if isinstance(n, ast.FunctionDef)
                     and n.name in ('_mkbtn', '_make_btn')]
        self.assertTrue(factories)
        for factory in factories:
            calls = [c for c in ast.walk(factory) if isinstance(c, ast.Call)]
            names = {c.func.id for c in calls if isinstance(c.func, ast.Name)}
            self.assertIn('make_secondary_button', names,
                          ast.get_source_segment(CANDIDATE, factory))
            own_button = any(isinstance(c.func, ast.Attribute)
                             and c.func.attr == 'Button' for c in calls)
            self.assertFalse(own_button,
                             'factory still builds its own tk.Button')

    def test_only_shared_helper_moves_tree_rows(self):
        offenders = []
        for node in ast.walk(TREE):
            if not isinstance(node, ast.FunctionDef) or node.name == 'sort_treeview':
                continue
            methods = {c.func.attr for c in ast.walk(node)
                       if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
            if 'get_children' in methods and 'move' in methods:
                offenders.append(node.name)
        self.assertEqual(offenders, [])


class ThemeTests(unittest.TestCase):
    """Theme switching must repaint in place: a rebuild stops running work and
    wipes search text, list data and scroll position."""

    @staticmethod
    def _function(name):
        return next(n for n in TREE.body
                    if isinstance(n, ast.FunctionDef) and n.name == name)

    def test_color_map_only_covers_changed_values(self):
        node = self._function('_theme_color_map')
        keys = ('BG', 'PANEL', 'PANEL2', 'PANEL3', 'BORDER', 'CYAN', 'PURPLE',
                'GREEN', 'YELLOW', 'RED', 'ORANGE', 'TEXT', 'TEXT2', 'MUTED')
        namespace = {'_THEME_KEYS': keys}
        exec(compile(ast.Module(body=[node], type_ignores=[]),
                     '<theme-map>', 'exec'), namespace)
        mapping = namespace['_theme_color_map']
        old = {k: '#000000' for k in keys}
        new = {k: '#000000' for k in keys}
        old['BG'], new['BG'] = '#0d1117', '#f5f7fa'
        old['CYAN'], new['CYAN'] = '#0089e9', '#a78bfa'
        self.assertEqual(mapping(old, new),
                         {'#0d1117': '#f5f7fa', '#0089e9': '#a78bfa'})
        self.assertEqual(mapping(old, old), {})

    def test_apply_theme_live_never_destroys_or_rebuilds_page(self):
        app = next(n for n in TREE.body
                   if isinstance(n, ast.ClassDef) and n.name == 'App')
        fn = next(n for n in app.body
                  if isinstance(n, ast.FunctionDef) and n.name == '_apply_theme_live')
        source = ast.get_source_segment(CANDIDATE, fn)

        # Calls reachable without entering an except handler: these run on the
        # happy path, so none of them may tear the page or settings window down.
        def happy_path_calls(nodes):
            names, stack = [], list(nodes)
            while stack:
                node = stack.pop()
                if isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Attribute):
                        names.append(func.attr)
                    elif isinstance(func, ast.Name):
                        names.append(func.id)
                for child in ast.iter_child_nodes(node):
                    if not isinstance(child, ast.ExceptHandler):
                        stack.append(child)
            return names

        calls = happy_path_calls(fn.body)
        self.assertNotIn('_switch', calls)
        self.assertNotIn('destroy', calls)
        self.assertIn('recolor_widget_tree', calls)
        # 预览色块必须在整体重涂之后重画，否则当前主题那块会被染成新主题
        self.assertLess(source.index('recolor_widget_tree'),
                        source.index('_paint_theme_chip'))

    def test_cancel_previews_restores_theme_then_closes_window(self):
        app = next(n for n in TREE.body
                   if isinstance(n, ast.ClassDef) and n.name == 'App')
        fn = next(n for n in app.body
                  if isinstance(n, ast.FunctionDef) and n.name == 'show_settings')
        source = ast.get_source_segment(CANDIDATE, fn)
        start = source.index('def cancel():')
        body = source[start:source.index('tk.Button(btns', start)]
        self.assertIn('theme_var.set(saved_theme)', body)
        self.assertLess(body.index('_apply_theme_live(saved_theme)'),
                        body.index('win.destroy()'))
        # 旧写法靠重建窗口收尾，会直接 return，窗口留在屏幕上
        self.assertNotIn('return          #', body)


if __name__ == '__main__':
    unittest.main()
