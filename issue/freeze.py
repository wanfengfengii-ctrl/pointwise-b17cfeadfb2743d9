from dataclasses import dataclass

from station.markers import NamedPoints
from station.revisions import load_exact_revision
from station.source_store import SourceStore


@dataclass(frozen=True)
class FrozenScan:
    batch: str
    station: str
    revision: int
    source: str
    allow_flip: bool
    markers: NamedPoints
    probes: NamedPoints


def freeze_revision(
    store: SourceStore, *, batch: str, station: str, revision: int
) -> FrozenScan:
    scan = load_exact_revision(store, batch=batch, station=station, revision=revision)
    return FrozenScan(
        scan.batch, scan.station, scan.revision, scan.source, scan.allow_flip,
        scan.markers, scan.probes,
    )
