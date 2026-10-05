"""One temporary SV670N speed-gain trial, with durable restore state."""
import json
import os
import subprocess

# Change this in a later revision after evaluating the preceding trial.
SPEED_GAIN_PERCENT = 125
GAIN_INDEX = '0x2008'
GAIN_SUBINDEX = 1


class EtherCAT:
    def run(self, action, datatype, index, subindex, value=None):
        args = ['ethercat', action, '--master=0', '--position=0', '--alias=-',
                '-t', datatype, index, str(subindex)]
        if value is not None:
            args.append(str(value))
        try:
            output = subprocess.check_output(args, stderr=subprocess.STDOUT,
                                             timeout=2.).decode().strip()
        except subprocess.CalledProcessError as exc:
            raise RuntimeError('SDO {} {}:{} failed: {}'.format(
                action, index, subindex, exc.output.decode().strip()))
        except subprocess.TimeoutExpired:
            raise RuntimeError('SDO {} {}:{} timed out'.format(action, index, subindex))
        if action == 'upload':
            try:
                return int(output.split()[-1], 10)
            except (ValueError, IndexError):
                raise RuntimeError('Unreadable SDO {}:{}: {}'.format(index, subindex, output))

    def read(self, datatype, index, subindex):
        return self.run('upload', datatype, index, subindex)

    def write(self, datatype, index, subindex, value):
        self.run('download', datatype, index, subindex, value)


class GainTuner:
    def __init__(self, backup_path, drive=None):
        self.path = backup_path
        self.drive = drive if drive is not None else EtherCAT()

    def identity(self):
        identity = [self.drive.read('uint32', '0x1018', sub) for sub in (1, 2, 4)]
        if identity[:2] != [0x100000, 0xc0130]:
            raise RuntimeError('Tuning requires the supplied SV670N INT identity')
        return identity

    def require_disabled(self):
        if (self.drive.read('uint16', '0x6041', 0) & 0x6f) != 0x40:
            raise RuntimeError('Gain write refused: drive is not Switch On Disabled')

    def gain(self, subindex=GAIN_SUBINDEX):
        return self.drive.read('uint16', GAIN_INDEX, subindex)

    def set_verified(self, value, subindex=GAIN_SUBINDEX):
        self.require_disabled()
        self.drive.write('uint16', GAIN_INDEX, subindex, value)
        if self.gain(subindex) != value:
            raise RuntimeError('Gain 0x2008:{} readback does not match requested value'.format(subindex))

    def save(self, record):
        # Never overwrite an outstanding restore record. Sync before any write
        # to the drive, including a download whose result may be ambiguous.
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(record, f, sort_keys=True)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        self.sync_directory()

    def sync_directory(self):
        fd = os.open(os.path.dirname(os.path.abspath(self.path)), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def restore(self):
        if not os.path.exists(self.path):
            return
        with open(self.path) as f:
            record = json.load(f)
        version = record.get('version')
        if version not in (1, 2) or record.get('identity') != self.identity():
            raise RuntimeError('Saved tuning record does not match this spindle drive')
        # v1 snapshots belong to the old position-gain trial; recover those
        # before starting the speed-gain test. Keep the same backup filename.
        subindex = 3 if version == 1 else 1
        name = 'position' if version == 1 else 'speed'
        original, trial = record['original'], record['trial']
        if (type(original) is not int or type(trial) is not int or
                not 1 <= original <= 20000 or not original <= trial <= 20000):
            raise RuntimeError('Invalid saved gain values')
        self.require_disabled()
        current = self.gain(subindex)
        if current not in (original, trial):
            raise RuntimeError('{} gain changed outside this test; restore record retained'.format(name.capitalize()))
        if current != original:
            self.set_verified(original, subindex)
        # Confirm readback even if the original was already in effect.
        if self.gain(subindex) != original:
            raise RuntimeError('Original {} gain could not be verified'.format(name))
        os.unlink(self.path)
        self.sync_directory()
        print('Original {} gain restored and verified: {:.1f} Hz.'.format(
            name, original / 10.), flush=True)

    def apply(self):
        # Recover an interrupted previous run before taking a new baseline.
        self.restore()
        identity = self.identity()
        self.require_disabled()
        if self.drive.read('uint16', '0x2008', 9) != 0:
            raise RuntimeError('Temporary tuning requires the first gain bank')
        original = self.gain()
        if not 1 <= original <= 20000:
            raise RuntimeError('Live speed gain is outside the supported range')
        trial = (original * SPEED_GAIN_PERCENT + 50) // 100
        if not original < trial <= 20000:
            raise RuntimeError('Speed-gain trial is outside the supported range or rounds to no increase')
        position = self.gain(3)
        integral = self.drive.read('uint16', '0x2008', 2)
        self.save(dict(version=2, identity=identity, original=original, trial=trial))
        self.set_verified(trial)
        print('Temporary speed gain: {:.1f} -> {:.1f} Hz (+{}%). Position gain unchanged: {:.1f} Hz; integral time unchanged: {:.2f} ms.'.format(
            original / 10., trial / 10., SPEED_GAIN_PERCENT - 100, position / 10., integral / 100.), flush=True)
