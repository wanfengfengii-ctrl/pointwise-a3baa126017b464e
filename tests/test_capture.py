import sqlite3
from contextlib import closing
from dataclasses import replace

from archive.disposition import DispositionStore
from archive.queue import settle
from capture.checkpoint import CaptureCheckpoint
from capture.decode import BadFrame
from capture.evidence import EvidenceStore, ReplayConflict
from capture.intake import pump
from demo import block_fixture_commit
from device.frame import FrameOrigin, read_source_frame
from device.port import ConfirmationUnknown, DevicePort
from device.position import DeviceSequenceError
from device.recording import DeviceRecording
from review.readback import get_manifest
from run.catalog import RunCatalog
from run.lifecycle import stop_source
from run.workspace import open_workspace
from tests import HEADER, ROLL, WorkspaceTest, frame, shift_recording


class CaptureTests(WorkspaceTest):
    def test_bad_delta(self):
        port = self.start(DeviceRecording(ROLL, HEADER, (frame(1, ((3, 99),)),)))
        with self.assertRaises(BadFrame):
            pump(self.db, ROLL, port)
        checkpoint = CaptureCheckpoint(self.db)
        self.assertEqual(port.confirmed_position(), 0)
        self.assertEqual(checkpoint.confirmed_through(ROLL), 0)
        self.assertEqual(checkpoint.read_baseline(RunCatalog(self.db).get(ROLL)), (10, 20))
        self.assertIsNone(EvidenceStore(self.db).get(ROLL, 1))
        self.assertIsNone(settle(self.db, ROLL))
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_bad_delta_atomic(self):
        port = self.start(DeviceRecording(ROLL, HEADER, (
            frame(1, ((1, 15),)), frame(2, ((1, 999), (3, 30))),
        )))
        self.assertEqual(pump(self.db, ROLL, port), 1)
        identifier = settle(self.db, ROLL)
        before = get_manifest(self.db, identifier)
        with self.assertRaises(BadFrame):
            pump(self.db, ROLL, port)
        self.assertEqual(port.confirmed_position(), 1)
        checkpoint = CaptureCheckpoint(self.db)
        self.assertEqual(checkpoint.confirmed_through(ROLL), 1)
        self.assertEqual(checkpoint.read_baseline(RunCatalog(self.db).get(ROLL)), (15, 20))
        self.assertIsNone(EvidenceStore(self.db).get(ROLL, 2))
        self.assertIsNone(DispositionStore(self.db).get(ROLL, 2))
        self.assertIsNone(settle(self.db, ROLL))
        self.assertEqual(get_manifest(self.db, identifier), before)

    def test_bad_fields_leave_no_prepared_fact(self):
        good = frame(1)
        for bad in (
            replace(good, sequence=2), replace(good, recording_id='other'),
            replace(good, changes=((1, 10), (1, 11))), replace(good, changes=((True, 4),)),
            replace(good, changes=((1, False),)), replace(good, vibration_exceeded=0),
            replace(good, origin=FrameOrigin('LS-7', ' ')),
            read_source_frame({'sequence': 1, 'roll_id': ROLL}),
        ):
            with self.subTest(bad=bad):
                port = self.start(DeviceRecording(ROLL, HEADER, (bad,)))
                with self.assertRaises(BadFrame):
                    pump(self.db, ROLL, port)
                self.assertEqual(port.confirmed_position(), 0)
                self.assertEqual(self.counts(), (0, 0, 0))

    def test_ack_lost(self):
        port = self.start(lose_ack=(1,))
        with self.assertRaises(ConfirmationUnknown):
            pump(self.db, ROLL, port)
        self.assertEqual(port.confirmed_position(), 1)
        self.assertIsNone(port.redeliver(1))
        self.assertEqual(CaptureCheckpoint(self.db).confirmed_through(ROLL), 0)
        self.assertEqual(EvidenceStore(self.db).get(ROLL, 1).raw_row, (15, 20))
        self.assertIsNone(settle(self.db, ROLL))
        self.reopen()
        self.assertEqual(pump(self.db, ROLL, port), 1)
        self.assertEqual(CaptureCheckpoint(self.db).confirmed_through(ROLL), 1)
        self.assertEqual(self.counts(), (1, 0, 0))
        self.assertEqual(pump(self.db, ROLL, port), 2)
        self.assertEqual(EvidenceStore(self.db).get(ROLL, 2).raw_row, (15, 21))
        issued = get_manifest(self.db, settle(self.db, ROLL))
        self.assertEqual([entry.sequence for entry in issued.entries], [1, 2])
        self.assertEqual(self.counts(), (2, 2, 1))

    def test_ack_lost_pre_ack_commit(self):
        observed = []

        def observe_request(sequence):
            with closing(open_workspace(self.path)) as observer:
                observed.append((
                    sequence, EvidenceStore(observer).get(ROLL, sequence),
                    CaptureCheckpoint(observer).confirmed_through(ROLL),
                ))

        port = self.start(on_ack_request=observe_request)
        with block_fixture_commit(self.db, 'capture_facts', 1):
            with self.assertRaises(sqlite3.IntegrityError) as failure:
                pump(self.db, ROLL, port)
        self.assertEqual(failure.exception.sqlite_errorcode, sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(observed, [])
        self.assertEqual(port.confirmed_position(), 0)
        self.assertIsNotNone(port.redeliver(1))
        self.assertEqual(self.counts(), (0, 0, 0))
        self.assertEqual(pump(self.db, ROLL, port), 1)
        self.assertEqual(len(observed), 1)
        sequence, fact, confirmed = observed[0]
        self.assertEqual((sequence, confirmed), (1, 0))
        self.assertEqual(fact.raw_row, (15, 20))
        self.assertEqual(fact.source, shift_recording().frame_at(1))
        self.assertIsNone(port.redeliver(1))

    def test_ack_lost_retry_same(self):
        port = self.start(pause_ack=(1,))
        with self.assertRaises(ConfirmationUnknown):
            pump(self.db, ROLL, port)
        self.assertEqual(port.confirmed_position(), 0)
        prepared = EvidenceStore(self.db).get(ROLL, 1)
        self.assertEqual(port.redeliver(1), prepared.source)
        self.reopen()
        self.assertEqual(pump(self.db, ROLL, port), 1)
        self.assertEqual(EvidenceStore(self.db).get(ROLL, 1), prepared)
        self.assertEqual(self.counts(), (1, 0, 0))
        self.assertIsNone(port.redeliver(1))
        self.assertEqual(port.acknowledge(1), 1)

    def test_ack_lost_retry_conflict(self):
        recording = shift_recording()
        original = recording.frame_at(1)
        conflicting = replace(original, origin=FrameOrigin('LS-7', 'other-slot'))
        port = self.start(recording, pause_ack=(1,), replays={1: conflicting})
        with self.assertRaises(ConfirmationUnknown):
            pump(self.db, ROLL, port)
        self.reopen()
        original_fact = EvidenceStore(self.db).get(ROLL, 1)
        with self.assertRaises(ReplayConflict):
            pump(self.db, ROLL, port)
        self.assertEqual(port.confirmed_position(), 0)
        self.assertEqual(CaptureCheckpoint(self.db).confirmed_through(ROLL), 0)
        self.assertEqual(EvidenceStore(self.db).get(ROLL, 1), original_fact)
        self.assertIsNone(settle(self.db, ROLL))
        self.assertEqual(pump(self.db, ROLL, port), 1)
        self.assertEqual(EvidenceStore(self.db).get(ROLL, 1).source.origin, original.origin)
        self.assertEqual(self.counts(), (1, 0, 0))

    def test_stopped_pending_confirmation_stays_unverified(self):
        port = self.start(lose_ack=(1,))
        with self.assertRaises(ConfirmationUnknown):
            pump(self.db, ROLL, port)
        stop_source(self.db, ROLL, port)
        self.reopen()
        self.assertIsNone(pump(self.db, ROLL, None))
        self.assertIsNone(settle(self.db, ROLL))
        self.assertEqual(self.counts(), (1, 0, 0))
        self.assertEqual(CaptureCheckpoint(self.db).confirmed_through(ROLL), 0)

    def test_device_window_does_not_reoffer_retired_slots(self):
        port = DevicePort(shift_recording(), capacity=2, reclaim_on_ack=False)
        self.assertEqual(port.fetch_next().sequence, 1)
        with self.assertRaises(DeviceSequenceError):
            port.acknowledge(2)
        self.assertEqual(port.confirmed_position(), 0)
        port.acknowledge(1)
        self.assertEqual(port.redeliver(1).sequence, 1)
        self.assertEqual(port.fetch_next().sequence, 2)
        port.acknowledge(2)
        self.assertEqual(port.fetch_next().sequence, 3)
        self.assertIsNone(port.redeliver(1))
        self.assertEqual(port.redeliver(2).sequence, 2)

    def test_position_from_a_different_device_session_cannot_regress_checkpoint(self):
        port = self.start()
        self.assertEqual(pump(self.db, ROLL, port), 1)
        reset_port = DevicePort(shift_recording())
        with self.assertRaises(ConfirmationUnknown):
            pump(self.db, ROLL, reset_port)
        self.assertEqual(CaptureCheckpoint(self.db).confirmed_through(ROLL), 1)
        self.assertEqual(reset_port.confirmed_position(), 0)
        self.assertEqual(self.counts(), (1, 0, 0))
        self.assertEqual(pump(self.db, ROLL, port), 2)
