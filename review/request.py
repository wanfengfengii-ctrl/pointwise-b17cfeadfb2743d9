from dataclasses import dataclass
from datetime import datetime

from intake.inbox import IntakeInbox
from intake.selection import SelectedAdmissions, select_admissions
from reports.publish import publish_review
from reports.store import ReportStore, StoredReport
from review.distance import ProbeLocation, squared_probe_distances
from review.placement import enumerate_placements
from review.seams import compile_seams
from station.markers import require_label

ProbeReference = tuple[str, str]


@dataclass(frozen=True)
class ReviewRequest:
    admission_ids: tuple[int, ...]
    anchor_station: str
    probes: tuple[ProbeReference, ProbeReference]


def resolve_probes(
    selected: SelectedAdmissions, references: tuple[ProbeReference, ProbeReference]
) -> tuple[ProbeLocation, ProbeLocation]:
    if not isinstance(references, (list, tuple)) or len(references) != 2:
        raise ValueError('Exactly two probe references are required')
    by_station = {item.identity.station: item.probes for item in selected.admissions}
    locations = []
    for reference in references:
        if not isinstance(reference, (list, tuple)) or len(reference) != 2:
            raise ValueError('A probe reference must contain a station and a probe name')
        station = require_label(reference[0], 'Probe station')
        name = require_label(reference[1], 'Probe name')
        if station not in by_station or name not in by_station[station]:
            raise ValueError(f'No probe {name!r} at selected station {station!r}')
        locations.append((station, by_station[station][name]))
    return locations[0], locations[1]


def sign_review(
    inbox: IntakeInbox, reports: ReportStore, request: ReviewRequest,
    *, signed_by: str, signed_at: datetime | None = None,
) -> StoredReport:
    if not isinstance(request, ReviewRequest):
        raise ValueError('A ReviewRequest is required')
    selected = select_admissions(inbox, request.admission_ids)
    anchor = require_label(request.anchor_station, 'Anchor station')
    if all(item.identity.station != anchor for item in selected.admissions):
        raise ValueError('Anchor station must be selected')
    probes = resolve_probes(selected, request.probes)
    seams = compile_seams(selected)
    distances = squared_probe_distances(enumerate_placements(selected, seams, anchor), probes)
    references = (tuple(request.probes[0]), tuple(request.probes[1]))
    return publish_review(
        reports, selected, anchor_station=anchor, probes=references, distances=distances,
        signed_by=signed_by, signed_at=signed_at,
    )
