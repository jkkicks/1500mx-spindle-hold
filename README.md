# SV670N stationary spindle hold

The untuned CSP hold has passed on the target and improved restoring force.
Increasing position gain to 150% added return noise without noticeably reducing
deflection. This revision instead keeps the original position gain and trials
**125% of the original speed-loop gain and 75% of the original speed integral
time**, with a live motor-error/torque display. The speed-only trial gave no noticeable
holding improvement. The new P/I trial is offline-tested and still needs its
first hardware run.

## Run on the target

Close PathPilot completely. Start with the spindle stationary and the
exchange arm clear of the spindle. Keep hands clear during the enable sequence
and keep the hardware E-stop accessible.

Stop any running test, update the checkout, then run from its folder:

```bash
bash ./spindle-test.sh check
bash ./spindle-test.sh hold
```

There is no requirement to repeat `disabled`. The hold launcher also performs
`check` itself. Run `hold` in an interactive terminal.

Plain `hold` automatically reads the live first-bank speed gain (0x2008:1),
saves it locally, and applies **125% of that original value**, rounded to the
nearest raw count. A 20.0 Hz baseline becomes 25.0 Hz. The same hold also trials **75% of the
original speed integral time (0x2008:2)**: a 4.00 ms baseline becomes 3.00 ms.
Shortening this time strengthens integral action; it is not an increase to
position proportional gain. The position-gain boost has been removed: the original position gain is kept (8.0 Hz in the supplied
configuration). The original and trial speed gain/integral time and the
unchanged position gain are displayed at startup; no fixed baseline is assumed.
Second-bank gains, torque limits and filters are unchanged. No tuning arguments or manual SDO commands are needed.

Wait for **CSP HOLD ENABLED** before assessing spindle rigidity. The command
holds the current position; it does not request a new angle or a tool change.
Stop if the new gain produces buzzing, hunting or oscillation.

Press **Enter** or **Ctrl+C** in the hold terminal to stop. Alternatively, from
another terminal in the same folder:

```bash
bash ./spindle-test.sh off
```

Normal exit first prints **Original speed gain restored and verified** and
**Original integral time restored and verified**, then **Spindle disabled; CSV mode 9 acknowledged; standalone session can
close.** Wait for the launcher to exit before reopening PathPilot. `off` is a
stop request, not a separate step needed after the hold terminal has closed.
If disable or mode acknowledgement is unavailable, use the hardware E-stop
and inspect the drive before restarting.

Both original values are saved in `.position-gain-backup.json` before the first
SDO write. The legacy filename is retained so outstanding backups from the
position-only or speed-only trials are automatically recovered before starting
a new speed/integral trial. A normal stop, handled signal or setup failure
attempts to restore both values while disabled, before requesting CSV. Failed writes/readbacks
abort enable. Failed restoration retains the file, reports failure and does
not request CSV. Do not reopen PathPilot until restoration is confirmed.

Power loss or a forced kill cannot guarantee immediate restoration. Keep the
backup file: the next `hold` checks the drive identity/serial and recovers the
saved originals while disabled before starting a fresh trial. An unexpected
live gain or a different drive stops recovery rather than overwriting it.
Do not delete the file to bypass a recovery error. `disabled` does not recover
a pending tuning record. Repeated completed runs always start from the restored
baseline, so neither tuning adjustment compounds. A live integral time of
512.00 ms (integral disabled) or a trial below the documented minimum is
rejected before either setting is written.

## Sequence and boundaries

The launcher checks the SV670N identity, settings and generated PDO mapping.
It refuses an existing PathPilot/HAL session and uses the target's stock PDO
generator without starting the full-mill drive manager. Only the spindle has
an enable control-word connection. Other drive control words and unconnected
I/O outputs remain zero.

The supervisor first confirms Switch On Disabled and CSV mode 9. It captures
the raw actual position as a fixed target, requests CSP mode 8, confirms the
new mode acknowledgement, and steps through Shutdown, Switch On and Operation
Enabled with status acknowledgement at each step. Temporary tuning is applied
and verified before resetting the enable latch, with permit false and the drive
confirmed Switch On Disabled. A captured target differing
from actual position by more than 1000 raw counts aborts before Operation
Enabled. The unverified raw velocity threshold has been removed. This test
assumes the operator starts with a stationary spindle.

Mode/state/interlock loss requests a stop. A realtime latch gates the spindle
control word on bus OP, STO feedback, drive fault, ATC air/VFD interlocks,
supervisor permit and a one-second heartbeat watchdog. A lost heartbeat or
interlock drops the control word to zero. Normal exit confirms disabled state
and restores/verifies the original speed gain and integral time before requesting and
acknowledging CSV mode 9. Hardware STO/E-stop remains
available independently of this software test.

Only 0x2008:1 and 0x2008:2 are downloaded for this P/I trial and restoration. Recovery of
an outstanding old position-gain backup may also restore 0x2008:3. No
EEPROM-save command, mask, gearing or other tuning-parameter write is sent.
60FE:2 may be zero or 0x04010000 and is preserved. DO2 remains drive-controlled
ALM/contactor with 2004:3=11 and 2004:4=1. The gain-switchover PDO is low,
matching the supplied orient implementation. With a zero mask, no effective
forced P/PI override is assumed. Rigidity improvement is to be determined by
the test, not guaranteed by selecting CSP.

## Live motor-position error and actual torque

After CSP HOLD ENABLED the terminal updates one line:

```text
Motor err:     +125 ct | Tq:  -12.3% | Lim: N | Peak:      250 ct
```

Error is **actual position minus the fixed captured target**, with signed
32-bit counter rollover handled. The sign indicates direction. Torque is
the drive-reported actual motor torque (6077h), scaled as percent of rated
motor torque: raw 1000 means 100%. This is not spindle-side torque in Nm.
Lim is status-word bit 11, internal limit active; it can indicate limits other
than torque and does not establish saturation by itself. The sampled
peak is the largest absolute error seen during this hold, starting after
Operation Enabled; it resets for each run. Feedback is sampled at about 20 Hz
and displayed at 5 Hz in a terminal. Redirected output uses one line per second.
The peak is sampled, not a guaranteed capture of every transient.

The readout uses existing position and torque PDO feedback and performs no
SDO transactions while holding. The XML validator also requires feedback-torque
to map signed 6077h. No extra PDO mapping is added. It reports raw drive position counts, not spindle millimeters or
degrees; pulley/gearing conversion is deliberately omitted. It neither changes
the target nor adds a new stop threshold during the feel test.

If physical spindle movement is substantial while motor error stays small,
that points toward compliance or play between motor feedback and spindle.
If motor error rises with the movement, the servo loop is also yielding. This
readout does not measure spindle-side displacement or identify a specific
mechanical fault by itself.

### Short diagnostic test

Run the normal hold command. Wait for CSP HOLD ENABLED, leave it untouched
for about three seconds, apply moderate pressure at a consistent point for
three seconds, then release for three seconds. Repeat in the opposite direction.
Use the same leverage between tests; trying to find maximum force is not needed.
Press Enter to disable and restore.

`last-hold.csv` records elapsed time, actual/target positions, signed error,
signed actual torque (raw and percent rated), status word and internal-limit
flag at approximately 20 samples/second. It is flushed about once a second and
on normal stop. Each new powered hold overwrites this file, so copy a recording
you want to keep before running another test. It is ignored by Git.

This capture helps distinguish sustained position error, torque building or
plateauing, and physical spindle movement with little motor error. Torque near
the requested 300% ceiling while motor error grows suggests saturation.
A lower plateau can reflect another drive limit; Lim alone does not identify it.
Small motor error with visible spindle displacement points toward mechanical
compliance. Rising motor error with a delayed torque increase motivates checking
integral action, filtering and control selection.

The pressure is manually applied and not measured. Samples are userspace PDO
snapshots at about 20 Hz, not guaranteed same-cycle captures. The recording
cannot establish millisecond-scale loop latency or an absolute stiffness value.
If the first capture is inconclusive, a faster synchronous capture is the next
step. Torque reported by the drive is not an independent force measurement.

## Target and portability

Based on v2.15.0-EXATC-1: SV670N INT at bus 0, position 0, product 0x000c0130;
exchange-arm IO at alias 170. The actual generated XML is validated before
loading HAL and retained as last-ethercat.xml for diagnosis. XML HAL type names
may be uppercase or lowercase; indices, subindices and signedness must match.

The active runtime defaults to ~/tmc. Set PP_ROOT if a different runtime is
active. Its shipped HAL modules and Python environment are used. No compiler,
custom component, main-HAL edit or INI is required. The launcher exports
EMC2_BIN_DIR, EMC2_RTLIB_DIR and HAL_RTMOD_DIR to avoid baked development paths.

The physical two-speed pulley setup is not resolved by the archive, whose
spindle include lists SINGLE_SPEED=TRUE and 72:36 for both ranges. Capturing
6064 directly into 607A does not require a pulley-ratio conversion.

`disabled` remains an optional diagnostic: all control words stay zero, the
initial spindle mode is preserved, and position/velocity feedback is printed
before automatic exit. It needs no `off` command. `plan` runs offline. Hardware
commands cannot succeed in the simulator without physical EtherCAT devices.
Do not source the launcher; run it with bash.

## Verification

```bash
python3 test_offline.py
python3 test_launcher.py
python3 test_tuning.py
python3 test_readout.py
bash -n spindle-test.sh
```

Tests cover disabled operation, enable/disable handshakes, stale mode feedback
including an old mode-8 acknowledgement, captured-target movement, large raw
velocity with a stationary target, CSV restore acknowledgement, stop,
interlock/launcher loss, XML checks, interactive-terminal requirements,
sourcing protection and read failures. They do not establish physical drive
or realtime transport behavior. Tuning tests also cover durable backup before
writes, live-baseline scaling, readback failures, ambiguous-write recovery,
non-compounding retries, drive identity, external changes, disabled-state
requirements, restoration before CSV, and recovery of the old position-gain
and speed-only backup formats, second-write failures, partial restoration,
and disabled/out-of-range integral settings. Display tests cover signed error, counter rollover, sampled
peaks between display updates, terminal throttling, signed torque scaling,
limit flags, CSV sampling and redirected output. The trial factors are
`SPEED_GAIN_PERCENT = 125` and `INTEGRAL_TIME_PERCENT = 75` in tuning.py; later trials change those constants
in a reviewed revision rather than increasing it automatically on each run.

## Updating a Git checkout on the controller

Stop the standalone test before updating. From a cloned checkout, use:

```bash
git pull --ff-only
bash ./spindle-test.sh check
bash ./spindle-test.sh hold
```

Update the whole checkout together; do not mix scripts or HAL files from
separate revisions. `--ff-only` stops if the controller has a diverging local
commit instead of creating a merge. Generated mappings, logs and session state
are ignored by Git.
