import hashlib

from intake.receipts import load_admission, receive_packet
from tests.fixtures import WorkspaceTest, center_stores, example, external_bytes


class IntakeTests(WorkspaceTest):
    def setUp(self):
        super().setUp()
        self.connection = self.connect(self.center_path)
        self.inbox, _ = center_stores(self.connection)
        self.packet = example('offline_packets.json')['A']

    def count(self):
        return self.connection.execute('SELECT COUNT(*) FROM admissions').fetchone()[0]

    def test_identity_mismatch(self):
        for field, wrong_value in [('station', 'Z'), ('revision', 32), ('issue_id', 99)]:
            with self.subTest(field=field):
                wrong = {**self.packet, 'identity': {**self.packet['identity'], field: wrong_value}}
                with self.assertRaisesRegex(ValueError, 'does not match'):
                    receive_packet(self.inbox, external_bytes(wrong), received_from='offline/drop')
                self.assertEqual(self.count(), 0)

    def test_batch_mismatch(self):
        valid = receive_packet(self.inbox, external_bytes(self.packet), received_from='offline/valid')
        other_identity = {**self.packet['body']['identity'], 'batch': 'J18'}
        wrong = {**self.packet, 'body': {**self.packet['body'], 'identity': other_identity}}
        with self.assertRaisesRegex(ValueError, 'does not match'):
            receive_packet(self.inbox, external_bytes(wrong), received_from='offline/bad-batch')
        self.assertEqual(self.count(), 1)
        self.assertEqual(load_admission(self.inbox, valid.admission_id), valid)

    def test_bad_format_does_not_admit(self):
        good = external_bytes(self.packet)
        for raw in (b'\xff', good[:-1], good.replace(b'"version":1', b'"version":true'),
                    good.replace(b'"version":1', b'"version":1,"version":1')):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    receive_packet(self.inbox, raw, received_from='offline/drop')
        self.assertEqual(self.count(), 0)

    def test_exact_replay_preserves_first_source_and_bytes(self):
        raw = external_bytes(self.packet)
        first = receive_packet(self.inbox, raw, received_from='offline/first')
        replay = receive_packet(self.inbox, raw, received_from='offline/replay')
        self.assertEqual(replay, first)
        self.assertEqual((replay.packet, replay.received_from), (raw, 'offline/first'))
        self.assertEqual(replay.packet_sha256, hashlib.sha256(raw).hexdigest())
        changed_body = {**self.packet['body'], 'probes': {'D': ['3', '4']}}
        changed = external_bytes({**self.packet, 'body': changed_body})
        with self.assertRaisesRegex(ValueError, 'Different bytes'):
            receive_packet(self.inbox, changed, received_from='offline/conflict')
        self.assertEqual(self.count(), 1)
        self.assertEqual(load_admission(self.inbox, first.admission_id), first)
