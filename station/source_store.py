import sqlite3


class SourceStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('PRAGMA foreign_keys = ON')
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS scan_revisions (
                revision INTEGER PRIMARY KEY,
                batch TEXT NOT NULL,
                station TEXT NOT NULL,
                source TEXT NOT NULL,
                payload TEXT NOT NULL
            )
        ''')
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS current_scans (
                batch TEXT NOT NULL,
                station TEXT NOT NULL,
                revision INTEGER NOT NULL REFERENCES scan_revisions(revision),
                PRIMARY KEY (batch, station)
            )
        ''')

    def append_revision(self, batch: str, station: str, source: str, payload: str) -> int:
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            cursor = self.connection.execute('''
                INSERT INTO scan_revisions (batch, station, source, payload)
                VALUES (?, ?, ?, ?)
            ''', (batch, station, source, payload))
            revision = cursor.lastrowid
            self.connection.execute('''
                INSERT INTO current_scans (batch, station, revision) VALUES (?, ?, ?)
                ON CONFLICT (batch, station) DO UPDATE SET revision = excluded.revision
            ''', (batch, station, revision))
        return revision

    def read_revision(self, revision: int) -> sqlite3.Row | tuple | None:
        return self.connection.execute('''
            SELECT revision, batch, station, source, payload
            FROM scan_revisions WHERE revision = ?
        ''', (revision,)).fetchone()

    def read_current_revision(self, batch: str, station: str) -> int | None:
        row = self.connection.execute('''
            SELECT revision FROM current_scans WHERE batch = ? AND station = ?
        ''', (batch, station)).fetchone()
        return None if row is None else row[0]
