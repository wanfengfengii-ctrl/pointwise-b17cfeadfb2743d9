from collections.abc import Iterator, Mapping
from types import MappingProxyType

from intake.selection import SelectedAdmissions
from review.rigid import RigidPlacement
from review.seams import Seam, seam_candidates, seam_holds

JointPlacement = Mapping[str, RigidPlacement]


def _frontier(seams: tuple[Seam, ...], assigned: dict[str, RigidPlacement]) -> tuple[Seam, str, str]:
    for fixed in reversed(assigned):
        for seam in seams:
            if seam.left == fixed and seam.right not in assigned:
                return seam, fixed, seam.right
            if seam.right == fixed and seam.left not in assigned:
                return seam, fixed, seam.left
    raise ValueError('No seam reaches the remaining stations')


def enumerate_placements(
    selected: SelectedAdmissions, seams: tuple[Seam, ...], anchor_station: str
) -> Iterator[JointPlacement]:
    permits_flip = {item.identity.station: item.allow_flip for item in selected.admissions}
    if anchor_station not in permits_flip:
        raise ValueError('Anchor station must be selected')

    def extend(assigned: dict[str, RigidPlacement]) -> Iterator[JointPlacement]:
        if len(assigned) == len(permits_flip):
            yield MappingProxyType(assigned)
            return
        seam, fixed, moving = _frontier(seams, assigned)
        for candidate in seam_candidates(seam, fixed, assigned[fixed]):
            if candidate.orientation < 0 and not permits_flip[moving]:
                continue
            branch = {**assigned, moving: candidate}
            if all(
                seam_holds(edge, branch[edge.left], branch[edge.right])
                for edge in seams if edge.left in branch and edge.right in branch
            ):
                yield from extend(branch)

    # The anchor fixes translation and rotation. Its permitted face can still vary.
    anchor_faces = (False, True) if permits_flip[anchor_station] else (False,)
    for reflected in anchor_faces:
        yield from extend({anchor_station: RigidPlacement(reflected=reflected)})
