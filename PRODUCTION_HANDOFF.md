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
