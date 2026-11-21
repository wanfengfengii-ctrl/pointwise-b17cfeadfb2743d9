import json
from dataclasses import dataclass

from station.coordinates import encode_point
from station.markers import NamedPoints, collect_named_points, require_label
from station.source_store import SourceStore


@dataclass(frozen=True)
class ScanRevision:
    revision: int
    batch: str
    station: str
    source: str
    allow_flip: bool
    markers: NamedPoints
    probes: NamedPoints


def register_revision(
    store: SourceStore,
    *,
    batch: str,
    station: str,
    source: str,
    allow_flip: bool,
    markers: NamedPoints,
    probes: NamedPoints,
    raw_scan: dict,
) -> int:
    payload = json.dumps({
        'raw_scan': raw_scan,
        'allow_flip': allow_flip,
        'markers': [[name, encode_point(point)] for name, point in markers.items()],
        'probes': [[name, encode_point(point)] for name, point in probes.items()],
    }, default=str, sort_keys=True)
    return store.append_revision(batch, station, source, payload)


def load_exact_revision(
    store: SourceStore, *, batch: str, station: str, revision: int
) -> ScanRevision:
    require_label(batch, 'Batch')
    require_label(station, 'Station')
    if type(revision) is not int or not 0 < revision < 2**63:
        raise ValueError('Invalid revision number')
    row = store.read_revision(revision)
    if row is None or (row[1], row[2]) != (batch, station):
        raise ValueError('No revision matches the specified batch, station and revision')
    saved_revision, saved_batch, saved_station, source, payload = row
    data = json.loads(payload)
    return ScanRevision(
        saved_revision, saved_batch, saved_station, source, data['allow_flip'],
        collect_named_points(data['markers']), collect_named_points(data['probes']),
    )
