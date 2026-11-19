from archive.queue import settle
from capture.checkpoint import CaptureCheckpoint
from capture.intake import pump
from device.port import DevicePort
from device.recording import DeviceRecording
from review.readback import get_manifest
from run.catalog import RunCatalog, RunConflict, RunNotFound
from run.lifecycle import is_source_stopped, stop_source
from run.manifest import RecordingHeader
from run.opening import open_run
from run.workspace import initialize_workspace
from tests import HEADER, ROLL, WorkspaceTest


class OpeningTests(WorkspaceTest):
    def test_header_ok(self):
        first = open_run(self.db, ROLL, HEADER)
        second = open_run(self.db, ROLL, RecordingHeader(HEADER.recording_id, 2, [10, 20]))
        self.assertEqual(first, second)
        self.assertEqual(first.header.initial_row, (10, 20))
        self.assertEqual(CaptureCheckpoint(self.db).read_baseline(first), (10, 20))
        self.assertFalse(first.source_stopped)
        self.assertEqual(self.db.execute('SELECT count(*) FROM runs').fetchone()[0], 1)

    def test_header_ok_reinitialize(self):
        port = self.start()
        self.assertEqual(pump(self.db, ROLL, port), 1)
        identifier = settle(self.db, ROLL)
        issued = get_manifest(self.db, identifier)
        stop_source(self.db, ROLL, port)
        self.reopen()
        initialize_workspace(self.db)
        initialize_workspace(self.db)
        reopened = open_run(self.db, ROLL, HEADER)
        self.assertTrue(reopened.source_stopped)
        self.assertEqual(reopened.header, HEADER)
        checkpoint = CaptureCheckpoint(self.db)
        self.assertEqual(checkpoint.confirmed_through(ROLL), 1)
        self.assertEqual(checkpoint.read_baseline(reopened), (15, 20))
        self.assertEqual(get_manifest(self.db, identifier), issued)
        self.assertEqual(self.counts(), (1, 1, 1))
        self.assertIsNone(pump(self.db, ROLL, None))

    def test_header_conflict(self):
        fixed = open_run(self.db, ROLL, HEADER)
        for competing in (
            RecordingHeader('another-recording', 2, (10, 20)),
            RecordingHeader(HEADER.recording_id, 2, (10, 22)),
            RecordingHeader(HEADER.recording_id, 1, (10,)),
        ):
            with self.subTest(competing=competing), self.assertRaises(RunConflict):
                open_run(self.db, ROLL, competing)
        self.assertEqual(open_run(self.db, ROLL, HEADER), fixed)

    def test_header_conflict_invalid_dimensions(self):
        fixed = open_run(self.db, ROLL, HEADER)
        for invalid in (
            RecordingHeader(HEADER.recording_id, 0, ()),
            RecordingHeader(HEADER.recording_id, 3, (10, 20)),
            RecordingHeader(HEADER.recording_id, True, (10,)),
            RecordingHeader(HEADER.recording_id, 2, (10, True)),
            RecordingHeader(' ', 2, (10, 20)),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                open_run(self.db, ROLL, invalid)
        with self.assertRaises(ValueError):
            open_run(self.db, '', HEADER)
        self.assertEqual(RunCatalog(self.db).get(ROLL), fixed)
        with self.assertRaises(RunNotFound):
            RunCatalog(self.db).get('unknown-roll')

    def test_wrong_source_cannot_stop_or_capture(self):
        self.start()
        wrong = DevicePort(DeviceRecording(ROLL, RecordingHeader('different', 2, (10, 20)), ()))
        with self.assertRaises(RunConflict):
            stop_source(self.db, ROLL, wrong)
        with self.assertRaises(RunConflict):
            pump(self.db, ROLL, wrong)
        self.assertFalse(is_source_stopped(self.db, ROLL))
        self.assertEqual(self.counts(), (0, 0, 0))
