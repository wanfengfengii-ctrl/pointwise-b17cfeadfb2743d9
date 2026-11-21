import sqlite3
from dataclasses import dataclass

from intake.identity import VerifiedIdentity


@dataclass(frozen=True)
class InboxEntry:
    admission_id: int
    identity: VerifiedIdentity
    packet: bytes
    received_from: str
    packet_sha256: str


class IntakeInbox:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS admissions (
                admission_id INTEGER PRIMARY KEY,
                batch TEXT NOT NULL,
                station TEXT NOT NULL,
                revision INTEGER NOT NULL,
                issue_id INTEGER NOT NULL,
                packet BLOB NOT NULL,
                received_from TEXT NOT NULL,
                packet_sha256 TEXT NOT NULL,
                UNIQUE (batch, station, revision, issue_id)
            )
        ''')

    def append_admission(
        self, identity: VerifiedIdentity, packet: bytes, received_from: str, packet_sha256: str
    ) -> InboxEntry:
        key = (identity.batch, identity.station, identity.revision, identity.issue_id)
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            self.connection.execute('''
                INSERT INTO admissions
                    (batch, station, revision, issue_id, packet, received_from, packet_sha256)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (batch, station, revision, issue_id) DO NOTHING
            ''', (*key, packet, received_from, packet_sha256))
            row = self.connection.execute('''
                SELECT admission_id, packet, received_from, packet_sha256 FROM admissions
                WHERE batch = ? AND station = ? AND revision = ? AND issue_id = ?
            ''', key).fetchone()
            admission_id, first_packet, first_source, first_digest = row
            if first_packet != packet:
                raise ValueError('Different bytes already admitted under this issue identity')
        return InboxEntry(admission_id, identity, first_packet, first_source, first_digest)

    def read_admission(self, admission_id: int) -> InboxEntry | None:
        row = self.connection.execute('''
            SELECT batch, station, revision, issue_id, packet, received_from, packet_sha256
            FROM admissions WHERE admission_id = ?
        ''', (admission_id,)).fetchone()
        if row is None:
            return None
        batch, station, revision, issue_id, packet, source, digest = row
        identity = VerifiedIdentity(batch, station, revision, issue_id)
        return InboxEntry(admission_id, identity, packet, source, digest)
