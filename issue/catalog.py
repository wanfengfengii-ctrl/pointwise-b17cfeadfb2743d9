import sqlite3
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class IssuedPacket:
    issue_id: int
    batch: str
    station: str
    revision: int
    source: str
    packet: bytes


class IssueCatalog:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS issued_packets (
                issue_id INTEGER PRIMARY KEY,
                batch TEXT NOT NULL,
                station TEXT NOT NULL,
                revision INTEGER NOT NULL,
                source TEXT NOT NULL,
                packet BLOB NOT NULL
            )
        ''')

    def record_issue(
        self, *, batch: str, station: str, revision: int, source: str,
        encode: Callable[[int], bytes],
    ) -> IssuedPacket:
        # Reserve the number inside the same write transaction as the final bytes.
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            cursor = self.connection.execute('''
                INSERT INTO issued_packets (batch, station, revision, source, packet)
                VALUES (?, ?, ?, ?, ?)
            ''', (batch, station, revision, source, b''))
            issue_id = cursor.lastrowid
            packet = encode(issue_id)
            self.connection.execute('''
                UPDATE issued_packets SET packet = ? WHERE issue_id = ?
            ''', (packet, issue_id))
        return IssuedPacket(issue_id, batch, station, revision, source, packet)


def get_packet(catalog: IssueCatalog, issue_id: int) -> IssuedPacket | None:
    if type(issue_id) is not int or not 0 < issue_id < 2**63:
        raise ValueError('Invalid issue number')
    row = catalog.connection.execute('''
        SELECT issue_id, batch, station, revision, source, packet
        FROM issued_packets WHERE issue_id = ?
    ''', (issue_id,)).fetchone()
    return None if row is None else IssuedPacket(*row)
