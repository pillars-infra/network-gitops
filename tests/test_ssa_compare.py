import sys
from pathlib import Path
import unittest
root = next(p for p in Path(__file__).resolve().parents if (p/'operations/releases/ssa_compare.py').exists())
sys.path.insert(0, str(root/'operations/releases'))
from ssa_compare import retry_read_conflict, safe_failure_reason

class CompareRetryTest(unittest.TestCase):
    def test_reloads_live_read_on_version_race(self):
        reads = []
        def project():
            reads.append(len(reads))
            if len(reads) < 2: raise RuntimeError('the object has been modified; latest version')
            return False
        self.assertFalse(retry_read_conflict(project))
        self.assertEqual(len(reads), 2)

    def test_repeated_races_stop_after_three_reads(self):
        reads = []
        def project():
            reads.append(1)
            raise RuntimeError('the object has been modified')
        with self.assertRaises(RuntimeError): retry_read_conflict(project)
        self.assertEqual(len(reads), 3)

    def test_field_conflicts_and_auth_are_never_retried(self):
        for message in ('conflict with field manager', 'Forbidden', 'timed out'):
            reads = []
            def project():
                reads.append(1)
                raise RuntimeError(message)
            with self.assertRaises(RuntimeError): retry_read_conflict(project)
            self.assertEqual(len(reads), 1)

    def test_safe_reason_never_exposes_error_payload(self):
        self.assertEqual(safe_failure_reason(RuntimeError('conflict with manager: private-value')), 'SSA field ownership conflict')
