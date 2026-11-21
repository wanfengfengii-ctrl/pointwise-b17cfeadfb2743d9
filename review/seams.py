from dataclasses import dataclass
from itertools import combinations

from intake.receipts import Admission
from intake.selection import SelectedAdmissions
from review.rigid import RigidPlacement, align_pair
from station.coordinates import Point


@dataclass(frozen=True)
class Seam:
    left: str
    right: str
    names: tuple[str, ...]
    pairs: tuple[tuple[Point, Point], ...]


def _compile_seam(left: Admission, right: Admission) -> Seam | None:
    shared = sorted(left.markers.keys() & right.markers.keys())
    if not shared:
        return None
    basis = next((
        (first, second) for first, second in combinations(shared, 2)
        if left.markers[first] != left.markers[second]
        and right.markers[first] != right.markers[second]
    ), None)
    if basis is None:
        raise ValueError(
            f'Seam {left.identity.station}–{right.identity.station} needs two distinct shared locations'
        )
    names = (*basis, *(name for name in shared if name not in basis))
    pairs = tuple((left.markers[name], right.markers[name]) for name in names)
    return Seam(left.identity.station, right.identity.station, names, pairs)


def compile_seams(selected: SelectedAdmissions) -> tuple[Seam, ...]:
    seams = []
    for left, right in combinations(selected.admissions, 2):
        seam = _compile_seam(left, right)
        if seam is not None:
            seams.append(seam)

    neighbors = {item.identity.station: set() for item in selected.admissions}
    for seam in seams:
        neighbors[seam.left].add(seam.right)
        neighbors[seam.right].add(seam.left)
    start = selected.admissions[0].identity.station
    reached = {start}
    pending = [start]
    while pending:
        station = pending.pop()
        unseen = neighbors[station] - reached
        reached.update(unseen)
        pending.extend(unseen)
    if len(reached) != len(neighbors):
        raise ValueError('The selected stations must form a connected seam graph')
    return tuple(seams)


def seam_holds(seam: Seam, left: RigidPlacement, right: RigidPlacement) -> bool:
    return all(left.apply(a) == right.apply(b) for a, b in seam.pairs)


def seam_candidates(
    seam: Seam, fixed_station: str, fixed: RigidPlacement
) -> tuple[RigidPlacement, ...]:
    if fixed_station == seam.left:
        fixed_index = 0
    elif fixed_station == seam.right:
        fixed_index = 1
    else:
        raise ValueError('Fixed station must be an endpoint of the seam')
    moving_index = 1 - fixed_index
    first, second = seam.pairs[:2]
    candidates = align_pair(
        first[moving_index], second[moving_index],
        fixed.apply(first[fixed_index]), fixed.apply(second[fixed_index]),
    )
    valid = []
    for moving in candidates:
        left, right = (fixed, moving) if fixed_index == 0 else (moving, fixed)
        if seam_holds(seam, left, right):
            valid.append(moving)
    return tuple(valid)
