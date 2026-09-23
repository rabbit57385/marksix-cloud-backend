"""Canonical production import identity, without package-directory path hacks."""
import ast
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from marksix_cloud_backend import analysis_engine, analysis_repository, main, statistics_core
from marksix_cloud_backend.tests.test_analysis_foundation import history
from marksix_cloud_backend.tests.test_database_updater import db_row

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parent


class ImportIdentityTests(unittest.TestCase):
    def test_shared_snapshot_identity_and_safety_guard(self):
        snapshot_type = analysis_repository.AnalysisSnapshot
        self.assertIs(analysis_engine.AnalysisSnapshot, snapshot_type)
        self.assertIs(main.AnalysisSnapshot, snapshot_type)
        self.assertIs(statistics_core.AnalysisSnapshot, snapshot_type)
        self.assertEqual(snapshot_type.__module__, 'marksix_cloud_backend.analysis_repository')
        with self.assertRaisesRegex(TypeError, 'history must be an AnalysisSnapshot'):
            analysis_engine.build_analysis_foundation(object())

    def test_real_dependency_repository_engine_endpoint(self):
        self.assertFalse(main.app.dependency_overrides)
        with patch.object(analysis_repository, 'connect_database') as connect:
            cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchall.return_value = [db_row(d) for d in history(101)]
            with patch.object(main, 'build_analysis_foundation', wraps=analysis_engine.build_analysis_foundation) as build:
                with TestClient(main.app) as client:
                    response = client.get('/api/v1/marksix/analysis')
            self.assertEqual(response.status_code, 200)
            build.assert_called_once()
            self.assertIs(type(build.call_args.args[0]), analysis_repository.AnalysisSnapshot)
            self.assertEqual(len(response.json()['numbers']), 49)
            connect.assert_called_once_with()
            cursor.execute.assert_called_once()

    def test_clean_canonical_process_without_internal_path(self):
        code = '''
import importlib, pathlib, sys
from marksix_cloud_backend import analysis_repository as repo, analysis_engine as engine, main
package = pathlib.Path(repo.__file__).resolve().parent
assert all(pathlib.Path(p or '.').resolve() != package for p in sys.path)
for file in package.glob('*.py'):
    if file.stem != '__init__':
        importlib.import_module('marksix_cloud_backend.' + file.stem)
        assert file.stem not in sys.modules
assert repo.AnalysisSnapshot is engine.AnalysisSnapshot is main.AnalysisSnapshot
from fastapi.testclient import TestClient
with TestClient(main.app) as client:
    assert client.get('/health').status_code == 200
'''
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_bare_entry_points_fail_before_creating_duplicate_snapshot(self):
        # The old single-file working directory must not load a second snapshot.
        code = '''
import importlib, sys
for name in ('analysis_repository', 'analysis_engine', 'main', 'statistics_core',
             'statistics_models', 'database', 'hkjc_client', 'update_marksix',
             'analysis_models', 'analysis_response'):
    try:
        importlib.import_module(name)
    except ImportError as exc:
        assert 'relative import' in str(exc), (name, str(exc))
    else:
        raise AssertionError('bare import unexpectedly succeeded: ' + name)
    assert name not in sys.modules
assert 'analysis_repository' not in sys.modules
'''
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=PACKAGE, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_production_imports_are_static_package_relative(self):
        local = {p.stem for p in PACKAGE.glob('*.py')}
        for path in PACKAGE.glob('*.py'):
            with self.subTest(module=path.name):
                tree = ast.parse(path.read_text(encoding='utf-8'))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        self.assertFalse(node.level == 0 and node.module.split('.')[0] in local)
                        self.assertNotIn(node.module.split('.')[0], {'sys', 'importlib'})
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            self.assertNotIn(alias.name.split('.')[0], local | {'sys', 'importlib'})
                    if isinstance(node, ast.Name):
                        self.assertNotIn(node.id, {'__package__', '__import__'})
                    if isinstance(node, ast.ExceptHandler) and node.type:
                        self.assertNotIn('ImportError', ast.unparse(node.type))


if __name__ == '__main__':
    unittest.main()
