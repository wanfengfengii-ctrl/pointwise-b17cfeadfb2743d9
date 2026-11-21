from dataclasses import dataclass
from fractions import Fraction

from station.coordinates import Point

_ZERO: Point = (Fraction(0), Fraction(0))


@dataclass(frozen=True)
class RigidPlacement:
    cosine: Fraction = Fraction(1)
    sine: Fraction = Fraction(0)
    translation: Point = _ZERO
    reflected: bool = False

    @property
    def orientation(self) -> int:
        return -1 if self.reflected else 1

    def apply(self, point: Point) -> Point:
        x, y = point
        y *= self.orientation
        dx, dy = self.translation
        return (
            self.cosine * x - self.sine * y + dx,
            self.sine * x + self.cosine * y + dy,
        )


def align_pair(
    source_start: Point, source_end: Point, target_start: Point, target_end: Point
) -> tuple[RigidPlacement, ...]:
    sx, sy = (source_end[0] - source_start[0], source_end[1] - source_start[1])
    tx, ty = (target_end[0] - target_start[0], target_end[1] - target_start[1])
    source_length = sx * sx + sy * sy
    target_length = tx * tx + ty * ty
    if source_length == 0 or target_length == 0:
        raise ValueError('Alignment endpoints must have different locations')
    if source_length != target_length:
        return ()

    placements = []
    for reflected in (False, True):
        dy = -sy if reflected else sy
        cosine = (sx * tx + dy * ty) / source_length
        sine = (sx * ty - dy * tx) / source_length
        unshifted = RigidPlacement(cosine, sine, reflected=reflected)
        x, y = unshifted.apply(source_start)
        translation = (target_start[0] - x, target_start[1] - y)
        placements.append(RigidPlacement(cosine, sine, translation, reflected))
    return tuple(placements)
