from archive.publication import ManifestStore
from archive.queue import settle
from capture.intake import pump
from device.recording import DeviceRecording
from review.export import render_handover
from review.readback import ManifestNotFound, get_manifest
from run.lifecycle import is_source_stopped, stop_source
from run.manifest import RecordingHeader
from tests import ROLL, WorkspaceTest, frame


class ReadbackTests(WorkspaceTest):
    def test_historical_manifest(self):
        port = self.start()
        for sequence in (1, 2):
            self.assertEqual(pump(self.db, ROLL, port), sequence)
        historical = get_manifest(self.db, settle(self.db, ROLL))
        self.assertEqual(historical.through, 2)
        self.assertEqual(historical.entries[1].spread, 6)
        self.assertEqual(pump(self.db, ROLL, port), 3)
        stop_source(self.db, ROLL, port)
        self.reopen()
        newest = get_manifest(self.db, settle(self.db, ROLL))
        self.assertEqual(newest.through, 3)
        self.reopen()
        reread = get_manifest(self.db, historical.manifest_id)
        self.assertEqual(reread, historical)
        self.assertEqual([entry.origin.source_key for entry in reread.entries], ['slot-01', 'slot-02'])
        self.assertEqual((reread.totals.accepted, reread.totals.rejected), (1, 1))

    def test_historical_manifest_offline(self):
        port = self.start()
        self.assertEqual(pump(self.db, ROLL, port), 1)
        old = get_manifest(self.db, settle(self.db, ROLL))
        self.assertEqual(pump(self.db, ROLL, port), 2)
        stop_source(self.db, ROLL, port)
        del port
        self.reopen()
        self.assertTrue(is_source_stopped(self.db, ROLL))
        self.assertIsNone(pump(self.db, ROLL, None))
        current = get_manifest(self.db, settle(self.db, ROLL))
        self.assertEqual(current.entries[1].raw_row, (15, 21))
        self.assertEqual(current.entries[1].origin.source_key, 'slot-02')
        self.assertEqual(get_manifest(self.db, old.manifest_id), old)
        self.assertIn('F2  LS-7/slot-02  [15, 21]  极差 6 原码计数', render_handover(current))

    def test_historical_manifest_unknown_id(self):
        port = self.start()
        self.assertEqual(pump(self.db, ROLL, port), 1)
        view = get_manifest(self.db, settle(self.db, ROLL))
        with self.assertRaisesRegex(ManifestNotFound, 'unknown manifest'):
            get_manifest(self.db, view.manifest_id + 900)
        self.assertEqual(self.counts(), (1, 1, 1))
        self.assertEqual(ManifestStore(self.db).published_through(ROLL), 1)
        self.assertEqual(get_manifest(self.db, view.manifest_id), view)

    def test_historical_manifest_full_row_spread(self):
        header = RecordingHeader('wide', 4, (-5, 0, 0, 4))
        port = self.start(DeviceRecording(ROLL, header, (
            frame(1, ((2, 12), (3, -9)), header=header), frame(2, header=header),
        )))
        self.assertEqual(pump(self.db, ROLL, port), 1)
        self.assertEqual(pump(self.db, ROLL, port), 2)
        identifier = settle(self.db, ROLL)
        stop_source(self.db, ROLL, port)
        self.reopen()
        view = get_manifest(self.db, identifier)
        self.assertEqual([entry.raw_row for entry in view.entries], [(-5, 12, -9, 4)] * 2)
        self.assertEqual([entry.spread for entry in view.entries], [21, 21])
        self.assertEqual([entry.sequence for entry in view.entries], [1, 2])
        self.assertEqual((view.totals.accepted, view.totals.rejected), (2, 0))
        self.assertEqual(render_handover(view).count('极差 21 原码计数'), 2)

    def test_raw_codes_keep_integer_precision_outside_sqlite_integer_range(self):
        magnitude = 2**100
        header = RecordingHeader('precision', 2, (-magnitude, 0))
        port = self.start(DeviceRecording(ROLL, header, (frame(1, ((2, magnitude),), header=header),)))
        self.assertEqual(pump(self.db, ROLL, port), 1)
        identifier = settle(self.db, ROLL)
        self.reopen()
        entry = get_manifest(self.db, identifier).entries[0]
        self.assertEqual(entry.raw_row, (-magnitude, magnitude))
        self.assertEqual(entry.spread, 2**101)
