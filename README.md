# SV670N stationary spindle hold

`hold` is enabled in this revision. The standalone disabled session has passed
on the target controller. The powered sequence has passed offline tests; its
first powered hardware run is still a commissioning test.

## Run on the target

Close PathPilot completely. Start with the spindle stationary and the
exchange arm clear of the spindle. Keep hands clear during the enable sequence
and keep the hardware E-stop accessible.

Replace the old folder contents with this package, then run from that folder:

```bash
bash ./spindle-test.sh check
bash ./spindle-test.sh hold
```

There is no requirement to repeat `disabled`. The hold launcher also performs
`check` itself. Run `hold` in an interactive terminal.

Wait for **CSP HOLD ENABLED** before assessing spindle rigidity. The command
holds the current position; it does not request a new angle or a tool change.

Press **Enter** or **Ctrl+C** in the hold terminal to stop. Alternatively, from
another terminal in the same folder:

```bash
bash ./spindle-test.sh off
```

Wait for **Spindle disabled; CSV mode 9 acknowledged; standalone session can
close.** and for the launcher to exit before reopening PathPilot. `off` is a
stop request, not a separate step needed after the hold terminal has closed.
If disable or mode acknowledgement is unavailable, use the hardware E-stop
and inspect the drive before restarting.

## Sequence and boundaries

The launcher checks the SV670N identity, settings and generated PDO mapping.
It refuses an existing PathPilot/HAL session and uses the target's stock PDO
generator without starting the full-mill drive manager. Only the spindle has
an enable control-word connection. Other drive control words and unconnected
I/O outputs remain zero.

The supervisor first confirms Switch On Disabled and CSV mode 9. It captures
the raw actual position as a fixed target, requests CSP mode 8, confirms the
new mode acknowledgement, and steps through Shutdown, Switch On and Operation
Enabled with status acknowledgement at each step. A captured target differing
from actual position by more than 1000 raw counts aborts before Operation
Enabled. The unverified raw velocity threshold has been removed. This test
assumes the operator starts with a stationary spindle.

Mode/state/interlock loss requests a stop. A realtime latch gates the spindle
control word on bus OP, STO feedback, drive fault, ATC air/VFD interlocks,
supervisor permit and a one-second heartbeat watchdog. A lost heartbeat or
interlock drops the control word to zero. Normal exit confirms disabled state
before requesting and acknowledging CSV mode 9. Hardware STO/E-stop remains
available independently of this software test.

No mask, gain, gearing or other tuning-parameter download is performed.
60FE:2 may be zero or 0x04010000 and is preserved. DO2 remains drive-controlled
ALM/contactor with 2004:3=11 and 2004:4=1. The gain-switchover PDO is low,
matching the supplied orient implementation. With a zero mask, no effective
forced P/PI override is assumed. Rigidity improvement is to be determined by
the test, not guaranteed by selecting CSP.

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
bash -n spindle-test.sh
```

Tests cover disabled operation, enable/disable handshakes, stale mode feedback
including an old mode-8 acknowledgement, captured-target movement, large raw
velocity with a stationary target, CSV restore acknowledgement, stop,
interlock/launcher loss, XML checks, interactive-terminal requirements,
sourcing protection and read failures. They do not establish physical drive
or realtime transport behavior.

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
