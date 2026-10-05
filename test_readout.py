"""Motor error rollover, sampled peaks and throttled terminal output."""
import io
import csv
import unittest
from hold import MotorErrorReadout, position_error


class LiveStream(io.StringIO):
    def isatty(self):
        return True


class ReadoutTests(unittest.TestCase):
    def test_signed_error_and_rollover(self):
        self.assertEqual(position_error(105, 100), 5)
        self.assertEqual(position_error(95, 100), -5)
        self.assertEqual(position_error(-2147483648, 2147483647), 1)
        self.assertEqual(position_error(2147483647, -2147483648), -1)

    def test_peak_includes_samples_between_display_updates(self):
        clock = [0.]
        stream = LiveStream()
        r = MotorErrorReadout(stream, lambda: clock[0])
        r.sample(100, 100)
        clock[0] = .05
        r.sample(75, 100)
        self.assertEqual(stream.getvalue().count('Motor err:'), 1)
        clock[0] = .21
        r.sample(101, 100)
        self.assertEqual(r.peak, 25)
        self.assertIn('Peak:       25 ct', stream.getvalue())
        self.assertEqual(stream.getvalue().count('Motor err:'), 2)
        self.assertNotIn('\n', stream.getvalue())
        r.finish()
        self.assertTrue(stream.getvalue().endswith('\n'))

    def test_redirected_output_uses_lines_and_one_second_interval(self):
        clock = [0.]
        stream = io.StringIO()
        r = MotorErrorReadout(stream, lambda: clock[0])
        r.sample(100, 100)
        clock[0] = .3
        r.sample(90, 100)
        self.assertEqual(stream.getvalue().count('Motor err:'), 1)
        clock[0] = 1.01
        r.sample(100, 100)
        self.assertEqual(stream.getvalue().count('Motor err:'), 2)
        self.assertNotIn('\r', stream.getvalue())
        self.assertIn('Peak:       10 ct', stream.getvalue())
        r.finish()

    def test_csv_samples_each_tick_with_signed_torque_and_limit_flag(self):
        clock = [10.]
        stream, log = io.StringIO(), io.StringIO()
        r = MotorErrorReadout(stream, lambda: clock[0], log)
        r.sample(100, 100, -123, 0x27)
        clock[0] = 10.05
        r.sample(110, 100, -3000, 0x827)
        r.finish()
        rows = list(csv.DictReader(io.StringIO(log.getvalue())))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['torque_percent'], '-12.3')
        self.assertEqual(rows[1]['time_s'], '0.050000')
        self.assertEqual(rows[1]['error_counts'], '10')
        self.assertEqual(rows[1]['internal_limit_active'], '1')
        self.assertEqual(rows[1]['torque_percent'], '-300.0')
        self.assertEqual(r.peak_torque, 3000)
        self.assertEqual(stream.getvalue().count('Motor err:'), 1)

if __name__ == '__main__':
    unittest.main()
