# Accepted 250% hold trial, 2026-10-07

The operator reported that the latest run held the spindle well and chose this
setting as the starting point for the final tool-change implementation.
`last-hold-settings.json` confirms the actual first-bank settings:

| Setting | Original | CSP hold trial |
|---|---:|---:|
| Position proportional gain (2008:3) | 8.0 Hz | 20.0 Hz |
| Speed proportional gain (2008:1) | 20.0 Hz | 50.0 Hz |
| Speed integral time (2008:2) | 4.00 ms | 4.00 ms |

`last-hold.csv` contains 663 samples over 33.22 seconds, at about 20 Hz. In the
repository copy, line endings were normalized from CRLF to LF; all CSV fields
and rows are unchanged from the supplied file. In the first and last three
seconds the sampled motor-position error stayed within
4 raw encoder counts. Across the recording the error ranged from -13,860 to
+15,500 counts; the largest absolute reported motor torque was 67.1% of rated.
The sampled status word stayed `0x9637`, with no internal-limit-active sample.

The CSV covers manual pushes and releases with unknown force. Its peak error is
therefore not an absolute stiffness measurement or a controlled comparison with
earlier trials. It also cannot capture vibration above its sampling rate. The
selection is based on the operator's physical assessment together with the
recorded stable rest and absence of a sampled limit indication.
