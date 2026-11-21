import hashlib
import sqlite3
from contextlib import closing
from fractions import Fraction

from intake.receipts import load_admission, receive_packet
from issue.catalog import get_packet
from issue.packet import issue_packet
from reports.retrieve import get_report
from review.request import sign_review
from station.ingest import ingest_scan
from tests.fixtures import (
    FIRST_SIGNING, SECOND_SIGNING, WorkspaceTest, center_stores, collinear_scans,
    cycle_request, example, issue_and_receive, pair_request, report_counts, station_stores,
)


class ReportTests(WorkspaceTest):
    def test_receipt_write_failure(self):
        connection = self.connect(self.center_path)
        inbox, reports = center_stores(connection)
        _, admissions = issue_and_receive(self.station_path, inbox, collinear_scans(face='fixed'))
        request = pair_request(admissions)
        old = sign_review(inbox, reports, request, signed_by='First analyst', signed_at=FIRST_SIGNING)
        self.assertEqual(old.distances, (Fraction(0),))
        before = report_counts(connection)
        self.assertEqual(before, (1, 2, 1))
        connection.execute('''
            CREATE TEMP TRIGGER reject_first_receipt BEFORE INSERT ON report_receipts
            WHEN 2 = (SELECT COUNT(*) FROM report_parents WHERE report_id = NEW.report_id)
            BEGIN SELECT RAISE(ABORT, 'receipt write rejected'); END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'receipt write rejected'):
            sign_review(inbox, reports, request, signed_by='Next analyst', signed_at=SECOND_SIGNING)
        self.assertEqual(report_counts(connection), before)
        self.assertEqual(get_report(reports, old.report_id), old)
        connection.execute('DROP TRIGGER reject_first_receipt')
        retried = sign_review(inbox, reports, request, signed_by='Next analyst', signed_at=SECOND_SIGNING)
        self.assertEqual(report_counts(connection), (2, 4, 2))
        self.assertEqual(retried.distances, (Fraction(0),))
        self.assertEqual(retried.receipt.signed_at, SECOND_SIGNING)
        self.assertEqual(retried.receipt.signed_by, 'Next analyst')
        self.assertEqual(get_report(reports, retried.report_id), retried)

    def test_reopen_and_retrieve(self):
        scans = example('day_shift.json')
        original_scans = {key: scans[key] for key in ('A', 'B', 'C_original')}
        with closing(sqlite3.connect(self.center_path)) as connection:
            inbox, reports = center_stores(connection)
            original_issues, admissions = issue_and_receive(self.station_path, inbox, original_scans)
            old_request = cycle_request(admissions, 'C_original')
            old = sign_review(inbox, reports, old_request, signed_by='First analyst', signed_at=FIRST_SIGNING)
            self.assertEqual(old.distances, ())
            with closing(sqlite3.connect(self.station_path)) as station_connection:
                source, catalog = station_stores(station_connection)
                correction = ingest_scan(source, scans['C_corrected'])
                corrected = issue_packet(source, catalog, batch='J17', station='C', revision=correction)
            admissions['C_corrected'] = receive_packet(inbox, corrected.packet, received_from='night/correction')
            new = sign_review(
                inbox, reports, cycle_request(admissions, 'C_corrected'),
                signed_by='Next analyst', signed_at=SECOND_SIGNING,
            )
            self.assertEqual(new.distances, (Fraction(1),))
            self.assertEqual(report_counts(connection), (2, 6, 2))

        with closing(sqlite3.connect(self.station_path)) as station_connection:
            source, catalog = station_stores(station_connection)
            station_stores(station_connection)
            self.assertEqual(source.read_current_revision('J17', 'C'), correction)
            self.assertEqual(station_connection.execute('SELECT COUNT(*) FROM scan_revisions').fetchone()[0], 4)
            self.assertEqual(station_connection.execute('SELECT COUNT(*) FROM issued_packets').fetchone()[0], 4)
            old_issue = original_issues['C_original']
            self.assertEqual(get_packet(catalog, old_issue.issue_id), old_issue)
            self.assertEqual(get_packet(catalog, corrected.issue_id), corrected)
            self.assertIsNone(get_packet(catalog, 999))

        with closing(sqlite3.connect(self.center_path)) as connection:
            inbox, reports = center_stores(connection)
            center_stores(connection)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM admissions').fetchone()[0], 4)
            old_copy, new_copy = get_report(reports, old.report_id), get_report(reports, new.report_id)
            self.assertEqual(old_copy, old)
            self.assertEqual(new_copy, new)
            self.assertEqual(old_copy.receipt.signed_at, FIRST_SIGNING)
            self.assertEqual(new_copy.receipt.signed_at, SECOND_SIGNING)
            self.assertEqual(old_copy.parents[-1].packet_sha256, hashlib.sha256(old_issue.packet).hexdigest())
            self.assertEqual(old_copy.parents[-1].received_from, 'handoff/C_original')
            self.assertEqual(new_copy.parents[-1].received_from, 'night/correction')
            self.assertEqual(load_admission(inbox, old_copy.parents[-1].admission_id).packet, old_issue.packet)
            self.assertIsNone(get_report(reports, 999))
            self.assertEqual(report_counts(connection), (2, 6, 2))
            again = sign_review(inbox, reports, old_request, signed_by='Relief analyst', signed_at=SECOND_SIGNING)
            self.assertEqual(again.distances, ())
            self.assertEqual(again.parents, old.parents)
            self.assertEqual(get_report(reports, old.report_id), old)
            self.assertEqual(report_counts(connection), (3, 9, 3))
