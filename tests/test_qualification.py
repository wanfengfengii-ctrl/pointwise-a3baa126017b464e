from archive.queue import settle
from capture.checkpoint import CaptureCheckpoint
from capture.intake import pump
from device.recording import DeviceRecording
from review.readback import get_manifest
from run.catalog import RunCatalog
from tests import HEADER, ROLL, WorkspaceTest, frame


class QualificationTests(WorkspaceTest):
    def test_reject_base(self):
        port = self.start()
        self.assertEqual(pump(self.db, ROLL, port), 1)
        first = get_manifest(self.db, settle(self.db, ROLL, through=1))
        rejected = first.entries[0]
        self.assertEqual(rejected.sequence, 1)
        self.assertEqual(rejected.reason, 'vibration_exceeded')
        self.assertIsNone(rejected.raw_row)
        self.assertIsNone(rejected.spread)
        self.assertEqual(rejected.origin.source_key, 'slot-01')
        self.assertEqual(pump(self.db, ROLL, port), 2)
        second = get_manifest(self.db, settle(self.db, ROLL, through=2))
        actual = second.entries[1].raw_row
        self.assertEqual(actual, (15, 21), f'FRAME_BASE_MISMATCH expected=[15,21] actual={actual!r}')
        self.assertEqual(second.entries[1].origin.source_key, 'slot-02')
        self.assertEqual(second.entries[1].spread, 6)
        self.assertEqual(second.entries[0], rejected)
        self.assertEqual((second.totals.accepted, second.totals.rejected), (1, 1))
        checkpoint = CaptureCheckpoint(self.db)
        self.assertEqual(checkpoint.read_baseline(RunCatalog(self.db).get(ROLL)), (15, 21))

    def test_unchanged_frame(self):
        port = self.start(DeviceRecording(ROLL, HEADER, (frame(1, ((1, 17),)), frame(2))))
        self.assertEqual(pump(self.db, ROLL, port), 1)
        first = get_manifest(self.db, settle(self.db, ROLL))
        self.assertEqual(first.entries[0].raw_row, (17, 20))
        self.assertEqual(pump(self.db, ROLL, port), 2)
        second = get_manifest(self.db, settle(self.db, ROLL))
        self.assertEqual([entry.sequence for entry in second.entries], [1, 2])
        self.assertEqual([entry.raw_row for entry in second.entries], [(17, 20), (17, 20)])
        self.assertEqual([entry.origin.source_key for entry in second.entries], ['slot-01', 'slot-02'])
        self.assertEqual((second.totals.accepted, second.totals.rejected), (2, 0))
        self.assertIsNone(pump(self.db, ROLL, port))

    def test_rejected_base_applies_before_any_publication(self):
        port = self.start()
        self.assertEqual(pump(self.db, ROLL, port), 1)
        self.assertEqual(pump(self.db, ROLL, port), 2)
        second = get_manifest(self.db, settle(self.db, ROLL, through=2))
        self.assertEqual(
            second.entries[1].raw_row, (15, 21),
            'a rejected but well-formed frame still fixes the next baseline',
        )
        self.assertEqual(second.entries[1].spread, 6)
        self.assertEqual(second.entries[1].origin.source_key, 'slot-02')
        self.assertIsNone(second.entries[0].raw_row)
        self.assertEqual(second.entries[0].reason, 'vibration_exceeded')
        self.assertEqual(second.entries[0].origin.source_key, 'slot-01')
