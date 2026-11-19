from contextlib import closing
from pathlib import Path

from capture.evidence import EvidenceStore
from demo import SAMPLE, run_shift
from device.recording import load_recording
from review.readback import get_manifest
from run.workspace import open_workspace
from tests import WorkspaceTest


class ShiftWorkflowTests(WorkspaceTest):
    def test_shift_workflow(self):
        recording = load_recording(SAMPLE)
        first, middle, final = run_shift(Path(self.path).with_name('demo-shift.sqlite3'), recording)
        self.assertEqual((first.through, middle.through, final.through), (1, 2, 3))
        self.assertEqual([entry.sequence for entry in final.entries], [1, 2, 3])
        self.assertEqual([entry.raw_row for entry in final.entries], [None, (15, 21), (17, 21)])
        self.assertEqual([entry.spread for entry in final.entries], [None, 6, 4])
        self.assertEqual([entry.reason for entry in final.entries], ['vibration_exceeded', None, None])
        self.assertEqual(
            [(entry.origin.station, entry.origin.source_key) for entry in final.entries],
            [('LS-7', 'slot-01'), ('LS-7', 'slot-02'), ('LS-7', 'slot-03')],
        )
        self.assertEqual((middle.totals.accepted, middle.totals.rejected), (1, 1))
        self.assertEqual((final.totals.accepted, final.totals.rejected), (2, 1))
        with closing(open_workspace(Path(self.path).with_name('demo-shift.sqlite3'))) as db:
            self.assertEqual(get_manifest(db, middle.manifest_id), middle)
            fact = EvidenceStore(db).get(recording.roll_id, 1)
            self.assertEqual(fact.raw_row, (15, 20))
            self.assertTrue(fact.source.vibration_exceeded)
