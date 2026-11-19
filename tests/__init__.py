import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from device.frame import FrameOrigin, SourceFrame
from device.port import DevicePort
from device.recording import DeviceRecording
from run.manifest import RecordingHeader
from run.opening import open_run
from run.workspace import initialize_workspace, open_workspace

ROLL = 'STRIP-07'
HEADER = RecordingHeader('LS7-SHIFT-A', 2, (10, 20))


def frame(sequence, changes=(), vibration=False, *, roll_id=ROLL, header=HEADER):
    return SourceFrame(
        roll_id, header.recording_id, sequence, tuple(changes), vibration,
        FrameOrigin('LS-7', f'slot-{sequence:02d}'),
    )


def shift_recording(first_value=15):
    return DeviceRecording(ROLL, HEADER, (
        frame(1, ((1, first_value),), True), frame(2, ((2, 21),)), frame(3, ((1, 17),)),
    ))


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='line-scan-test-')
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'workspace.sqlite3'
        self.db = open_workspace(self.path)
        self.addCleanup(lambda: self.db.close())
        initialize_workspace(self.db)

    def reopen(self):
        self.db.close()
        self.db = open_workspace(self.path)

    def start(self, recording=None, **port_options):
        if recording is None:
            recording = shift_recording()
        open_run(self.db, recording.roll_id, recording.header)
        return DevicePort(recording, **port_options)

    def counts(self):
        row = self.db.execute('''
            SELECT (SELECT count(*) FROM capture_facts) AS facts,
                   (SELECT count(*) FROM dispositions) AS outcomes,
                   (SELECT count(*) FROM manifests) AS manifests
        ''').fetchone()
        return row['facts'], row['outcomes'], row['manifests']
