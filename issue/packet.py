import json

from issue.catalog import IssueCatalog, IssuedPacket
from issue.freeze import FrozenScan, freeze_revision
from issue.geometry import RelativeGeometry, build_relative_geometry
from station.coordinates import encode_point
from station.source_store import SourceStore


def encode_packet(issue_id: int, scan: FrozenScan, geometry: RelativeGeometry) -> bytes:
    identity = {
        'batch': scan.batch, 'station': scan.station,
        'revision': scan.revision, 'issue_id': issue_id,
    }
    body = {
        'identity': identity,
        'allow_flip': geometry.allow_flip,
        'markers': {name: encode_point(point) for name, point in geometry.markers.items()},
        'probes': {name: encode_point(point) for name, point in geometry.probes.items()},
    }
    envelope = {'version': 1, 'identity': identity, 'body': body}
    return json.dumps(envelope, sort_keys=True, separators=(',', ':')).encode('utf-8')


def issue_packet(
    store: SourceStore, catalog: IssueCatalog, *, batch: str, station: str, revision: int
) -> IssuedPacket:
    frozen = freeze_revision(store, batch=batch, station=station, revision=revision)
    geometry = build_relative_geometry(frozen)
    return catalog.record_issue(
        batch=frozen.batch, station=frozen.station, revision=frozen.revision,
        source=frozen.source, encode=lambda issue_id: encode_packet(issue_id, frozen, geometry),
    )
