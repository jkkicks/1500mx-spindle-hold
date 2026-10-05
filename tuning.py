"""Coordinated SV670N position/speed proportional-gain trial, with durable restore state."""
import json
import os
import subprocess

# One coordinated step above the successful 200% trial, from the live baseline.
SPEED_GAIN_PERCENT = 250
POSITION_GAIN_PERCENT = 250
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
        self.last_trial = None

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

    def entries(self, record):
        version = record.get('version')
        if version in (1, 2):
            # Old position-only (v1) and speed-only (v2) records remain valid.
            entries = [dict(subindex=3 if version == 1 else 1,
                            original=record['original'], trial=record['trial'])]
        elif version in (3, 4):
            expected_subindices = {1, 2} if version == 3 else {1, 3}
            entries = record.get('entries')
            if (not isinstance(entries, list) or len(entries) != 2 or
                    {e.get('subindex') for e in entries if isinstance(e, dict)} != expected_subindices):
                raise RuntimeError('Invalid saved multi-setting restore record')
        else:
            raise RuntimeError('Unsupported tuning restore record version')
        limits = {1: (1, 20000), 2: (15, 51200), 3: (1, 20000)}
        for entry in entries:
            sub = entry['subindex']
            original, trial = entry['original'], entry['trial']
            low, high = limits[sub]
            if (type(sub) is not int or type(original) is not int or
                    type(trial) is not int or not low <= original <= high or
                    not low <= trial <= high):
                raise RuntimeError('Invalid saved tuning values')
        return entries

    def restore(self):
        if not os.path.exists(self.path):
            return
        with open(self.path) as f:
            record = json.load(f)
        entries = self.entries(record)
        if record.get('identity') != self.identity():
            raise RuntimeError('Saved tuning record does not match this spindle drive')
        self.require_disabled()
        # Check every value before writing any originals, to avoid clobbering
        # an unrelated external change. Partial restoration is retryable.
        for entry in entries:
            current = self.gain(entry['subindex'])
            if current not in (entry['original'], entry['trial']):
                raise RuntimeError('Setting 0x2008:{} changed outside this test; restore record retained'.format(entry['subindex']))
        for entry in reversed(entries):
            sub = entry['subindex']
            current = self.gain(sub)
            if current not in (entry['original'], entry['trial']):
                raise RuntimeError('Setting changed during restoration; backup retained')
            if current != entry['original']:
                self.set_verified(entry['original'], sub)
        # Remove the journal only after verifying ALL original settings.
        for entry in entries:
            if self.gain(entry['subindex']) != entry['original']:
                raise RuntimeError('Original setting 0x2008:{} could not be verified'.format(entry['subindex']))
        os.unlink(self.path)
        self.sync_directory()
        names = {1: ('speed gain', 10., 'Hz'),
                 2: ('integral time', 100., 'ms'),
                 3: ('position gain', 10., 'Hz')}
        for entry in entries:
            name, scale, unit = names[entry['subindex']]
            print('Original {} restored and verified: {:.2f} {}.'.format(
                name, entry['original'] / scale, unit), flush=True)

    def apply(self):
        # Recover any previous format before taking a new baseline.
        self.restore()
        identity = self.identity()
        self.require_disabled()
        if self.drive.read('uint16', '0x2008', 9) != 0:
            raise RuntimeError('Temporary tuning requires the first gain bank')
        speed = self.gain(1)
        integral = self.gain(2)
        position = self.gain(3)
        if not 1 <= speed <= 20000:
            raise RuntimeError('Live speed gain is outside the supported range')
        if not 1 <= position <= 20000:
            raise RuntimeError('Live position gain is outside the supported range')
        trial_speed = (speed * SPEED_GAIN_PERCENT + 50) // 100
        trial_position = (position * POSITION_GAIN_PERCENT + 50) // 100
        if not speed < trial_speed <= 20000:
            raise RuntimeError('Speed-gain trial is out of range or rounds to no increase')
        if not position < trial_position <= 20000:
            raise RuntimeError('Position-gain trial is out of range or rounds to no increase')
        entries = [dict(subindex=1, original=speed, trial=trial_speed),
                   dict(subindex=3, original=position, trial=trial_position)]
        # Both originals are durably saved before the first of the two writes.
        self.save(dict(version=4, identity=identity, entries=entries))
        for entry in entries:
            self.set_verified(entry['trial'], entry['subindex'])
        self.last_trial = dict(speed_original_hz=speed / 10.,
                               speed_trial_hz=trial_speed / 10.,
                               position_original_hz=position / 10.,
                               position_trial_hz=trial_position / 10.,
                               integral_time_ms=integral / 100.)
        print('Temporary position gain: {:.1f} -> {:.1f} Hz. Speed gain: {:.1f} -> {:.1f} Hz. Integral time unchanged: {:.2f} ms.'.format(
            position / 10., trial_position / 10., speed / 10., trial_speed / 10.,
            integral / 100.), flush=True)
