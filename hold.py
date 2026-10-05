#!/usr/bin/env python3
"""Stationary CSP hold supervisor; only shipped realtime HAL modules required."""
import os
import signal
import sys
import time

class StopRequested(Exception):
    pass

class HoldTest:
    def __init__(self, pins, sleep=time.sleep, clock=time.monotonic, parent_alive=lambda: True):
        self.p = pins
        self.sleep = sleep
        self.clock = clock
        self.parent_alive = parent_alive

    def tick(self):
        self.p['heartbeat'] = not self.p['heartbeat']
        self.sleep(.05)
        if self.p['stop'] or not self.parent_alive():
            raise StopRequested()

    def wait(self, predicate, description, timeout=5., check_health=False):
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            self.tick()
            if check_health and not self.p['allowed']:
                raise RuntimeError('Realtime stop latch opened during ' + description)
            if predicate():
                return
        raise RuntimeError('Timed out: ' + description)

    def pause(self, seconds, check_health=True):
        deadline = self.clock() + seconds
        while self.clock() < deadline:
            self.tick()
            if check_health and not self.p['allowed']:
                raise RuntimeError('Realtime stop latch opened')

    def enable(self):
        self.p['cw-request'] = 0
        self.p['mode-request'] = 9
        self.p['capture'] = False
        self.p['permit'] = True
        self.wait(lambda: self.p['oper'] and self.p['health'], 'bus/STO/ATC interlocks')
        self.wait(lambda: (self.p['status'] & 0x6f) == 0x40,
                  'initial Switch On Disabled')
        # Establish CSV feedback first, so an old CSP acknowledgement cannot
        # satisfy the subsequent mode-8 handshake. Raw velocity units are not
        # assumed; the operator starts with a stationary spindle.
        self.wait(lambda: self.p['mode-fb'] == 9, 'initial CSV acknowledgement')
        self.p['reset'] = True
        self.wait(lambda: self.p['allowed'], 'realtime stop latch reset')
        self.p['reset'] = False
        self.p['capture'] = True
        self.pause(.1)
        self.p['mode-request'] = 8
        self.wait(lambda: self.p['mode-fb'] == 8, 'CSP mode acknowledgement', check_health=True)
        # Normal CiA402 shutdown, switch-on, then enable-operation handshake.
        for word, expected in ((6, 0x21), (7, 0x23)):
            self.p['cw-request'] = word
            self.wait(lambda: (self.p['status'] & 0x6f) == expected,
                      'drive state 0x{:02x}'.format(expected), check_health=True)
        d = (self.p['actual'] - self.p['target'] + 2**31) % 2**32 - 2**31
        if abs(d) > 1000:
            raise RuntimeError('Spindle moved during setup; target will not be enabled')
        if self.p['mode-fb'] != 8:
            raise RuntimeError('CSP acknowledgement lost before enable')
        self.p['cw-request'] = 15
        self.wait(lambda: (self.p['status'] & 0x6f) == 0x27 and self.p['mode-fb'] == 8,
                  'CSP Operation Enabled', check_health=True)
        self.pause(.2)

    def hold(self):
        self.enable()
        print('CSP HOLD ENABLED. Press Enter in the launcher or run ./spindle-test.sh off.', flush=True)
        while True:
            self.tick()
            if not self.p['allowed'] or self.p['mode-fb'] != 8 or (self.p['status'] & 0x6f) != 0x27:
                raise RuntimeError('Holding interrupted by mode/state/interlock change')

    def disabled_only(self):
        self.p['cw-request'] = 0
        self.p['permit'] = False
        self.p['reset'] = False
        self.p['capture'] = False
        initial_mode = self.p['mode-request']
        self.wait(lambda: self.p['oper'] and (self.p['status'] & 0x6f) == 0x40,
                  'disabled PDO feedback', timeout=10.)
        start_position = previous_position = self.p['actual']
        low = high = largest_step = 0
        for _ in range(20):
            self.tick()
            if not self.p['oper'] or (self.p['status'] & 0x6f) != 0x40:
                raise RuntimeError('Disabled state or bus OP lost')
            offset = (self.p['actual'] - start_position + 2**31) % 2**32 - 2**31
            step = (self.p['actual'] - previous_position + 2**31) % 2**32 - 2**31
            low, high = min(low, offset), max(high, offset)
            largest_step = max(largest_step, abs(step))
            previous_position = self.p['actual']
            if self.p['mode-fb'] != initial_mode:
                raise RuntimeError('Mode feedback differs from preserved initial mode')
        print('DISABLED VALIDATION PASSED: status=0x{:04x}, mode={}, actual={}, target={}, velocity={}.'.format(
            self.p['status'], self.p['mode-fb'], self.p['actual'],
            self.p['target'], self.p['velocity']), flush=True)
        print('POSITION CHECK (~1 second, raw encoder counts): net={}, span={}, largest_sample_step={}.'.format(
            offset, high - low, largest_step), flush=True)
        print('All drive control words stayed zero. No CSP enable or mask change requested.', flush=True)

    def disable(self, restore_csv=True):
        # These outputs also drop the realtime latched control-word gate.
        self.p['cw-request'] = 0
        self.p['permit'] = False
        self.p['reset'] = False
        deadline = self.clock() + 3.
        while self.clock() < deadline:
            self.p['heartbeat'] = not self.p['heartbeat']
            self.sleep(.05)
            if self.p['oper'] and (self.p['status'] & 0x6f) == 0x40:
                if not restore_csv:
                    return True
                self.p['mode-request'] = 9
                # Mode acknowledgement may lag. Normal PP reinitializes it too.
                deadline2 = self.clock() + 1.
                while self.clock() < deadline2 and self.p['mode-fb'] != 9:
                    self.sleep(.05)
                return self.p['mode-fb'] == 9
        return False

def main():
    if sys.argv[1:] not in (['--disabled'], ['--hold']):
        sys.exit('Use the launcher: check | disabled | hold | off')
    powered = sys.argv[1:] == ['--hold']
    import hal
    c = hal.component('csp-test-ui')
    inputs = [('begin', hal.HAL_BIT), ('stop', hal.HAL_BIT),
              ('actual', hal.HAL_S32), ('target', hal.HAL_S32),
              ('mode-fb', hal.HAL_S32), ('status', hal.HAL_U32),
              ('velocity', hal.HAL_S32), ('oper', hal.HAL_BIT),
              ('health', hal.HAL_BIT), ('allowed', hal.HAL_BIT)]
    outputs = [('heartbeat', hal.HAL_BIT), ('permit', hal.HAL_BIT),
               ('reset', hal.HAL_BIT), ('capture', hal.HAL_BIT),
               ('cw-request', hal.HAL_U32), ('mode-request', hal.HAL_S32)]
    for name, typ in inputs: c.newpin(name, typ, hal.HAL_IN)
    for name, typ in outputs: c.newpin(name, typ, hal.HAL_OUT)
    c['mode-request'] = int(os.environ.get('CSP_INITIAL_MODE', '9'))
    c.ready()
    def interrupted(signum, frame):
        c['stop'] = True
        raise StopRequested()
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    launcher_pid = int(os.environ.get('CSP_LAUNCHER_PID', os.getppid()))
    parent_alive = lambda: os.getppid() == launcher_pid
    test = HoldTest(c, parent_alive=parent_alive)
    started = False
    result = 0
    try:
        deadline = time.monotonic() + 30
        while not c['begin']:
            if c['stop'] or not parent_alive(): raise StopRequested()
            if time.monotonic() > deadline: raise RuntimeError('HAL setup did not complete')
            time.sleep(.05)
        started = True
        if powered:
            test.hold()
        else:
            test.disabled_only()
    except StopRequested:
        pass
    except Exception as exc:
        print('Test stopped: ' + str(exc), file=sys.stderr, flush=True)
        result = 1
    finally:
        # During cleanup ignore repeated TERM/INT and finish disable handshake.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        if started:
            if test.disable(restore_csv=powered):
                print('Spindle disabled{}; standalone session can close.'.format(
                    '; CSV mode 9 acknowledged' if powered else ''), flush=True)
            else:
                print('Disable or mode-restore acknowledgement unavailable. Use hardware E-stop; inspect drive before restarting.', file=sys.stderr, flush=True)
                result = 1
        c.exit()
    return result

if __name__ == '__main__':
    sys.exit(main())
