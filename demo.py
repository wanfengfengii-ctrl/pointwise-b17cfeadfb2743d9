import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from intake.inbox import IntakeInbox
from intake.receipts import receive_packet
from issue.catalog import IssueCatalog, get_packet
from issue.packet import issue_packet
from reports.retrieve import get_handoff, get_report
from reports.store import ReportStore
from review.handoff import combine_handoffs, decode_handoff_bytes
from review.request import ReviewRequest, sign_handoff, sign_review
from station.ingest import ingest_scan
from station.source_store import SourceStore


def handoff_demo() -> None:
    """Sign handoff documents, reopen to retrieve them, then combine offline."""
    fixture = json.loads(
        (Path(__file__).resolve().parent / 'examples' / 'handoff.json').read_text('utf-8')
    )
    when = datetime(2025, 3, 4, 22, tzinfo=timezone.utc)
    with TemporaryDirectory() as work:
        station_path = Path(work) / 'handoff_station.sqlite'
        center_path = Path(work) / 'handoff_center.sqlite'
        scenario = fixture['faces']

        with closing(sqlite3.connect(station_path)) as connection:
            source, catalog = SourceStore(connection), IssueCatalog(connection)
            source.initialize()
            catalog.initialize()
            packets = {}
            for name, scan in scenario['scans'].items():
                revision = ingest_scan(source, scan)
                packets[name] = issue_packet(
                    source, catalog,
                    batch=scan['batch'], station=scan['station'], revision=revision,
                ).packet

        documents = {}
        with closing(sqlite3.connect(center_path)) as connection:
            inbox, reports = IntakeInbox(connection), ReportStore(connection)
            inbox.initialize()
            reports.initialize()
            admissions = {
                name: receive_packet(inbox, packet, received_from=f'handoff-desk/{name}')
                for name, packet in packets.items()
            }
            for name, spec in scenario['requests'].items():
                ids = tuple(admissions[key].admission_id for key in spec['parents'])
                probes = tuple(tuple(reference) for reference in spec['probes'])
                request = ReviewRequest(ids, spec['anchor'], probes)
                report = sign_handoff(
                    inbox, reports, request, signed_by='Relief lead', signed_at=when,
                )
                documents[name] = (report.report_id, get_handoff(reports, report.report_id))
                print(
                    f'handoff {name}: report {report.report_id}, '
                    f'distances {[str(d) for d in report.distances]} {report.unit}'
                )

        # Reopen the center after the signing connection has closed and read
        # the frozen bytes back by number; the station database is not needed.
        with closing(sqlite3.connect(center_path)) as connection:
            reports = ReportStore(connection)
            reports.initialize()
            retrieved = {name: get_handoff(reports, report_id) for name, (report_id, _) in documents.items()}
            for name, (report_id, original) in documents.items():
                assert retrieved[name] == original
            assert get_handoff(reports, 99999) is None

    # Offline combination works only from the retrieved handoff bytes.
    first = retrieved['first']
    second = retrieved['second']
    axis = retrieved['axis']
    corrected = retrieved['corrected']

    no_fixture = combine_handoffs([(first, '0'), (second, '0')])
    shared = combine_handoffs([(first, '0'), (second, '4')])
    flipped = combine_handoffs([(axis, '0'), (second, '0')])
    assert no_fixture is None
    assert shared is not None and flipped is not None

    def summarize(solution):
        return [
            [
                {
                    'cosine': str(placement.cosine),
                    'sine': str(placement.sine),
                    'translation': [str(value) for value in placement.translation],
                    'reflected': placement.reflected,
                }
                for placement in piece
            ]
            for piece in solution
        ]

    first_anchor = decode_handoff_bytes(first).anchor_station
    print(f'first anchor station {first_anchor} is the common origin (zero translation)')
    print('POINTWISE_HANDOFF ' + json.dumps({
        'case_id': 'handoff_faces',
        'selected_distances': {'first': '0', 'second': '4'},
        'no_common_fixture_selection': {'first': '0', 'second': '0', 'result': None},
        'common_fixture': summarize(shared),
        'flipped_peer_fixture': summarize(flipped),
        'corrected_station_conflict': _expect_value_error(
            lambda: combine_handoffs([(corrected, '1'), (first, '0')])
        ),
        'missing_distance_result': combine_handoffs([(first, '999'), (second, '4')]),
    }, sort_keys=True))


def _expect_value_error(call):
    try:
        call()
    except ValueError as error:
        return str(error)
    raise AssertionError('Expected a ValueError for the illegal combination')


def main() -> None:
    path = Path(__file__).resolve().parent / 'examples' / 'day_shift.json'
    scans = json.loads(path.read_text(encoding='utf-8'))
    expected = {'original': [], 'corrected': ['1']}
    with TemporaryDirectory() as work:
        station_path = Path(work) / 'station.sqlite'
        center_path = Path(work) / 'center.sqlite'
        issues = {}
        with closing(sqlite3.connect(station_path)) as connection:
            source, catalog = SourceStore(connection), IssueCatalog(connection)
            source.initialize()
            catalog.initialize()
            for name, scan in scans.items():
                revision = ingest_scan(source, scan)
                issues[name] = issue_packet(
                    source, catalog, batch=scan['batch'], station=scan['station'], revision=revision,
                )

        with closing(sqlite3.connect(center_path)) as connection:
            inbox, reports = IntakeInbox(connection), ReportStore(connection)
            inbox.initialize()
            reports.initialize()
            admissions = {
                key: receive_packet(inbox, issue.packet, received_from=f'desk/{key}')
                for key, issue in issues.items()
            }
            groups = {
                'original': ('A', 'B', 'C_original'),
                'corrected': ('A', 'B', 'C_corrected'),
            }
            selected = {
                name: tuple(admissions[key].admission_id for key in keys)
                for name, keys in groups.items()
            }
            signed = {}
            for hour, (name, ids) in enumerate(selected.items(), start=20):
                request = ReviewRequest(ids, 'A', (('A', 'D'), ('C', 'F')))
                signed[name] = sign_review(
                    inbox, reports, request, signed_by='Night analyst',
                    signed_at=datetime(2025, 3, 4, hour, tzinfo=timezone.utc),
                )
        actual = {name: [str(value) for value in report.distances] for name, report in signed.items()}
        assert actual == expected, (actual, expected)

        with closing(sqlite3.connect(station_path)) as connection:
            catalog = IssueCatalog(connection)
            catalog.initialize()
            original = issues['C_original']
            assert get_packet(catalog, original.issue_id) == original

        downstream = {}
        with closing(sqlite3.connect(center_path)) as connection:
            reports = ReportStore(connection)
            reports.initialize()
            for name, report in signed.items():
                stored = get_report(reports, report.report_id)
                assert stored == report
                downstream[name] = {
                    'distances': [str(value) for value in stored.distances],
                    'parent_admissions': [parent.admission_id for parent in stored.parents],
                    'receipt_report': stored.receipt.report_id,
                }
        downstream_expected = {
            name: {
                'distances': expected[name], 'parent_admissions': list(selected[name]),
                'receipt_report': report.report_id,
            }
            for name, report in signed.items()
        }
        assert downstream == downstream_expected
        for name, report in signed.items():
            print(f'{name}: report {report.report_id}, {actual[name]} {report.unit}')
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v_cycle', 'input': {'scans': scans, 'selected_admissions': selected},
            'expected': expected, 'actual': actual,
            'downstream_expected': downstream_expected, 'downstream_actual': downstream,
            'code_paths': [
                'station/ingest.py', 'issue/packet.py', 'intake/receipts.py',
                'review/seams.py', 'review/placement.py', 'review/distance.py',
                'reports/store.py', 'reports/retrieve.py',
            ],
            'oracle': 'P fixes equal A/B faces, Q equal B/C faces, and original R opposite A/C faces. Corrected R permits the shared face, with probes one millimetre apart. Parent order and receipt number come from the original request and signing.',
        }, sort_keys=True))

    handoff_demo()


if __name__ == '__main__':
    main()
