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


def _linear_matrix(placement: RigidPlacement) -> tuple[tuple[Fraction, Fraction], tuple[Fraction, Fraction]]:
    """Return the [[c, -e s], [s, e c]] linear part of a placement."""
    c, s = placement.cosine, placement.sine
    e = placement.orientation
    return ((c, -e * s), (s, e * c))


def compose(first: RigidPlacement, second: RigidPlacement) -> RigidPlacement:
    """Return the placement that applies ``first`` and then ``second``."""
    (a11, a12), (a21, a22) = _linear_matrix(first)
    (b11, b12), (b21, b22) = _linear_matrix(second)
    cosine = b11 * a11 + b12 * a21
    sine = b21 * a11 + b22 * a21
    tx, ty = first.translation
    translation = (
        b11 * tx + b12 * ty + second.translation[0],
        b21 * tx + b22 * ty + second.translation[1],
    )
    return RigidPlacement(cosine, sine, translation, first.reflected != second.reflected)


def inverse(placement: RigidPlacement) -> RigidPlacement:
    """Return the inverse rigid placement, including the face reflection.

    The linear part is orthogonal, so its inverse is its transpose. Writing
    that transpose back into the dataclass convention keeps ``sine`` as the
    lower-left matrix entry; the inverse translation is ``-R^T t``.
    """
    (r11, r12), (r21, r22) = _linear_matrix(placement)
    tx, ty = placement.translation
    inverse_cosine = r11
    inverse_sine = r12 if placement.reflected else -r21
    translation = (
        -(r11 * tx + r21 * ty),
        -(r12 * tx + r22 * ty),
    )
    return RigidPlacement(inverse_cosine, inverse_sine, translation, placement.reflected)


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
