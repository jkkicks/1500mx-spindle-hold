# Starting point for PathPilot tool-change integration

The target 1500MX has an SV670N INT spindle drive at EtherCAT bus 0, position 0.
The accepted standalone run used first-bank position gain 20.0 Hz (2008:3),
speed gain 50.0 Hz (2008:1), and unchanged speed integral time 4.00 ms
(2008:2). These are target-machine values, not a blanket 250% recommendation
for other drives. The test uses a stationary motor-position target; it does not
validate an M19 angle or movement of the side-mount tool changer.

For the integrated implementation:

1. Give one controller exclusive ownership of spindle mode, control word,
   position target, and gain settings during the orient/tool-change window.
   Enter only after the spindle has stopped and the machine permits a tool
   change. Keep the existing STO, EtherCAT, drive-fault, air, and ATC interlocks.
2. Capture a current position target before enabling CSP, or compute a bounded
   target for the requested orient angle. The motor encoder alone cannot prove
   spindle-side angle or stiffness through the two-speed pulley; validate the
   mapping and holding behavior in both pulley configurations.
3. Clear the prior orient-complete state and establish a fresh mode transition.
   Verify CSV mode 9 before requesting CSP mode 8, then verify mode 8 and the
   new CiA 402 state sequence before authorizing arm motion. A status bit left
   high from the previous mode or previous tool change must not count as this
   transition's completion.
4. Apply the tuned gain pair only for the intended orient/tool-change window.
   Read and save the live originals before changing them; this test writes them
   while the drive is Switch On Disabled and verifies each SDO readback.
   Restore and verify the originals while disabled before returning to CSV and
   allowing normal spindle operation. Retain durable recovery state across a
   process crash or power loss, as `tuning.py` does for the standalone test.
5. Define an abort path for lost mode, bus, interlock, or controller heartbeat:
   remove torque enable, stop ATC motion, and require a verified gain/mode
   recovery before another spindle command. Confirm with an actual arm load and
   repeated tool changes in each pulley configuration; the hand test alone
   establishes neither orient accuracy nor changer reliability.

The standalone `hold.py` and `hold.hal` demonstrate the fixed-target CSP
handshake, interlock gate, and restore journal. They run with PathPilot closed
and are not an integrated tool-change component. The accepted raw run is in
[`evidence/2026-10-07-250pct`](evidence/2026-10-07-250pct/).

## Drive tuning history and proposed INI keys

This SV670N has nested position and speed loops, rather than one external PID
block. These are the first-bank drive parameters we actually changed during
the standalone trials (Hz and ms are engineering units, not raw SDO integers):

| Trial | Position P, 2008:3 | Speed P, 2008:1 | Speed integral time, 2008:2 | Reported result |
|---|---:|---:|---:|---|
| Untuned CSP | 8.0 Hz | 20.0 Hz | 4.00 ms | Much more restoring force than the prior orient behavior |
| Position P only | 10.0, then 12.0 Hz | 20.0 Hz | 4.00 ms | Little stiffness gain; 12.0 Hz added return noise |
| Speed P only | 8.0 Hz | 25.0 Hz | 4.00 ms | Little stiffness gain |
| Speed P plus stronger I | 8.0 Hz | 25.0 Hz | 3.00 ms | Rest readout steadier; little stiffness gain |
| Coordinated P | 16.0 Hz | 40.0 Hz | 4.00 ms | Clear stiffness improvement |
| Accepted coordinated P | 20.0 Hz | 50.0 Hz | 4.00 ms | Operator's preferred starting tune |

For commissioning, expose the **two absolute proportional gains** as the main
INI knobs. Make speed integral time an optional advanced knob, since the
accepted run left it at the drive's original 4.00 ms and the 3.00 ms trial did
not materially improve holding. A proposed new section is:

```ini
[SPINDLE_CSP_HOLD]
POSITION_GAIN_HZ = 20.0
SPEED_GAIN_HZ = 50.0
# Optional advanced key; omission preserves the live value.
# SPEED_INTEGRAL_TIME_MS = 4.00
```

These keys are a design for the future integrated component; the standalone
script does not parse them. Use absolute targets so a change to the normal
spindle tune cannot silently multiply the hold gains. Validate units and drive
range, save the live values, write and verify the hold values while disabled,
and restore the saved values on every exit. If the optional integral key is
omitted, leave 2008:2 untouched. Keep any position/speed gain adjustments
coordinated, as the [SV670-INT parameter guide](https://portal-file.inovance.com/owfile/ProdDoc/SC/PS00009762_PDF_EN/A00/SV670-INT%20Series%20Servo%20Drive%20Parameter%20Guide-EN-A00.PDF)
recommends for position mode.

The pre-existing `[SPINDLE] P`, `I`, `D`, `P2`, and similar PathPilot INI keys
belong to a different spindle-orient control path; this SV670N experiment did
not change them. There was no derivative-gain trial. Keep the 3000 forward and
reverse PDO torque limits, feedforward values, filters, second-bank gains,
2008:9 gain-mode selection, and 60FE output mask out of the routine tuning
section. The torque limits already matched the supplied mill HAL, and the
accepted recording did not show a sampled internal-limit indication.
