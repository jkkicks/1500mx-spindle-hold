"""Run without importing HAL or touching hardware."""
import unittest
import tempfile
import os
import xml.etree.ElementTree as ET
from hold import HoldTest, StopRequested
from validate_xml import validate

class Fake:
    def __init__(self):
        self.now = 0.
        self.p = dict((n, 0) for n in ('heartbeat','stop','cw-request','mode-request',
                      'permit','reset','capture','velocity','allowed','target'))
        self.p.update(actual=123456, oper=True, health=True, status=0x40, **{'mode-fb':9})
        self.words = []
        self.stale_mode = False
        self.move_during_setup = False
        self.was_captured = False
    def sleep(self, dt):
        self.now += dt
        if not self.p['capture']: self.p['target'] = self.p['actual']
        elif self.move_during_setup and not self.was_captured:
            self.p['actual'] += 2000
        self.was_captured = self.p['capture']
        if self.p['reset'] and self.p['health']: self.p['allowed'] = True
        if not self.p['permit'] or not self.p['health']: self.p['allowed'] = False
        if not self.stale_mode: self.p['mode-fb'] = self.p['mode-request']
        word = self.p['cw-request'] if self.p['allowed'] else 0
        self.words.append(word)
        self.p['status'] = {0:0x40,6:0x21,7:0x23,15:0x27}[word]
    def test(self, parent_alive=lambda: True):
        return HoldTest(self.p, self.sleep, lambda:self.now, parent_alive)

class SequenceTests(unittest.TestCase):
    def test_disabled_only_never_enables_or_changes_mode(self):
        f=Fake();f.p['mode-request']=8;f.p['mode-fb']=8;t=f.test()
        t.disabled_only()
        self.assertTrue(t.disable(restore_csv=False))
        self.assertTrue(all(w==0 for w in f.words))
        self.assertEqual(f.p['mode-request'],8)
        self.assertFalse(f.p['permit'])

    def test_enable_and_disable(self):
        f=Fake();t=f.test();t.enable()
        self.assertEqual(f.p['status'],0x27)
        self.assertEqual(f.p['target'],123456)
        f.p['actual']+=500
        t.pause(.2)
        self.assertEqual(f.p['target'],123456)
        self.assertTrue(t.disable())
        self.assertEqual(f.p['status'],0x40)
        self.assertEqual(f.p['mode-fb'],9)
    def test_stale_mode_never_enables(self):
        f=Fake();f.stale_mode=True;t=f.test()
        with self.assertRaises(RuntimeError):t.enable()
        self.assertNotIn(15,f.words)
        self.assertTrue(t.disable())
    def test_large_raw_velocity_does_not_block_stationary_target(self):
        f=Fake();f.p['velocity']=64000;t=f.test();t.enable()
        self.assertEqual(f.p['status'],0x27)
        self.assertEqual(f.p['target'],f.p['actual'])
        self.assertTrue(t.disable())

    def test_stale_csp_requires_csv_round_trip(self):
        f=Fake();f.p['mode-fb']=8;f.stale_mode=True;t=f.test()
        with self.assertRaises(RuntimeError):t.enable()
        self.assertNotIn(15,f.words)

    def test_csv_restore_requires_acknowledgement(self):
        f=Fake();t=f.test();t.enable();f.stale_mode=True
        self.assertFalse(t.disable())
        self.assertEqual(f.p['status'],0x40)

    def test_moved_target_never_enables(self):
        f=Fake();f.move_during_setup=True;t=f.test()
        with self.assertRaises(RuntimeError):t.enable()
        self.assertNotIn(15,f.words)
        self.assertTrue(t.disable())
    def test_interlock_loss(self):
        f=Fake();t=f.test();t.enable();f.p['health']=False
        with self.assertRaises(RuntimeError):t.pause(.2)
        self.assertEqual(f.words[-1],0)
    def test_parent_loss(self):
        f=Fake();t=f.test(parent_alive=lambda:False)
        with self.assertRaises(StopRequested):t.enable()
        self.assertNotIn(15,f.words)
    def test_stop(self):
        f=Fake();t=f.test();f.p['stop']=True
        with self.assertRaises(StopRequested):t.enable()
        self.assertTrue(t.disable())

class XmlTests(unittest.TestCase):
    def fixture(self):
        root=ET.Element('masters');m=ET.SubElement(root,'master',idx='0',appTimePeriod='1000000')
        s=ET.SubElement(m,'slave',idx='0',alias='0',vid=str(0x100000),pid=str(0xc0130))
        entries=[('command-position',0x607a,'s32'),('feedback-position',0x6064,'s32'),
                 ('control-word',0x6040,'u32'),('status-word',0x6041,'u32'),
                 ('command-mode',0x6060,'s32'),('feedback-drive-mode',0x6061,'s32'),
                 ('ff-velocity',0x60b1,'s32'),('ff-torque',0x60b2,'s32'),
                 ('feedback-velocity',0x606c,'s32'),('command-torque-limit-fw',0x60e0,'u32'),
                 ('command-torque-limit-rev',0x60e1,'u32')]
        for name,ix,typ in entries:ET.SubElement(s,'pdoEntry',halPin=name,idx=str(ix),subIdx='0',halType=typ)
        for name in ('edm','sw03-fault','do1','gain-switchover'):ET.SubElement(s,'complexEntry',halPin=name)
        io=ET.SubElement(m,'slave',idx='0',alias='170',vid=str(0x100000),pid=str(0x10f40912))
        for name in ('atc-air-pressure','mag-vfd-fault','arm-vfd-fault'):ET.SubElement(io,'complexEntry',halPin=name)
        return root
    def check(self,root):
        fd,path=tempfile.mkstemp(suffix='.xml');os.close(fd)
        try:ET.ElementTree(root).write(path);validate(path)
        finally:os.unlink(path)
    def test_valid(self):self.check(self.fixture())
    def test_uppercase_types_from_target_generator(self):
        r=self.fixture()
        for entry in r.iter('pdoEntry'):
            entry.set('halType',entry.get('halType').upper())
        self.check(r)

    def test_wrong_drive(self):
        r=self.fixture();r.find('master/slave').set('pid',str(0xc011e))
        with self.assertRaises(ValueError):self.check(r)
    def test_wrong_target(self):
        r=self.fixture();r.find('master/slave/pdoEntry').set('idx',str(0x6064))
        with self.assertRaises(ValueError):self.check(r)

if __name__ == '__main__': unittest.main()
