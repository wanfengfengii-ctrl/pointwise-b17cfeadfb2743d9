from dataclasses import replace
from fractions import Fraction

from intake.receipts import receive_packet
from intake.selection import select_admissions
from reports.retrieve import get_report
from review.request import ReviewRequest, sign_review
from review.rigid import RigidPlacement
from review.seams import compile_seams, seam_candidates
from tests.fixtures import (
    FIRST_SIGNING, SECOND_SIGNING, WorkspaceTest, center_stores, collinear_scans,
    cycle_request, example, external_bytes, issue_and_receive, pair_request, report_counts, scan,
)


class ReviewTests(WorkspaceTest):
    def setUp(self):
        super().setUp()
        self.connection = self.connect(self.center_path)
        self.inbox, self.reports = center_stores(self.connection)

    def receive_scans(self, scans):
        _, admissions = issue_and_receive(self.station_path, self.inbox, scans)
        return admissions

    def sign(self, request, *, when=FIRST_SIGNING):
        return sign_review(self.inbox, self.reports, request, signed_by='Night analyst', signed_at=when)

    def test_cycle_before_and_after_correction(self):
        admissions = self.receive_scans(example('day_shift.json'))
        # Both C revisions have been received and the station connection has closed.
        old_request = cycle_request(admissions, 'C_original', order=('A', 'B', 'C'))
        new_request = cycle_request(admissions, 'C_corrected', order=('C', 'A', 'B'))
        old, new = self.sign(old_request), self.sign(new_request, when=SECOND_SIGNING)
        self.assertEqual(old.distances, ())
        self.assertEqual(new.distances, (Fraction(1),))
        self.assertEqual((old.unit, new.unit), ('mm²', 'mm²'))
        self.assertEqual(tuple(parent.admission_id for parent in old.parents), old_request.admission_ids)
        self.assertEqual(tuple(parent.admission_id for parent in new.parents), new_request.admission_ids)
        self.assertEqual([parent.station for parent in new.parents], ['C', 'A', 'B'])
        self.assertEqual(old.parents[-1].revision, admissions['C_original'].identity.revision)
        self.assertEqual(new.parents[0].revision, admissions['C_corrected'].identity.revision)
        self.assertEqual(get_report(self.reports, old.report_id), old)
        self.assertEqual(get_report(self.reports, new.report_id), new)

    def test_independent_cycle_packets_and_individually_legal_seams(self):
        packets = example('offline_packets.json')
        admissions = {
            key: receive_packet(self.inbox, external_bytes(packet), received_from=f'offline/{key}')
            for key, packet in packets.items()
        }
        self.assertFalse(self.station_path.exists())
        request = cycle_request(admissions, 'C_original')
        selected = select_admissions(self.inbox, request.admission_ids)
        seams = compile_seams(selected)
        self.assertEqual([(seam.left, seam.right) for seam in seams], [('A', 'B'), ('A', 'C'), ('B', 'C')])
        orientations = []
        for seam in seams:
            candidates = seam_candidates(seam, seam.left, RigidPlacement())
            self.assertEqual(len(candidates), 1)
            orientations.append(candidates[0].orientation)
        self.assertEqual(orientations, [1, -1, 1])
        self.assertEqual(self.sign(request).distances, ())
        corrected = self.sign(cycle_request(admissions, 'C_corrected'))
        self.assertEqual(corrected.distances, (Fraction(1),))
        self.assertEqual(corrected.parents[-1].received_from, 'offline/C_corrected')

    def test_collinear_seam_faces(self):
        reversible = self.receive_scans(collinear_scans())
        fixed = self.receive_scans(collinear_scans(face='fixed'))
        both = self.sign(pair_request(reversible))
        zero = self.sign(pair_request(fixed))
        self.assertEqual(both.distances, (Fraction(0), Fraction(4)))
        self.assertEqual(zero.distances, (Fraction(0),))
        self.assertIs(type(zero.distances[0]), Fraction)
        self.assertEqual(get_report(self.reports, zero.report_id).distances, (Fraction(0),))

    def test_reversible_anchor_fixed_peer(self):
        scans = collinear_scans(face='fixed')
        scans['A']['face'] = 'reversible'
        scans['A']['markers'].append(('P', (0, 1)))
        scans['B']['markers'].append(('P', (0, -1)))
        scans['B']['probes'] = [('F', (1, -1))]
        admissions = self.receive_scans(scans)
        for anchor in ('A', 'B'):
            with self.subTest(anchor=anchor):
                self.assertEqual(self.sign(pair_request(admissions, anchor=anchor)).distances, (Fraction(1),))

    def test_fractional_projection_and_equal_distance_deduplication(self):
        scaled = self.receive_scans(collinear_scans(step='1/3'))
        centered = self.receive_scans(collinear_scans(first_probe=(0, 0)))
        self.assertEqual(self.sign(pair_request(scaled)).distances, (Fraction(0), Fraction(4, 9)))
        self.assertEqual(self.sign(pair_request(centered)).distances, (Fraction(1),))

    def test_rational_rotation_and_length_mismatch(self):
        scans = collinear_scans(face='fixed')
        scans['B']['markers'] = [('O', (0, 0)), ('E', ('3/5', '4/5'))]
        scans['B']['probes'] = [('F', ('-4/5', '3/5'))]
        rotated = self.receive_scans(scans)
        self.assertEqual(self.sign(pair_request(rotated)).distances, (Fraction(0),))
        scans['B']['markers'] = [('O', (0, 0)), ('E', (2, 0))]
        mismatched = self.receive_scans(scans)
        self.assertEqual(self.sign(pair_request(mismatched)).distances, ())

    def test_connected_chain_with_distinct_seam_bases(self):
        scans = {
            'A': scan('A', [('O', (0, 0)), ('E', (1, 0))], [('D', (0, 1))]),
            'B': scan('B', [('O', (2, 0)), ('E', (3, 0)), ('U', (2, 2)), ('V', (2, 3))]),
            'C': scan('C', [('U', (0, 1)), ('V', (1, 1))], [('F', (0, 0))]),
        }
        admissions = self.receive_scans(scans)
        request = ReviewRequest(
            tuple(admissions[key].admission_id for key in ('C', 'B', 'A')),
            'A', (('A', 'D'), ('C', 'F')),
        )
        # U=(0,2), V=(0,3) in A's frame. A preserving 90° turn puts F=(1,2).
        self.assertEqual(self.sign(request).distances, (Fraction(2),))

    def test_mixed_batch(self):
        scans = collinear_scans()
        scans['B']['batch'] = 'J18'
        request = pair_request(self.receive_scans(scans))
        before = report_counts(self.connection)
        for numbers in (request.admission_ids, request.admission_ids[::-1]):
            with self.assertRaisesRegex(ValueError, 'same batch'):
                self.sign(replace(request, admission_ids=numbers))
        self.assertEqual(report_counts(self.connection), before)

    def test_invalid_topology(self):
        for second_markers in ([('U', (0, 0)), ('V', (1, 0))], [('O', (0, 0)), ('E', (0, 0))]):
            with self.subTest(second_markers=second_markers):
                scans = collinear_scans()
                scans['B']['markers'] = second_markers
                request = pair_request(self.receive_scans(scans))
                with self.assertRaises(ValueError):
                    self.sign(request)
        self.assertEqual(report_counts(self.connection), (0, 0, 0))

    def test_bad_probe_owner_and_selection(self):
        request = pair_request(self.receive_scans(collinear_scans()))
        for bad in (
            replace(request, probes=(('B', 'D'), ('B', 'F'))),
            replace(request, anchor_station='C'),
            replace(request, admission_ids=(request.admission_ids[0],) * 2),
            replace(request, admission_ids=(request.admission_ids[0],)),
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.sign(bad)
        with self.assertRaises(LookupError):
            self.sign(replace(request, admission_ids=(request.admission_ids[0], 999)))
        self.assertEqual(report_counts(self.connection), (0, 0, 0))
