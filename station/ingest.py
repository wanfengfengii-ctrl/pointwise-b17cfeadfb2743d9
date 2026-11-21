from station.markers import collect_named_points, require_label
from station.revisions import register_revision
from station.source_store import SourceStore


def parse_face_permission(value: object) -> bool:
    if value == 'fixed':
        return False
    if value == 'reversible':
        return True
    raise ValueError('Face permission must be fixed or reversible')


def ingest_scan(store: SourceStore, scan: dict) -> int:
    fields = {'batch', 'station', 'source', 'face', 'markers', 'probes'}
    if not isinstance(scan, dict) or scan.keys() != fields:
        raise ValueError('Scan fields must be batch, station, source, face, markers and probes')
    batch = require_label(scan['batch'], 'Batch')
    station = require_label(scan['station'], 'Station')
    source = require_label(scan['source'], 'Scan source')
    allow_flip = parse_face_permission(scan['face'])
    markers = collect_named_points(scan['markers'])
    probes = collect_named_points(scan['probes'])
    return register_revision(
        store, batch=batch, station=station, source=source, allow_flip=allow_flip,
        markers=markers, probes=probes, raw_scan=scan,
    )
