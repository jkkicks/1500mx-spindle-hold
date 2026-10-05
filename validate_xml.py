#!/usr/bin/env python3
"""Reject a generated bus map that does not match this target configuration."""
import sys
import xml.etree.ElementTree as ET

def validate(path):
    root = ET.parse(path).getroot()
    masters = root.findall('master')
    if len(masters) != 1 or int(masters[0].get('idx', '-1')) != 0:
        raise ValueError('Expected one master, index 0')
    if int(masters[0].get('appTimePeriod', '0')) != 1000000:
        raise ValueError('Expected 1 ms bus period')
    slaves = masters[0].findall('slave')
    spindle = [s for s in slaves if int(s.get('idx', '-1')) == 0 and int(s.get('alias', '0')) == 0]
    if len(spindle) != 1:
        raise ValueError('Expected unaliased spindle at position 0')
    s = spindle[0]
    if int(s.get('vid', '0'), 0) != 0x100000 or int(s.get('pid', '0'), 0) != 0xc0130:
        raise ValueError('Spindle identity does not match SV670N INT')
    mapping = dict((e.get('halPin'), (int(e.get('idx', '0'), 0), int(e.get('subIdx', '0'), 0), (e.get('halType') or '').lower()))
                   for e in s.iter('pdoEntry') if e.get('halPin'))
    expected = {'command-position': (0x607a, 0, 's32'), 'feedback-position': (0x6064, 0, 's32'),
                'control-word': (0x6040, 0, 'u32'), 'status-word': (0x6041, 0, 'u32'),
                'command-mode': (0x6060, 0, 's32'), 'feedback-drive-mode': (0x6061, 0, 's32'),
                'ff-velocity': (0x60b1, 0, 's32'), 'ff-torque': (0x60b2, 0, 's32'),
                'feedback-velocity': (0x606c, 0, 's32'),
                'command-torque-limit-fw': (0x60e0, 0, 'u32'),
                'command-torque-limit-rev': (0x60e1, 0, 'u32')}
    for name, value in expected.items():
        if mapping.get(name) != value:
            raise ValueError('Unexpected PDO mapping/type: {}: expected {!r}, got {!r}'.format(name, value, mapping.get(name)))
    bits = set(e.get('halPin') for e in s.iter('complexEntry'))
    if not {'edm', 'sw03-fault', 'do1', 'gain-switchover'}.issubset(bits):
        raise ValueError('Missing spindle safety/P-PI/output pins')
    io = [s for s in slaves if int(s.get('alias', '0')) == 170]
    if len(io) != 1 or int(io[0].get('vid', '0'), 0) != 0x100000 or int(io[0].get('pid', '0'), 0) != 0x10f40912:
        raise ValueError('Expected target exchange-arm IO at alias 170')
    bits = set(e.get('halPin') for e in io[0].iter('complexEntry'))
    if not {'atc-air-pressure', 'mag-vfd-fault', 'arm-vfd-fault'}.issubset(bits):
        raise ValueError('Missing exchange-arm interlock pins')

if __name__ == '__main__':
    try:
        validate(sys.argv[1])
    except Exception as exc:
        sys.exit('Bus configuration rejected: ' + str(exc))
