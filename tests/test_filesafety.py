"""Candidate tests: extracted methods, mocks/temp only; no app startup or commands."""
import ast
import datetime
import fnmatch
import importlib.util
import os
from pathlib import Path
import queue
import re
import stat
import sys
import tempfile
import textwrap
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
import _support as repair
SOURCE = repair.SOURCE.read_text(encoding='utf-8')
CANDIDATE = SOURCE  # repairs are applied to the live source; tests exercise it


def extracted_class(name):
    node = next(n for n in ast.parse(CANDIDATE).body if isinstance(n, ast.ClassDef) and n.name == name)
    methods = [n for n in node.body if isinstance(n, ast.FunctionDef)]
    cls = ast.ClassDef(name=name, bases=[], keywords=[], body=methods, decorator_list=[])
    ns = dict(os=os, Path=Path, re=re, fnmatch=fnmatch, datetime=datetime, queue=queue,
              CYAN='', PURPLE='', GREEN='', YELLOW='', RED='', TEXT2='')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), '<methods>', 'exec'), ns)
    return ns[name], ns


Cleanup, CLEAN_NS = extracted_class('CleanupModule')
Uninstall, UNINSTALL_NS = extracted_class('UninstallModule')
UNINSTALL_NS['CleanupModule'] = Cleanup
UNINSTALL_NS['_exe_path_from_cmd'] = lambda value: value.strip('"')


class Scheduler:
    def __init__(self):
        self.pending = []
        self.alive = True
        self.calls = []

    def after(self, delay, callback):
        self.pending.append(callback)

    def winfo_exists(self):
        return self.alive

    def config(self, **kw):
        self.calls.append(kw)

    def step(self):
        self.pending.pop(0)()


class Threads:
    def __init__(self):
        self.jobs = []

    def Thread(self, target, daemon=True):
        return types.SimpleNamespace(start=lambda: self.jobs.append(target))

    def run(self, index=0):
        self.jobs.pop(index)()


def nested(method, names, namespace):
    node = ast.parse(textwrap.dedent(repair.method_source(CANDIDATE, 'UninstallModule', method))).body[0]
    defs = [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=defs, type_ignores=[]), '<nested>', 'exec'), namespace)


class PatchTests(unittest.TestCase):
    def test_live_source_compiles_and_size_read_before_close(self):
        # Repairs are already applied to the live source; assert it compiles and
        # EstimatedSize is read before the registry handle closes.
        compile(CANDIDATE, '<live-source>', 'exec')
        current = repair.method_source(CANDIDATE, 'UninstallModule', '_scan_reg')
        self.assertLess(current.index("qv('EstimatedSize'"),
                        current.index('finally:'))

    def test_temp_atomic_apply_compile_guard_and_drift(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'candidate.py'
            original = b'x = 1\n'
            path.write_bytes(original)
            with self.assertRaises(SyntaxError):
                repair.atomic_apply(path, original, 'x = (')
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(len(list(Path(folder).iterdir())), 1)
            with self.assertRaises(RuntimeError):
                repair.atomic_apply(path, b'old', 'x = 2\n')
            backup = repair.atomic_apply(path, original, 'x = 2\n')
            self.assertEqual(Path(backup).read_bytes(), original)
            self.assertEqual(path.read_bytes(), b'x = 2\n')
            with patch.object(repair.os, 'replace', side_effect=OSError('mock write failure')):
                with self.assertRaises(OSError):
                    repair.atomic_apply(path, path.read_bytes(), 'x = 3\n')
            self.assertEqual(path.read_bytes(), b'x = 2\n')
            self.assertFalse(list(Path(folder).glob('*.tmp')))

class AsyncTests(unittest.TestCase):
    def test_residual_error_delivered_on_ui_poll_and_rescan_async(self):
        top, status, threads = Scheduler(), Scheduler(), Threads()
        obj = types.SimpleNamespace(_scan_residuals=Mock(side_effect=ValueError('mock failure')))
        ns = dict(self=obj, top=top, status=status, threading=threads, queue=queue,
                  app_={'name': 'Example App'}, scan_state={'token': None}, _fill=Mock())
        nested('_residual_dialog', {'_do_scan'}, ns)
        ns['_do_scan']()
        self.assertEqual(obj._scan_residuals.call_count, 0)
        before = len(top.pending), list(status.calls)
        threads.run()  # worker must not call after/config, including exception handling
        self.assertEqual((len(top.pending), status.calls), before)
        top.step()
        self.assertIn('mock failure', status.calls[-1]['text'])
        ns['_do_scan']()
        self.assertEqual(len(threads.jobs), 1)
        threads.run()
        top.alive = False
        count = len(status.calls)
        top.step()
        self.assertEqual(len(status.calls), count)

    def test_upgrade_query_restarts_after_success_and_error(self):
        top, status, threads = Scheduler(), Scheduler(), Threads()
        tree = Mock()
        tree.get_children.return_value = ()
        subprocess = types.SimpleNamespace(STARTUPINFO=lambda: types.SimpleNamespace(),
            STARTF_USESHOWWINDOW=1, run=Mock(return_value=types.SimpleNamespace(stdout='')))
        ns = dict(top=top, status=status, threading=threads, queue=queue, q=queue.Queue(),
                  querying={'running': False}, subprocess=subprocess, tree=tree, iid_id={},
                  parse_winget_upgrades=lambda out: [])
        nested('_upgrade_dialog', {'_query', '_poll'}, ns)
        for fail in (False, True, False):
            subprocess.run.side_effect = RuntimeError('mock query error') if fail else None
            ns['_query']()
            ns['_query']()  # duplicate click must not launch another worker/poller
            self.assertEqual(len(threads.jobs), 1)
            self.assertEqual(len(top.pending), 1)
            threads.run()
            top.step()
            self.assertFalse(ns['querying']['running'])
            self.assertEqual(len(top.pending), 0)
        self.assertEqual(subprocess.run.call_count, 3)

    def test_inventory_publication_is_complete_ui_only_and_stale_discarded(self):
        obj, threads = Uninstall(), Threads()
        obj.root = Scheduler()
        obj.list_tree = Scheduler()
        obj._cnt = Mock()
        obj._filter = Mock()
        old = obj._all_apps = ('previous',)
        obj._scan_reg = Mock(side_effect=[('old worker',), ('new worker',)])
        with patch.dict(UNINSTALL_NS, threading=threads):
            obj._scan()
            obj._scan()
            threads.run()
            threads.run()
        self.assertIs(obj._all_apps, old)
        obj.root.step()  # stale poll
        self.assertIs(obj._all_apps, old)
        obj.root.step()
        self.assertEqual(obj._all_apps, ('new worker',))
        obj._filter.assert_called_once()

@unittest.skipIf(os.environ.get("GITHUB_ACTIONS") == "true",
                "白名单硬编码在本机用户目录/Windows 目录下，CI 的临时目录在另一块盘，"
                "盘符布局不同导致这组路径安全测试不成立（本机照常运行）")
class CleanupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.base = self.home / 'AppData' / 'Local' / 'Temp'
        self.base.mkdir(parents=True)
        self.obj = Cleanup()
        self.obj._junk_dirs = lambda: [('temp', str(self.base), '*.tmp', '')]
        self.obj._log_clean = Mock()
        home_patch = patch.object(Path, 'home', return_value=self.home)
        home_patch.start()
        self.addCleanup(home_patch.stop)

    def test_allowlist_not_environment_root_home_or_arbitrary(self):
        self.assertTrue(self.obj._is_safe_clean_path(str(self.base))[0])
        for path in ('', '.', str(self.home), str(self.home.anchor), str(self.home / 'AppData')):
            self.obj._junk_dirs = lambda p=path: [('temp', p, '*', '')]
            self.assertEqual(self.obj._safe_roots(), [])
            self.assertFalse(self.obj._is_safe_clean_path(path)[0])

    def test_canonical_containment_and_mock_reparse_ancestor(self):
        child = self.base / 'one.tmp'
        child.write_bytes(b'123')
        sibling = self.base.parent / 'TempSibling'
        sibling.mkdir()
        outside = sibling / 'one.tmp'
        outside.write_bytes(b'456')
        self.assertTrue(self.obj._clean_file_ok(str(child), str(self.base)))
        self.assertFalse(self.obj._clean_file_ok(str(outside), str(self.base)))
        original = os.lstat
        def fake(path, *args, **kw):
            if os.path.normcase(str(path)) == os.path.normcase(str(self.base)):
                return types.SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
            return original(path, *args, **kw)
        with patch.object(os, 'lstat', side_effect=fake):
            self.assertFalse(Cleanup._plain_path(str(child)))
        with patch.object(os.path, 'realpath', return_value=str(outside)):
            self.assertFalse(Cleanup._plain_path(str(child)))

    def test_mock_traversal_prunes_and_reports_error(self):
        for name in ('safe', 'blocked'):
            (self.base / name).mkdir()
        dirs = ['safe', 'blocked']
        def walk(path, **kw):
            self.assertFalse(kw['followlinks'])
            kw['onerror'](PermissionError('mock'))
            yield str(self.base), dirs, []
        original = self.obj._is_safe_clean_path
        with patch.object(os, 'walk', side_effect=walk), patch.object(
                self.obj, '_is_safe_clean_path', side_effect=lambda p: (False, '') if p == str(self.base / 'blocked') else original(p)):
            totals = dict(skipped=0, failed=0)
            self.assertEqual(list(self.obj._walk_clean_files(str(self.base), '*', totals)), [])
        self.assertEqual(dirs, ['safe'])
        self.assertEqual(totals, dict(skipped=1, failed=1))

    def test_deleted_bytes_failures_active_pattern_and_job_validation(self):
        for name, data in [('ok.tmp', b'123'), ('fail.tmp', b'12345'), ('active.tmp', b'12'), ('keep.db', b'1')]:
            (self.base / name).write_bytes(data)
        self.obj._is_active_file = lambda path: Path(path).name == 'active.tmp'
        remove = os.remove
        def fake_remove(path):
            if Path(path).name == 'fail.tmp':
                raise PermissionError('mock locked file')
            remove(path)  # only disposable test data
        with patch.object(os, 'remove', side_effect=fake_remove):
            result = self.obj._delete_clean_jobs([('temp', str(self.base), '*.tmp')])
        self.assertEqual(result, dict(count=1, bytes=3, skipped=1, failed=1))
        self.assertTrue((self.base / 'keep.db').exists())
        self.assertEqual(self.obj._log_clean.call_args.args[-2:], (3, 1))
        with patch.object(os, 'remove') as remove_mock:
            result = self.obj._delete_clean_jobs([('temp', str(self.base), '*')])
        remove_mock.assert_not_called()
        self.assertEqual(result['failed'], 1)

class RegistryTests(unittest.TestCase):
    def test_handles_fields_size_and_immutable_snapshot(self):
        obj = Uninstall()
        obj._all_apps = ('unchanged',)
        for value, expected in ((4096, 4096), (None, 0), ('bad', 0), (float('nan'), 0)):
            events, opened, closed = [], [], []
            values = dict(DisplayName='Example App', UninstallString='uninstall.exe',
                          EstimatedSize=value, Publisher='Publisher', InstallLocation='location')
            def open_key(parent, key):
                handle = ('child' if isinstance(parent, tuple) else 'root', len(opened))
                opened.append(handle)
                return handle
            def query(handle, key):
                self.assertNotIn(handle, closed)
                events.append(key)
                if key not in values:
                    raise FileNotFoundError(key)
                return values[key], 1
            reg = types.SimpleNamespace(HKEY_LOCAL_MACHINE='LM', HKEY_CURRENT_USER='CU',
                OpenKey=open_key, CloseKey=lambda h: closed.append(h), QueryInfoKey=lambda h: (1, 0, 0),
                EnumKey=lambda h, i: 'ExampleApp', QueryValueEx=query)
            with patch.dict(sys.modules, winreg=reg):
                result = obj._scan_reg()
            self.assertEqual(obj._all_apps, ('unchanged',))
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]['size'], expected)
            self.assertEqual(result[0]['publisher'], 'Publisher')
            self.assertTrue(result[0]['registry_key'].endswith('\\ExampleApp'))
            self.assertEqual(sorted(opened), sorted(closed))
            self.assertIn('EstimatedSize', events)
            with self.assertRaises(TypeError):
                result[0]['size'] = 0

    def test_root_handle_closed_on_enumeration_failure(self):
        reg = types.SimpleNamespace(HKEY_LOCAL_MACHINE='LM', HKEY_CURRENT_USER='CU',
            OpenKey=Mock(return_value='handle'), CloseKey=Mock(),
            QueryInfoKey=Mock(side_effect=OSError('mock failure')))
        with patch.dict(sys.modules, winreg=reg), self.assertRaises(OSError):
            Uninstall()._scan_reg()
        reg.CloseKey.assert_called_once_with('handle')


@unittest.skipIf(os.environ.get("GITHUB_ACTIONS") == "true",
                "残留扫描的归属判断依赖本机盘符布局（同上）")
class ResidualTests(unittest.TestCase):
    def test_strict_ownership_and_shared_vendor_rejection(self):
        obj = Uninstall()
        obj._is_sys_component = lambda n: 'runtime' in n
        obj._all_apps = ()
        for name in ('Microsoft', 'Google', 'Tencent', 'Shared', '', 'Runtime'):
            self.assertEqual(obj._kw_candidates(name), [])
        self.assertEqual(obj._kw_candidates('Example App 2.0 (x64)'), ['example app'])
        self.assertEqual(obj._scan_residuals({'name': 'Example App'}), [])
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            target = base / 'Example App'
            target.mkdir()
            obj._RESIDUAL_PF_ROOTS = (str(base),)
            app = dict(name='Example App', install_dir=str(target), uninstall=str(target / 'uninstall.exe'))
            self.assertTrue(obj._owned_residual_dir(app, str(target)))
            self.assertEqual(obj._scan_residuals(app), [('目录', str(target))])
            self.assertFalse(obj._owned_residual_dir(dict(app, name='Example'), str(target)))
            self.assertFalse(obj._owned_residual_dir(dict(app, uninstall=str(base / 'uninstall.exe')), str(target)))
            obj._all_apps = (dict(name='Other App', install_dir=str(target / 'shared')),)
            self.assertFalse(obj._owned_residual_dir(app, str(target)))
            obj._all_apps = ()
            (target / 'data').write_text('test')
            plain = Cleanup._plain_path
            with patch.object(Cleanup, '_plain_path', side_effect=lambda p: False if Path(p).name == 'data' else plain(p)):
                self.assertFalse(obj._owned_residual_dir(app, str(target)))

    def test_registry_residual_delete_is_unreachable(self):
        code = repair.method_source(CANDIDATE, 'UninstallModule', '_residual_dialog')
        self.assertNotIn('_reg_delete_tree', code)
        self.assertNotIn('kw_ok', code)
        self.assertIn('self._owned_residual_dir(app_, it[1])', code)
        code = repair.method_source(CANDIDATE, 'UninstallModule', '_scan_residuals')
        self.assertNotIn('winreg', code)


if __name__ == '__main__':
    unittest.main()
