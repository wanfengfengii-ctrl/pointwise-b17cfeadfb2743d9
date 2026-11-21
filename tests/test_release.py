import json
from fractions import Fraction

from intake.decode import decode_packet
from issue.catalog import get_packet
from issue.packet import issue_packet
from station.ingest import ingest_scan
from tests.fixtures import WorkspaceTest, example, station_stores


def side_of_baseline(points, name):
    ox, oy = points['O']
    ex, ey = points['E']
    px, py = points[name]
    return (ex - ox) * (py - oy) - (ey - oy) * (px - ox)


class ReleaseTests(WorkspaceTest):
    def setUp(self):
        super().setUp()
        self.connection = self.connect(self.station_path)
        self.source, self.catalog = station_stores(self.connection)
        self.scans = example('day_shift.json')

    def issue_c(self, revision):
        return issue_packet(self.source, self.catalog, batch='J17', station='C', revision=revision)

    def test_exact_revision(self):
        old = ingest_scan(self.source, self.scans['C_original'])
        corrected = {**self.scans['C_corrected'], 'face': 'fixed'}
        new = ingest_scan(self.source, corrected)
        self.assertNotEqual(old, new)
        self.assertEqual(self.source.read_current_revision('J17', 'C'), new)

        old_issue, new_issue = self.issue_c(old), self.issue_c(new)
        old_body, new_body = decode_packet(old_issue.packet), decode_packet(new_issue.packet)
        self.assertEqual((old_body.inner.revision, new_body.inner.revision), (old, new))
        self.assertEqual((old_issue.source, new_issue.source), ('day/C/initial', 'day/C/correction'))
        self.assertEqual((old_body.allow_flip, new_body.allow_flip), (True, False))
        self.assertEqual(side_of_baseline(old_body.markers, 'R'), Fraction(-1))
        self.assertEqual(side_of_baseline(new_body.markers, 'R'), Fraction(1))
        for body in (old_body, new_body):
            qx, qy = body.markers['Q']
            fx, fy = body.probes['F']
            self.assertEqual((fx - qx, fy - qy), (Fraction(1), Fraction(2)))
        self.assertEqual(get_packet(self.catalog, old_issue.issue_id), old_issue)

    def test_conflicting_marker(self):
        old = ingest_scan(self.source, self.scans['C_original'])
        invalid = dict(self.scans['C_corrected'])
        invalid['markers'] = [*invalid['markers'], ['R', [1, -1]]]
        with self.assertRaisesRegex(ValueError, 'Conflicting readings for R'):
            ingest_scan(self.source, invalid)
        self.assertEqual(self.source.read_current_revision('J17', 'C'), old)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM scan_revisions').fetchone()[0], 1)
        self.assertEqual(side_of_baseline(decode_packet(self.issue_c(old).packet).markers, 'R'), -1)

    def test_invalid_rationals_and_equivalent_duplicate(self):
        initial = self.scans['C_original']
        old = ingest_scan(self.source, initial)
        for coordinate in ('1/0', 0.5, True, 'not a reading'):
            with self.subTest(coordinate=coordinate):
                invalid = {**initial, 'probes': [['F', [coordinate, 3]]]}
                with self.assertRaises(ValueError):
                    ingest_scan(self.source, invalid)
                self.assertEqual(self.source.read_current_revision('J17', 'C'), old)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM scan_revisions').fetchone()[0], 1)

        equivalent = {**initial, 'markers': [*initial['markers'], ['R', ['2/2', '-1.0']]]}
        again = ingest_scan(self.source, equivalent)
        raw = json.loads(self.source.read_revision(again)[4])['raw_scan']
        self.assertEqual(raw['markers'], equivalent['markers'])
        self.assertEqual(set(decode_packet(self.issue_c(again).packet).markers), {'E', 'O', 'Q', 'R'})

    def test_mismatched_references_do_not_issue(self):
        revision = ingest_scan(self.source, self.scans['C_original'])
        for batch, station, number in [('J18', 'C', revision), ('J17', 'A', revision), ('J17', 'C', 999)]:
            with self.subTest(batch=batch, station=station, number=number):
                with self.assertRaises(ValueError):
                    issue_packet(self.source, self.catalog, batch=batch, station=station, revision=number)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM issued_packets').fetchone()[0], 0)
        self.assertEqual(self.issue_c(revision).revision, revision)

    def test_machine_translation_and_raw_origin_remain_station_side(self):
        base = self.scans['C_original']
        shifted = {**base, 'source': 'station-only/shifted'}
        for group in ('markers', 'probes'):
            shifted[group] = [[name, [x + 100, y + 200]] for name, (x, y) in base[group]]
        normal = self.issue_c(ingest_scan(self.source, base))
        moved = self.issue_c(ingest_scan(self.source, shifted))
        reference, observed = decode_packet(normal.packet), decode_packet(moved.packet)
        self.assertEqual(observed.markers, reference.markers)
        self.assertEqual(observed.probes, reference.probes)
        self.assertNotIn(b'station-only/shifted', moved.packet)
        self.assertEqual(moved.source, 'station-only/shifted')
