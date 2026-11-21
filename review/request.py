from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction

from intake.inbox import IntakeInbox
from intake.selection import SelectedAdmissions, select_admissions
from reports.publish import publish_handoff, publish_review
from reports.store import ReportStore, StoredReport
from review.distance import ProbeLocation, squared_probe_distances
from review.placement import JointPlacement, enumerate_placements
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


def _prepare(
    inbox: IntakeInbox, request: ReviewRequest
) -> tuple[SelectedAdmissions, str, tuple[ProbeLocation, ProbeLocation], tuple[tuple[str, str], ...], object]:
    selected = select_admissions(inbox, request.admission_ids)
    anchor = require_label(request.anchor_station, 'Anchor station')
    if all(item.identity.station != anchor for item in selected.admissions):
        raise ValueError('Anchor station must be selected')
    probes = resolve_probes(selected, request.probes)
    seams = compile_seams(selected)
    references = (tuple(request.probes[0]), tuple(request.probes[1]))
    return selected, anchor, probes, references, seams


def _distance_of(
    placement: JointPlacement, probes: tuple[ProbeLocation, ProbeLocation]
) -> Fraction:
    (first_station, first_point), (second_station, second_point) = probes
    first = placement[first_station].apply(first_point)
    second = placement[second_station].apply(second_point)
    x = first[0] - second[0]
    y = first[1] - second[1]
    return x * x + y * y


def sign_review(
    inbox: IntakeInbox, reports: ReportStore, request: ReviewRequest,
    *, signed_by: str, signed_at: datetime | None = None,
) -> StoredReport:
    if not isinstance(request, ReviewRequest):
        raise ValueError('A ReviewRequest is required')
    selected, anchor, probes, references, seams = _prepare(inbox, request)
    distances = squared_probe_distances(
        enumerate_placements(selected, seams, anchor), probes,
    )
    return publish_review(
        reports, selected, anchor_station=anchor, probes=references, distances=distances,
        signed_by=signed_by, signed_at=signed_at,
    )


def sign_handoff(
    inbox: IntakeInbox, reports: ReportStore, request: ReviewRequest,
    *, signed_by: str, signed_at: datetime | None = None,
) -> StoredReport:
    """Sign a V1-style review and freeze all placements behind each distance.

    A structurally valid request with no permitted placement is still signed:
    both the distance tuple and the frozen evidence are then empty.
    """
    if not isinstance(request, ReviewRequest):
        raise ValueError('A ReviewRequest is required')
    selected, anchor, probes, references, seams = _prepare(inbox, request)
    placements = tuple(enumerate_placements(selected, seams, anchor))
    by_distance: dict[Fraction, list[JointPlacement]] = {}
    for placement in placements:
        by_distance.setdefault(_distance_of(placement, probes), []).append(placement)
    distances = tuple(sorted(by_distance))
    grouped = {
        distance: tuple(_deduplicate(branches))
        for distance, branches in by_distance.items()
    }
    return publish_handoff(
        reports, selected, anchor_station=anchor, probes=references, distances=distances,
        placements_by_distance=grouped, signed_by=signed_by, signed_at=signed_at,
    )


def _deduplicate(branches: list[JointPlacement]) -> list[JointPlacement]:
    unique = []
    seen = set()
    for branch in branches:
        key = tuple(sorted(branch.items()))
        if key not in seen:
            seen.add(key)
            unique.append(branch)
    return unique
