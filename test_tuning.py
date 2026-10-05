"""Exercise gain-write failure/recovery and hold sequencing without hardware."""
import os
import json
import shutil
import tempfile
import unittest
from tuning import GainTuner
from test_offline import Fake
from hold import HoldTest


class Drive:
    def __init__(self):
        self.position_gain = 80
        self.speed_gain = 200
        self.integral_time = 400
        self.status = 0x40
        self.serial = 123
        self.writes = []
        self.events = []
        self.fail_download_after_write = False
        self.ignore_download = False
        self.ignore_subindex = None
        self.fail_on_subindex = None

    def read(self, datatype, index, subindex):
        self.events.append(('read', index, subindex))
        if index == '0x1018':
            return {1: 0x100000, 2: 0xc0130, 4: self.serial}[subindex]
        if index == '0x6041':
            return self.status
        if index == '0x2008':
            return {1: self.speed_gain, 2: self.integral_time, 3: self.position_gain, 9: 0}[subindex]
        raise AssertionError('Unexpected SDO read')

    def write(self, datatype, index, subindex, value):
        self.writes.append((index, subindex, value))
        self.assert_backup_exists()
        if not self.ignore_download and subindex != self.ignore_subindex:
            if subindex == 1:
                self.speed_gain = value
            elif subindex == 2:
                self.integral_time = value
            elif subindex == 3:
                self.position_gain = value
            else:
                raise AssertionError('Unexpected SDO write')
        if self.fail_download_after_write or subindex == self.fail_on_subindex:
            self.fail_download_after_write = False
            self.fail_on_subindex = None
            raise RuntimeError('Ambiguous download failure')


class TuningTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.path = os.path.join(self.root, '.position-gain-backup.json')
        self.drive = Drive()
        self.drive.assert_backup_exists = lambda: self.assertTrue(os.path.exists(self.path))
        self.tuner = GainTuner(self.path, self.drive)

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_live_baseline_and_verified_restore(self):
        self.drive.speed_gain = 240
        self.tuner.apply()
        self.assertEqual(self.drive.speed_gain, 300)
        self.assertTrue(os.path.exists(self.path))
        self.tuner.restore()
        self.assertEqual(self.drive.speed_gain, 240)
        self.assertEqual(self.drive.position_gain, 80)
        self.assertEqual(self.drive.integral_time, 400)
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(self.drive.writes, [('0x2008', 1, 300), ('0x2008', 2, 300),
                                            ('0x2008', 2, 400), ('0x2008', 1, 240)])

    def test_recover_ambiguous_write(self):
        self.drive.fail_download_after_write = True
        with self.assertRaises(RuntimeError):
            self.tuner.apply()
        self.assertEqual(self.drive.speed_gain, 250)
        self.assertTrue(os.path.exists(self.path))
        GainTuner(self.path, self.drive).restore()
        self.assertEqual(self.drive.speed_gain, 200)
        self.assertFalse(os.path.exists(self.path))

    def test_interrupted_run_does_not_compound_gain(self):
        self.tuner.apply()
        GainTuner(self.path, self.drive).apply()
        self.assertEqual(self.drive.speed_gain, 250)
        self.assertEqual([w[2] for w in self.drive.writes], [250, 300, 400, 200, 250, 300])

    def test_old_position_backup_recovered_before_speed_trial(self):
        self.drive.position_gain = 120
        record = dict(version=1, identity=[0x100000, 0xc0130, self.drive.serial],
                      original=80, trial=120)
        with open(self.path, 'w') as f:
            json.dump(record, f)
        self.tuner.apply()
        self.assertEqual(self.drive.position_gain, 80)
        self.assertEqual(self.drive.speed_gain, 250)
        self.assertEqual(self.drive.writes, [('0x2008', 3, 80), ('0x2008', 1, 250), ('0x2008', 2, 300)])
        self.tuner.restore()
        self.assertEqual(self.drive.speed_gain, 200)
        self.assertEqual(self.drive.position_gain, 80)

    def test_old_speed_backup_recovered_before_combined_trial(self):
        self.drive.speed_gain = 250
        record = dict(version=2, identity=[0x100000, 0xc0130, self.drive.serial],
                      original=200, trial=250)
        with open(self.path, 'w') as f:
            json.dump(record, f)
        self.tuner.apply()
        self.assertEqual(self.drive.speed_gain, 250)
        self.assertEqual(self.drive.integral_time, 300)
        self.assertEqual(self.drive.writes[0], ('0x2008', 1, 200))
        self.tuner.restore()
        self.assertEqual(self.drive.speed_gain, 200)
        self.assertEqual(self.drive.integral_time, 400)

    def test_second_write_failure_restores_both_originals(self):
        self.drive.fail_on_subindex = 2
        with self.assertRaises(RuntimeError):
            self.tuner.apply()
        self.assertEqual(self.drive.speed_gain, 250)
        self.assertEqual(self.drive.integral_time, 300)
        with open(self.path) as f:
            record = json.load(f)
        self.assertEqual([e['original'] for e in record['entries']], [200, 400])
        self.tuner.restore()
        self.assertEqual(self.drive.speed_gain, 200)
        self.assertEqual(self.drive.integral_time, 400)
        self.assertFalse(os.path.exists(self.path))

    def test_partial_restore_can_be_retried(self):
        self.tuner.apply()
        self.drive.ignore_subindex = 1
        with self.assertRaises(RuntimeError):
            self.tuner.restore()
        self.assertEqual(self.drive.integral_time, 400)
        self.assertEqual(self.drive.speed_gain, 250)
        self.assertTrue(os.path.exists(self.path))
        self.drive.ignore_subindex = None
        self.tuner.restore()
        self.assertEqual(self.drive.speed_gain, 200)
        self.assertFalse(os.path.exists(self.path))

    def test_nondefault_integral_baseline(self):
        self.drive.integral_time = 800
        self.tuner.apply()
        self.assertEqual(self.drive.integral_time, 600)
        self.tuner.restore()
        self.assertEqual(self.drive.integral_time, 800)

    def test_disabled_or_too_small_integral_refuses_all_writes(self):
        for value in (51200, 15):
            self.drive.integral_time = value
            with self.assertRaises(RuntimeError):
                self.tuner.apply()
            self.assertEqual(self.drive.writes, [])
            self.assertFalse(os.path.exists(self.path))

    def test_external_integral_change_prevents_any_restore_write(self):
        self.tuner.apply()
        self.drive.integral_time = 350
        with self.assertRaises(RuntimeError):
            self.tuner.restore()
        self.assertEqual(len(self.drive.writes), 2)
        self.assertEqual(self.drive.speed_gain, 250)
        self.assertTrue(os.path.exists(self.path))

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
        self.assertEqual(len(self.drive.writes), 2)

    def test_external_change_is_not_overwritten(self):
        self.tuner.apply()
        self.drive.speed_gain = 249
        with self.assertRaises(RuntimeError):
            self.tuner.restore()
        self.assertTrue(os.path.exists(self.path))
        self.assertEqual(len(self.drive.writes), 2)

    def test_range_failure_makes_no_write(self):
        self.drive.speed_gain = 19000
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
