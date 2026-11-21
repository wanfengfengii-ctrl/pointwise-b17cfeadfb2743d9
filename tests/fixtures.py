import json
import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from intake.inbox import IntakeInbox
from intake.receipts import receive_packet
from issue.catalog import IssueCatalog
from issue.packet import issue_packet
from reports.store import ReportStore
from review.request import ReviewRequest
from station.ingest import ingest_scan
from station.source_store import SourceStore

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'
FIRST_SIGNING = datetime(2025, 3, 4, 20, 0, tzinfo=timezone.utc)
SECOND_SIGNING = datetime(2025, 3, 4, 21, 30, tzinfo=timezone.utc)


def example(name):
    return json.loads((EXAMPLES / name).read_text(encoding='utf-8'))


def external_bytes(packet):
    return json.dumps(packet, sort_keys=True, separators=(',', ':')).encode('utf-8')


def station_stores(connection):
    source, catalog = SourceStore(connection), IssueCatalog(connection)
    source.initialize()
    catalog.initialize()
    return source, catalog


def center_stores(connection):
    inbox, reports = IntakeInbox(connection), ReportStore(connection)
    inbox.initialize()
    reports.initialize()
    return inbox, reports


def issue_and_receive(path, inbox, scans):
    issues, admissions = {}, {}
    with closing(sqlite3.connect(path)) as connection:
        source, catalog = station_stores(connection)
        for key, scan in scans.items():
            revision = ingest_scan(source, scan)
            issued = issue_packet(
                source, catalog, batch=scan['batch'], station=scan['station'], revision=revision,
            )
            issues[key] = issued
            admissions[key] = receive_packet(inbox, issued.packet, received_from=f'handoff/{key}')
    return issues, admissions


def cycle_request(admissions, c_key, *, order=('A', 'B', 'C')):
    keys = (c_key if key == 'C' else key for key in order)
    numbers = tuple(admissions[key].admission_id for key in keys)
    return ReviewRequest(numbers, 'A', (('A', 'D'), ('C', 'F')))


def scan(station, markers, probes=(), *, face='fixed', batch='J17'):
    return {
        'station': station, 'batch': batch, 'source': f'bench/{station}', 'face': face,
        'markers': list(markers), 'probes': list(probes),
    }


def collinear_scans(*, face='reversible', step=1, first_probe=None):
    axis = [('O', (0, 0)), ('E', (step, 0))]
    anchor_probe = (0, step) if first_probe is None else first_probe
    return {
        'A': scan('A', axis, [('D', anchor_probe)]),
        'B': scan('B', axis, [('F', (0, step))], face=face),
    }


def pair_request(admissions, *, anchor='A'):
    numbers = tuple(admissions[key].admission_id for key in ('A', 'B'))
    return ReviewRequest(numbers, anchor, (('A', 'D'), ('B', 'F')))


def report_counts(connection):
    return (
        connection.execute('SELECT COUNT(*) FROM reports').fetchone()[0],
        connection.execute('SELECT COUNT(*) FROM report_parents').fetchone()[0],
        connection.execute('SELECT COUNT(*) FROM report_receipts').fetchone()[0],
    )


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.station_path = self.root / 'station.sqlite'
        self.center_path = self.root / 'center.sqlite'

    def connect(self, path):
        return self.enterContext(closing(sqlite3.connect(path)))
