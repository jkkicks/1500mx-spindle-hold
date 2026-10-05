"""Exercise gain-write failure/recovery and hold sequencing without hardware."""
import os
import shutil
import tempfile
import unittest
from tuning import PositionGainTuner
from test_offline import Fake
from hold import HoldTest


class Drive:
    def __init__(self):
        self.position_gain = 80
        self.status = 0x40
        self.serial = 123
        self.writes = []
        self.events = []
        self.fail_download_after_write = False
        self.ignore_download = False

    def read(self, datatype, index, subindex):
        self.events.append(('read', index, subindex))
        if index == '0x1018':
            return {1: 0x100000, 2: 0xc0130, 4: self.serial}[subindex]
        if index == '0x6041':
            return self.status
        if index == '0x2008':
            return {3: self.position_gain, 9: 0}[subindex]
        raise AssertionError('Unexpected SDO read')

    def write(self, datatype, index, subindex, value):
        self.writes.append((index, subindex, value))
        self.assert_backup_exists()
        if not self.ignore_download:
            self.position_gain = value
        if self.fail_download_after_write:
            self.fail_download_after_write = False
            raise RuntimeError('Ambiguous download failure')


class TuningTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.path = os.path.join(self.root, '.position-gain-backup.json')
        self.drive = Drive()
        self.drive.assert_backup_exists = lambda: self.assertTrue(os.path.exists(self.path))
        self.tuner = PositionGainTuner(self.path, self.drive)

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_live_baseline_and_verified_restore(self):
        self.drive.position_gain = 120
        self.tuner.apply()
        self.assertEqual(self.drive.position_gain, 180)
        self.assertTrue(os.path.exists(self.path))
        self.tuner.restore()
        self.assertEqual(self.drive.position_gain, 120)
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(self.drive.writes, [('0x2008', 3, 180), ('0x2008', 3, 120)])

    def test_recover_ambiguous_write(self):
        self.drive.fail_download_after_write = True
        with self.assertRaises(RuntimeError):
            self.tuner.apply()
        self.assertEqual(self.drive.position_gain, 120)
        self.assertTrue(os.path.exists(self.path))
        PositionGainTuner(self.path, self.drive).restore()
        self.assertEqual(self.drive.position_gain, 80)
        self.assertFalse(os.path.exists(self.path))

    def test_interrupted_run_does_not_compound_gain(self):
        self.tuner.apply()
        PositionGainTuner(self.path, self.drive).apply()
        self.assertEqual(self.drive.position_gain, 120)
        self.assertEqual([w[2] for w in self.drive.writes], [120, 80, 120])

    def test_enabled_drive_refuses_write(self):
        self.drive.status = 0x27
        with self.assertRaises(RuntimeError):
            self.tuner.apply()
        self.assertEqual(self.drive.writes, [])

    def test_readback_mismatch_keeps_backup(self):
        self.drive.ignore_download = True
        with self.assertRaises(RuntimeError):
            self.tuner.apply()
        self.assertTrue(os.path.exists(self.path))
        self.tuner.restore()
        self.assertFalse(os.path.exists(self.path))

    def test_restore_failure_keeps_backup(self):
        self.tuner.apply()
        self.drive.ignore_download = True
        with self.assertRaises(RuntimeError):
            self.tuner.restore()
        self.assertTrue(os.path.exists(self.path))

    def test_wrong_drive_refuses_restore(self):
        self.tuner.apply()
        self.drive.serial += 1
        with self.assertRaises(RuntimeError):
            self.tuner.restore()
        self.assertTrue(os.path.exists(self.path))
        self.assertEqual(len(self.drive.writes), 1)

    def test_external_change_is_not_overwritten(self):
        self.tuner.apply()
        self.drive.position_gain = 99
        with self.assertRaises(RuntimeError):
            self.tuner.restore()
        self.assertTrue(os.path.exists(self.path))
        self.assertEqual(len(self.drive.writes), 1)

    def test_range_failure_makes_no_write(self):
        self.drive.position_gain = 19000
        with self.assertRaises(RuntimeError):
            self.tuner.apply()
        self.assertEqual(self.drive.writes, [])

    def test_restore_before_csv_and_failure_blocks_csv(self):
        f = Fake()
        events = []
        class Tuner:
            def apply(inner):
                self.assertEqual(f.p['status'], 0x40)
                self.assertFalse(f.p['permit'])
                events.append('apply')
            def restore(inner):
                self.assertEqual(f.p['status'], 0x40)
                self.assertEqual(f.p['mode-request'], 8)
                self.assertFalse(f.p['permit'])
                events.append('restore')
                raise RuntimeError('Restore failed')
        t = HoldTest(f.p, f.sleep, lambda: f.now, tuner=Tuner())
        t.enable()
        with self.assertRaises(RuntimeError):
            t.disable()
        self.assertEqual(events, ['apply', 'restore'])
        self.assertEqual(f.p['status'], 0x40)
        self.assertEqual(f.p['mode-request'], 8)

    def test_apply_failure_never_enables(self):
        f = Fake()
        class Tuner:
            def apply(inner):
                raise RuntimeError('Tuning failed')
        t = HoldTest(f.p, f.sleep, lambda: f.now, tuner=Tuner())
        with self.assertRaises(RuntimeError):
            t.enable()
        self.assertNotIn(15, f.words)
        self.assertFalse(f.p['permit'])

if __name__ == '__main__':
    unittest.main()
