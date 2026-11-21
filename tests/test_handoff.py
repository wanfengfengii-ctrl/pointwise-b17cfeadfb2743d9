import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

from reports.retrieve import get_handoff, get_report
from review.handoff import combine_handoffs, decode_handoff_bytes
from review.request import ReviewRequest, sign_handoff
from review.rigid import RigidPlacement, compose, inverse
from tests.fixtures import (
    FIRST_SIGNING, SECOND_SIGNING, WorkspaceTest, center_stores, example,
    issue_and_receive, report_counts,
)

ZERO = Fraction(0)
ONE = Fraction(1)


class HandoffWorkspace(WorkspaceTest):
    def receive_fixture(self, scenario_name):
        scenario = example('handoff.json')[scenario_name]
        with closing(sqlite3.connect(self.center_path)) as connection:
            inbox, reports = center_stores(connection)
            _, admissions = issue_and_receive(self.station_path, inbox, scenario['scans'])
        return scenario, admissions

    def open_center(self):
        connection = self.connect(self.center_path)
        return connection, *center_stores(connection)

    def sign(self, inbox, reports, admissions, scenario, request_name, *, when=FIRST_SIGNING):
        spec = scenario['requests'][request_name]
        ids = tuple(admissions[name].admission_id for name in spec['parents'])
        probes = tuple(tuple(reference) for reference in spec['probes'])
        request = ReviewRequest(ids, spec['anchor'], probes)
        report = sign_handoff(inbox, reports, request, signed_by='Bench lead', signed_at=when)
        return report, get_handoff(reports, report.report_id)


class SignHandoffTests(HandoffWorkspace):
    def test_distances_parents_and_evidence_match_v1_review(self):
        scenario, admissions = self.receive_fixture('faces')
        connection, inbox, reports = self.open_center()
        for name, spec in scenario['requests'].items():
            with self.subTest(name=name):
                report, document = self.sign(inbox, reports, admissions, scenario, name)
                self.assertEqual([str(d) for d in report.distances], spec['distances'])
                expected_ids = [admissions[key].admission_id for key in spec['parents']]
                self.assertEqual([p.admission_id for p in report.parents], expected_ids)
                decoded = decode_handoff_bytes(document)
                self.assertEqual(decoded.report_id, report.report_id)
                self.assertEqual(decoded.batch, report.batch)
                self.assertEqual(decoded.anchor_station, report.anchor_station)
                self.assertEqual(decoded.distances, report.distances)
                self.assertEqual(len(decoded.evidence), len(report.distances))
                # Every frozen branch places every parent and anchors the frame.
                anchor_index = next(
                    i for i, p in enumerate(decoded.parents)
                    if p.station == decoded.anchor_station
                )
                for joint_branches in decoded.evidence:
                    self.assertTrue(joint_branches)
                    for branch in joint_branches:
                        self.assertEqual(len(branch), len(decoded.parents))
                        anchor = branch[anchor_index]
                        self.assertEqual(anchor.translation, (ZERO, ZERO))
                        self.assertEqual((anchor.cosine, anchor.sine), (ONE, ZERO))

    def test_infeasible_request_still_signs_empty_document(self):
        scans = example('day_shift.json')
        original = {key: scans[key] for key in ('A', 'B', 'C_original')}
        connection, inbox, reports = self.open_center()
        _, admissions = issue_and_receive(self.station_path, inbox, original)
        ids = tuple(admissions[key].admission_id for key in ('A', 'B', 'C_original'))
        request = ReviewRequest(ids, 'A', (('A', 'D'), ('C', 'F')))
        report = sign_handoff(inbox, reports, request, signed_by='Lead', signed_at=FIRST_SIGNING)
        self.assertEqual(report.distances, ())
        document = get_handoff(reports, report.report_id)
        decoded = decode_handoff_bytes(document)
        self.assertEqual(decoded.distances, ())
        self.assertEqual(decoded.evidence, ())
        self.assertEqual(get_report(reports, report.report_id), report)

    def test_invalid_request_raises_value_error_unknown_admission_lookup_error(self):
        scenario, admissions = self.receive_fixture('faces')
        connection, inbox, reports = self.open_center()
        spec = scenario['requests']['first']
        ids = tuple(admissions[name].admission_id for name in spec['parents'])
        good = ReviewRequest(ids, spec['anchor'], tuple(tuple(p) for p in spec['probes']))
        before = report_counts(connection)
        bad_anchor = ReviewRequest(ids, 'Z', good.probes)
        with self.assertRaises(ValueError):
            sign_handoff(inbox, reports, bad_anchor, signed_by='Lead', signed_at=FIRST_SIGNING)
        unknown = ReviewRequest((ids[0], 999), 'A', good.probes)
        with self.assertRaises(LookupError):
            sign_handoff(inbox, reports, unknown, signed_by='Lead', signed_at=FIRST_SIGNING)
        self.assertEqual(report_counts(connection), before)

    def test_handoff_write_failure_rolls_back_and_retries(self):
        scenario, admissions = self.receive_fixture('faces')
        connection, inbox, reports = self.open_center()
        before = report_counts(connection)
        spec = scenario['requests']['first']
        ids = tuple(admissions[name].admission_id for name in spec['parents'])
        request = ReviewRequest(ids, spec['anchor'], tuple(tuple(p) for p in spec['probes']))
        connection.execute('''
            CREATE TEMP TRIGGER reject_handoff BEFORE INSERT ON handoff_packets
            BEGIN SELECT RAISE(ABORT, 'handoff write rejected'); END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'handoff write rejected'):
            sign_handoff(inbox, reports, request, signed_by='Lead', signed_at=SECOND_SIGNING)
        self.assertEqual(report_counts(connection), before)
        self.assertEqual(
            connection.execute('SELECT COUNT(*) FROM handoff_packets').fetchone()[0], 0,
        )
        connection.execute('DROP TRIGGER reject_handoff')
        report, document = self.sign(
            inbox, reports, admissions, scenario, 'first', when=SECOND_SIGNING,
        )
        self.assertEqual(report.receipt.signed_at, SECOND_SIGNING)
        self.assertEqual(
            connection.execute('SELECT COUNT(*) FROM handoff_packets').fetchone()[0], 1,
        )
        self.assertEqual(decode_handoff_bytes(document).report_id, report.report_id)


class RetrieveHandoffTests(HandoffWorkspace):
    def test_get_handoff_modes_and_reopen_stability(self):
        scenario, admissions = self.receive_fixture('faces')
        with closing(sqlite3.connect(self.center_path)) as connection:
            inbox, reports = center_stores(connection)
            report, document = self.sign(inbox, reports, admissions, scenario, 'first')
            report_id = report.report_id
            document_bytes = document
        # Reopen: only stored values are read, no station or inbox dependency.
        with closing(sqlite3.connect(self.center_path)) as connection:
            reports = ReportStoreHarness(connection)
            self.assertEqual(get_handoff(reports, report_id), document_bytes)
            self.assertIsNone(get_handoff(reports, 99999))
            # A plain V1 report number never resolves to a handoff document.
            from review.request import sign_review
            inbox = InboxHarness(connection)
            spec = scenario['requests']['first']
            ids = tuple(admissions[name].admission_id for name in spec['parents'])
            plain = sign_review(
                inbox, reports,
                ReviewRequest(ids, spec['anchor'], tuple(tuple(p) for p in spec['probes'])),
                signed_by='Lead', signed_at=FIRST_SIGNING,
            )
            self.assertIsNone(get_handoff(reports, plain.report_id))
        for invalid in (0, -1, 1.5, '7'):
            with self.assertRaises(ValueError):
                get_handoff(reports, invalid)
        self.assertEqual(decode_handoff_bytes(document_bytes).report_id, report_id)

    def test_documents_are_deterministic_and_self_consistent(self):
        scenario, admissions = self.receive_fixture('faces')
        connection, inbox, reports = self.open_center()
        first, first_bytes = self.sign(inbox, reports, admissions, scenario, 'first')
        second, second_bytes = self.sign(
            inbox, reports, admissions, scenario, 'first', when=FIRST_SIGNING,
        )
        left = json.loads(first_bytes)
        right = json.loads(second_bytes)
        self.assertNotEqual(first.report_id, second.report_id)
        for body in (left, right):
            body.pop('report_id')
            body['receipt'].pop('report_id')
        self.assertEqual(left, right)
        # Round-trip decoding preserves every exact rational coefficient.
        decoded = decode_handoff_bytes(first_bytes)
        for joint_branches in decoded.evidence:
            for branch in joint_branches:
                for placement in branch:
                    self.assertIsInstance(placement.cosine, Fraction)
                    self.assertIsInstance(placement.translation[0], Fraction)
                    self.assertEqual(
                        placement.cosine ** 2 + placement.sine ** 2, ONE,
                    )


# Lightweight re-initialization helpers mirroring the fixtures without a fresh DB.
def ReportStoreHarness(connection):
    from reports.store import ReportStore
    store = ReportStore(connection)
    store.initialize()
    return store


def InboxHarness(connection):
    from intake.inbox import IntakeInbox
    inbox = IntakeInbox(connection)
    inbox.initialize()
    return inbox


class CombineHandoffTests(HandoffWorkspace):
    def setUp(self):
        super().setUp()
        self.faces, self.face_admissions = self.receive_fixture('faces')
        self.cycle, self.cycle_admissions = self.receive_fixture('cycle')
        connection, inbox, reports = self.open_center()
        self.connection, self.inbox, self.reports = connection, inbox, reports
        self.face_docs = {
            name: self.sign(inbox, reports, self.face_admissions, self.faces, name)[1]
            for name in self.faces['requests']
        }
        self.cycle_docs = {
            name: self.sign(inbox, reports, self.cycle_admissions, self.cycle, name)[1]
            for name in self.cycle['requests']
        }

    def test_faces_zero_zero_has_no_common_fixture(self):
        self.assertIsNone(
            combine_handoffs([(self.face_docs['first'], '0'), (self.face_docs['second'], '0')])
        )

    def test_faces_zero_four_shares_one_preserving_b_placement(self):
        result = combine_handoffs(
            [(self.face_docs['first'], '0'), (self.face_docs['second'], '4')]
        )
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 2)
        first_doc = decode_handoff_bytes(self.face_docs['first'])
        anchor_index = next(
            i for i, parent in enumerate(first_doc.parents)
            if parent.station == first_doc.anchor_station
        )
        anchor = result[0][anchor_index]
        self.assertEqual(anchor.translation, (ZERO, ZERO))
        self.assertEqual((anchor.cosine, anchor.sine), (ONE, ZERO))
        self.assertFalse(anchor.reflected)
        # The shared B receipt must occupy one identical station in both pieces.
        b_first = next(
            placement for parent, placement in zip(first_doc.parents, result[0])
            if parent.station == 'B'
        )
        second_doc = decode_handoff_bytes(self.face_docs['second'])
        b_second = next(
            placement for parent, placement in zip(second_doc.parents, result[1])
            if parent.station == 'B'
        )
        self.assertEqual(b_first, b_second)
        self.assertFalse(b_first.reflected)
        for placement in result[0] + result[1]:
            self.assertIsInstance(placement, RigidPlacement)
            self.assertIsInstance(placement.cosine, Fraction)

    def test_swapped_input_order_reanchors_to_the_new_first_piece(self):
        forward = combine_handoffs(
            [(self.face_docs['first'], '0'), (self.face_docs['second'], '4')]
        )
        swapped = combine_handoffs(
            [(self.face_docs['second'], '4'), (self.face_docs['first'], '0')]
        )
        self.assertIsNotNone(swapped)
        second_doc = decode_handoff_bytes(self.face_docs['second'])
        anchor_index = next(
            i for i, parent in enumerate(second_doc.parents)
            if parent.station == second_doc.anchor_station
        )
        anchor = swapped[0][anchor_index]
        self.assertEqual(anchor.translation, (ZERO, ZERO))
        self.assertEqual((anchor.cosine, anchor.sine), (ONE, ZERO))
        # The two answers describe the same relative B/A geometry, just
        # re-expressed with each input's own anchor as the common origin.
        forward_b = next(
            p for parent, p in zip(decode_handoff_bytes(self.face_docs['first']).parents, forward[0])
            if parent.station == 'B'
        )
        swapped_b = next(
            p for parent, p in zip(second_doc.parents, swapped[0])
            if parent.station == 'B'
        )
        self.assertEqual(forward_b.reflected, swapped_b.reflected)

    def test_axis_plus_second_feasible_with_b_face_branch(self):
        result = combine_handoffs(
            [(self.face_docs['axis'], '0'), (self.face_docs['second'], '0')]
        )
        self.assertIsNotNone(result)
        axis_doc = decode_handoff_bytes(self.face_docs['axis'])
        placements = {
            parent.station: placement
            for parent, placement in zip(axis_doc.parents, result[0])
        }
        # B is the first piece's anchor and therefore an identity placement;
        # its signed face branch is realized through the reflected A peer.
        self.assertFalse(placements['B'].reflected)
        self.assertEqual(placements['B'].translation, (ZERO, ZERO))
        self.assertTrue(placements['A'].reflected)
        # The shared B receipt still occupies one identical common station.
        second_doc = decode_handoff_bytes(self.face_docs['second'])
        shared_b = next(
            placement for parent, placement in zip(second_doc.parents, result[1])
            if parent.station == 'B'
        )
        self.assertEqual(shared_b, placements['B'])

    def test_cycle_pairs_feasible_but_triple_inconsistent(self):
        ab, bc, ca = self.cycle_docs['ab'], self.cycle_docs['bc'], self.cycle_docs['ca']
        self.assertIsNotNone(combine_handoffs([(ab, '0'), (bc, '0')]))
        self.assertIsNotNone(combine_handoffs([(bc, '0'), (ca, '0')]))
        self.assertIsNotNone(combine_handoffs([(ca, '0'), (ab, '0')]))
        self.assertIsNone(combine_handoffs([(ab, '0'), (bc, '0'), (ca, '0')]))

    def test_missing_distance_returns_none(self):
        self.assertIsNone(
            combine_handoffs([(self.face_docs['first'], '400'), (self.face_docs['second'], '4')])
        )

    def test_same_station_with_different_receipt_is_value_error(self):
        with self.assertRaisesRegex(ValueError, 'different receipt numbers'):
            combine_handoffs(
                [(self.face_docs['corrected'], '1'), (self.face_docs['first'], '0')]
            )

    def test_mixed_batch_is_value_error_even_when_distance_absent(self):
        # Rebrand one document's batch while keeping the rest structurally valid.
        decoded = json.loads(self.face_docs['first'])
        decoded['batch'] = 'OTHER'
        for parent in decoded['parents']:
            parent['batch'] = 'OTHER'
        foreign = json.dumps(decoded, separators=(',', ':')).encode('utf-8')
        with self.assertRaisesRegex(ValueError, 'same batch'):
            combine_handoffs([(foreign, '999'), (self.face_docs['second'], '999')])

    def test_v1_packet_and_bad_documents_are_value_errors(self):
        v1_packet = example('offline_packets.json')['A']
        v1_bytes = json.dumps(v1_packet, sort_keys=True, separators=(',', ':')).encode('utf-8')
        good = self.face_docs['first']
        for bad in (v1_bytes, b'not json', b'{}', b'\xff\xfe'):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    combine_handoffs([(bad, '0'), (good, '0')])

    def test_non_negative_and_rational_distance_rules(self):
        good = self.face_docs['first']
        with self.assertRaises(ValueError):
            combine_handoffs([(good, '-1'), (self.face_docs['second'], '0')])
        with self.assertRaises(ValueError):
            combine_handoffs([(good, 0.5), (self.face_docs['second'], '0')])
        # Fraction and integer inputs are accepted through parse_rational.
        self.assertIsNone(
            combine_handoffs([(good, Fraction(999)), (self.face_docs['second'], Fraction(0))])
        )

    def test_too_few_selections_and_bad_shape(self):
        good = self.face_docs['first']
        with self.assertRaises(ValueError):
            combine_handoffs([])
        with self.assertRaises(ValueError):
            combine_handoffs([(good, '0')])
        with self.assertRaises(ValueError):
            combine_handoffs([(good,), (self.face_docs['second'], '0')])

    def test_disconnected_group_is_value_error(self):
        # Two same-batch documents with no shared receipt cannot be combined.
        ab = self.cycle_docs['ab']
        # Rebrand every station and receipt number so the standalone document
        # keeps one shared batch but has no connecting admission or station.
        decoded = json.loads(self.face_docs['axis'])
        batch = self.cycle['scans']['A']['batch']
        decoded['batch'] = batch
        decoded['anchor_station'] = 'Y'
        decoded['probes'] = [
            [{'A': 'X', 'B': 'Y'}[station], name] for station, name in decoded['probes']
        ]
        for parent in decoded['parents']:
            parent['batch'] = batch
            parent['station'] = {'A': 'X', 'B': 'Y'}[parent['station']]
            parent['admission_id'] += 1000
        standalone = json.dumps(decoded, separators=(',', ':')).encode('utf-8')
        decode_handoff_bytes(standalone)  # structurally valid on its own
        with self.assertRaisesRegex(ValueError, 'connected group'):
            combine_handoffs([(ab, '0'), (standalone, '0')])

    def test_tampered_evidence_is_value_error_not_none(self):
        decoded = json.loads(self.face_docs['first'])
        decoded['evidence'][0][0][0]['cosine'] = '2'
        tampered = json.dumps(decoded, separators=(',', ':')).encode('utf-8')
        with self.assertRaises(ValueError):
            combine_handoffs([(tampered, '0'), (self.face_docs['second'], '0')])

    def test_rigid_algebra_identity_and_associativity(self):
        samples = [
            RigidPlacement(Fraction(3, 5), Fraction(4, 5), (1, 2), False),
            RigidPlacement(Fraction(3, 5), Fraction(-4, 5), (-2, 1), True),
            RigidPlacement(ONE, ZERO, (0, 0), True),
        ]
        points = [(Fraction(a, 3), Fraction(b, 3)) for a in range(-2, 3) for b in range(-2, 3)]
        for placement in samples:
            pinv = inverse(placement)
            self.assertEqual(compose(placement, pinv), RigidPlacement())
            self.assertEqual(compose(pinv, placement), RigidPlacement())
            for point in points:
                self.assertEqual(pinv.apply(placement.apply(point)), point)
        a, b, c = samples
        self.assertEqual(compose(compose(a, b), c), compose(a, compose(b, c)))
