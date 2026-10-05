"""Motor error rollover, sampled peaks and throttled terminal output."""
import io
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
        self.assertEqual(stream.getvalue().count('Motor error:'), 1)
        clock[0] = .21
        r.sample(101, 100)
        self.assertEqual(r.peak, 25)
        self.assertIn('sampled peak:        25 counts', stream.getvalue())
        self.assertEqual(stream.getvalue().count('Motor error:'), 2)
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
        self.assertEqual(stream.getvalue().count('Motor error:'), 1)
        clock[0] = 1.01
        r.sample(100, 100)
        self.assertEqual(stream.getvalue().count('Motor error:'), 2)
        self.assertNotIn('\r', stream.getvalue())
        self.assertIn('sampled peak:        10 counts', stream.getvalue())
        r.finish()

if __name__ == '__main__':
    unittest.main()
