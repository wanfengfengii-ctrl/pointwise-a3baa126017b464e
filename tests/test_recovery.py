import sqlite3

from archive.disposition import DispositionStore
from archive.publication import ManifestStore
from archive.queue import settle
from capture.checkpoint import CaptureCheckpoint
from capture.intake import pump
from demo import block_fixture_commit
from review.readback import get_manifest
from run.lifecycle import is_source_stopped, stop_source
from tests import ROLL, WorkspaceTest, shift_recording


class RecoveryTests(WorkspaceTest):
    def _offline_backlog(self, first_value=15):
        port = self.start(shift_recording(first_value))
        self.assertEqual(pump(self.db, ROLL, port), 1)
        original = get_manifest(self.db, settle(self.db, ROLL, through=1))
        self.assertEqual(pump(self.db, ROLL, port), 2)
        with block_fixture_commit(self.db, 'dispositions', 2):
            with self.assertRaises(sqlite3.IntegrityError) as failure:
                settle(self.db, ROLL, through=2)
        self.assertEqual(failure.exception.sqlite_errorcode, sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(self.counts(), (2, 1, 1))
        self.assertEqual(ManifestStore(self.db).published_through(ROLL), 1)
        self.assertIsNone(DispositionStore(self.db).get(ROLL, 2))
        self.assertEqual(pump(self.db, ROLL, port), 3)
        self.assertEqual(port.confirmed_position(), 3)
        self.assertIsNone(port.redeliver(2))
        self.assertIsNone(port.redeliver(3))
        self.assertEqual(self.counts(), (3, 1, 1))
        stop_source(self.db, ROLL, port)
        self.reopen()
        self.assertTrue(is_source_stopped(self.db, ROLL))
        self.assertEqual(CaptureCheckpoint(self.db).confirmed_through(ROLL), 3)
        self.assertEqual(get_manifest(self.db, original.manifest_id), original)
        return original

    def test_catch_up(self):
        original = self._offline_backlog()
        middle = get_manifest(self.db, settle(self.db, ROLL, through=2))
        final = get_manifest(self.db, settle(self.db, ROLL, through=3))
        self.assertEqual([entry.sequence for entry in middle.entries], [1, 2])
        self.assertEqual([entry.sequence for entry in final.entries], [1, 2, 3])
        self.assertEqual(final.entries[:2], middle.entries)
        self.assertEqual(middle.entries[0], original.entries[0])
        self.assertEqual(final.entries[0].reason, 'vibration_exceeded')
        self.assertEqual([entry.raw_row for entry in final.entries], [None, (15, 21), (17, 21)])
        self.assertEqual([entry.origin.source_key for entry in final.entries], ['slot-01', 'slot-02', 'slot-03'])
        self.assertEqual([entry.spread for entry in final.entries], [None, 6, 4])
        self.assertEqual((final.totals.accepted, final.totals.rejected), (2, 1))

    def test_catch_up_retry_binding(self):
        self._offline_backlog(first_value=16)
        through_two = get_manifest(self.db, settle(self.db, ROLL, through=2))
        through_three = get_manifest(self.db, settle(self.db, ROLL, through=3))
        second, third = through_two.entries[1], through_three.entries[2]
        self.assertEqual((second.raw_row, second.spread, second.reason), ((16, 21), 5, None))
        self.assertEqual((second.origin.station, second.origin.source_key), ('LS-7', 'slot-02'))
        self.assertEqual((third.raw_row, third.spread, third.reason), ((17, 21), 4, None))
        self.assertEqual((third.origin.station, third.origin.source_key), ('LS-7', 'slot-03'))

    def test_catch_up_publish_limit(self):
        original = self._offline_backlog()
        self.assertIsNone(settle(self.db, ROLL, through=0))
        self.assertIsNone(settle(self.db, ROLL, through=1))
        self.assertEqual(ManifestStore(self.db).published_through(ROLL), 1)
        middle = get_manifest(self.db, settle(self.db, ROLL, through=2))
        self.assertEqual(middle.through, 2)
        self.assertEqual([entry.sequence for entry in middle.entries], [1, 2])
        self.assertIsNone(DispositionStore(self.db).get(ROLL, 3))
        self.assertEqual(ManifestStore(self.db).published_through(ROLL), 2)
        later = get_manifest(self.db, settle(self.db, ROLL, through=3))
        self.assertEqual(later.through, 3)
        self.assertNotEqual(later.manifest_id, middle.manifest_id)
        self.assertEqual(get_manifest(self.db, middle.manifest_id), middle)
        self.assertEqual(get_manifest(self.db, original.manifest_id), original)

    def test_catch_up_idempotent_settle(self):
        self._offline_backlog()
        first_retry = settle(self.db, ROLL, through=2)
        self.assertIsNotNone(first_retry)
        self.assertIsNone(settle(self.db, ROLL, through=2))
        self.assertEqual(self.counts(), (3, 2, 2))
        later = settle(self.db, ROLL)
        self.assertIsNotNone(later)
        finished = get_manifest(self.db, later)
        self.reopen()
        self.assertIsNone(settle(self.db, ROLL))
        self.assertIsNone(settle(self.db, ROLL, through=9))
        self.assertEqual(self.counts(), (3, 3, 3))
        self.assertEqual(ManifestStore(self.db).published_through(ROLL), 3)
        self.assertEqual(get_manifest(self.db, later), finished)

    def test_archive_commit_failure_rolls_back_whole_attempt(self):
        port = self.start()
        for sequence in (1, 2, 3):
            self.assertEqual(pump(self.db, ROLL, port), sequence)
        with block_fixture_commit(self.db, 'dispositions', 2):
            with self.assertRaises(sqlite3.IntegrityError):
                settle(self.db, ROLL)
        self.assertEqual(self.counts(), (3, 0, 0))
        self.assertEqual(ManifestStore(self.db).published_through(ROLL), 0)
        self.assertEqual(port.confirmed_position(), 3)
        self.assertEqual(get_manifest(self.db, settle(self.db, ROLL)).through, 3)
        self.assertEqual(self.counts(), (3, 3, 1))
