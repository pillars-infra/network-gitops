import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'operations/releases'))
import ssa_executor

class ApplyOnlyCliTest(unittest.TestCase):
    def test_flag_reaches_executor_and_keeps_default(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root/'contract').write_text('{}')
                (root/'operation').write_text('{}')
                argv = ['ssa_executor', '--contract', str(root/'contract'), '--operation', str(root/'operation'), '--bundle', str(root/'bundle'), '--state-dir', str(root/'state')]
                if enabled: argv.append('--apply-only')
                def reconcile(executor, *args, **kwargs):
                    self.assertEqual(executor.apply_only, enabled)
                    return {'outcome': 'applied' if enabled else 'healthy'}
                with patch.object(sys, 'argv', argv), patch.object(ssa_executor.Executor, 'reconcile', reconcile), patch('builtins.print'):
                    self.assertEqual(ssa_executor.main(), 0)
