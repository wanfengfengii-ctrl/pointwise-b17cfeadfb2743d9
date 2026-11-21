import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction

from reports.lineage import ParentEvidence, restore_parent_evidence
from reports.receipt import FirstReceipt, make_first_receipt, restore_first_receipt


@dataclass(frozen=True)
class StoredReport:
    report_id: int
    batch: str
    anchor_station: str
    probes: tuple[tuple[str, str], tuple[str, str]]
    distances: tuple[Fraction, ...]
    parents: tuple[ParentEvidence, ...]
    receipt: FirstReceipt

    @property
    def unit(self) -> str:
        return 'mm²'


class ReportStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('PRAGMA foreign_keys = ON')
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                report_id INTEGER PRIMARY KEY,
                batch TEXT NOT NULL,
                anchor_station TEXT NOT NULL,
                probes TEXT NOT NULL,
                distances TEXT NOT NULL
            )
        ''')
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS report_parents (
                report_id INTEGER NOT NULL REFERENCES reports(report_id),
                ordinal INTEGER NOT NULL,
                admission_id INTEGER NOT NULL,
                batch TEXT NOT NULL,
                station TEXT NOT NULL,
                revision INTEGER NOT NULL,
                issue_id INTEGER NOT NULL,
                received_from TEXT NOT NULL,
                packet_sha256 TEXT NOT NULL,
                PRIMARY KEY (report_id, ordinal)
            )
        ''')
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS report_receipts (
                report_id INTEGER PRIMARY KEY REFERENCES reports(report_id),
                signed_by TEXT NOT NULL,
                signed_at TEXT NOT NULL
            )
        ''')
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS handoff_packets (
                report_id INTEGER PRIMARY KEY REFERENCES reports(report_id),
                document BLOB NOT NULL
            )
        ''')

    def commit_report(
        self, *, batch: str, anchor_station: str, probes: tuple[tuple[str, str], tuple[str, str]],
        distances: tuple[Fraction, ...], parents: tuple[ParentEvidence, ...],
        signed_by: str, signed_at: datetime | None,
    ) -> StoredReport:
        encoded_probes = json.dumps(probes)
        encoded_distances = json.dumps([str(distance) for distance in distances])
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            cursor = self.connection.execute('''
                INSERT INTO reports (batch, anchor_station, probes, distances) VALUES (?, ?, ?, ?)
            ''', (batch, anchor_station, encoded_probes, encoded_distances))
            report_id = cursor.lastrowid
            self.connection.executemany('''
                INSERT INTO report_parents
                    (report_id, ordinal, admission_id, batch, station, revision, issue_id,
                     received_from, packet_sha256)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                (report_id, ordinal, parent.admission_id, parent.batch, parent.station,
                 parent.revision, parent.issue_id, parent.received_from, parent.packet_sha256)
                for ordinal, parent in enumerate(parents)
            ))
            receipt = make_first_receipt(report_id, signed_by, signed_at)
            self.connection.execute('''
                INSERT INTO report_receipts (report_id, signed_by, signed_at) VALUES (?, ?, ?)
            ''', (report_id, receipt.signed_by, receipt.signed_at.isoformat()))
        return StoredReport(report_id, batch, anchor_station, probes, distances, parents, receipt)

    def commit_handoff(
        self, *, batch: str, anchor_station: str, probes: tuple[tuple[str, str], tuple[str, str]],
        distances: tuple[Fraction, ...], parents: tuple[ParentEvidence, ...],
        signed_by: str, signed_at: datetime | None,
        encode_document,
    ) -> StoredReport:
        encoded_probes = json.dumps(probes)
        encoded_distances = json.dumps([str(distance) for distance in distances])
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            cursor = self.connection.execute('''
                INSERT INTO reports (batch, anchor_station, probes, distances) VALUES (?, ?, ?, ?)
            ''', (batch, anchor_station, encoded_probes, encoded_distances))
            report_id = cursor.lastrowid
            self.connection.executemany('''
                INSERT INTO report_parents
                    (report_id, ordinal, admission_id, batch, station, revision, issue_id,
                     received_from, packet_sha256)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                (report_id, ordinal, parent.admission_id, parent.batch, parent.station,
                 parent.revision, parent.issue_id, parent.received_from, parent.packet_sha256)
                for ordinal, parent in enumerate(parents)
            ))
            receipt = make_first_receipt(report_id, signed_by, signed_at)
            self.connection.execute('''
                INSERT INTO report_receipts (report_id, signed_by, signed_at) VALUES (?, ?, ?)
            ''', (report_id, receipt.signed_by, receipt.signed_at.isoformat()))
            document = encode_document(report_id, receipt)
            self.connection.execute('''
                INSERT INTO handoff_packets (report_id, document) VALUES (?, ?)
            ''', (report_id, document))
        return StoredReport(report_id, batch, anchor_station, probes, distances, parents, receipt)

    def read_handoff(self, report_id: int) -> bytes | None:
        row = self.connection.execute('''
            SELECT document FROM handoff_packets WHERE report_id = ?
        ''', (report_id,)).fetchone()
        return None if row is None else row[0]

    def read_report(self, report_id: int) -> StoredReport | None:
        if type(report_id) is not int or not 0 < report_id < 2**63:
            raise ValueError('Invalid report number')
        row = self.connection.execute('''
            SELECT r.batch, r.anchor_station, r.probes, r.distances, s.signed_by, s.signed_at
            FROM reports r LEFT JOIN report_receipts s ON r.report_id = s.report_id
            WHERE r.report_id = ?
        ''', (report_id,)).fetchone()
        if row is None:
            return None
        batch, anchor, probes_json, distances_json, signed_by, signed_at = row
        if signed_at is None:
            raise sqlite3.DatabaseError(f'Report {report_id} has no first receipt')
        parent_rows = self.connection.execute('''
            SELECT admission_id, batch, station, revision, issue_id, received_from, packet_sha256
            FROM report_parents WHERE report_id = ? ORDER BY ordinal
        ''', (report_id,))
        parents = tuple(restore_parent_evidence(*parent) for parent in parent_rows)
        first, second = json.loads(probes_json)
        probes = (tuple(first), tuple(second))
        distances = tuple(Fraction(value) for value in json.loads(distances_json))
        receipt = restore_first_receipt(report_id, signed_by, signed_at)
        return StoredReport(report_id, batch, anchor, probes, distances, parents, receipt)
