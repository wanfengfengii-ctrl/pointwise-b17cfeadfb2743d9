from collections.abc import Iterable
from fractions import Fraction

from review.placement import JointPlacement
from station.coordinates import Point

ProbeLocation = tuple[str, Point]


def squared_probe_distances(
    placements: Iterable[JointPlacement], probes: tuple[ProbeLocation, ProbeLocation]
) -> tuple[Fraction, ...]:
    (first_station, first_point), (second_station, second_point) = probes
    distances = set()
    for placement in placements:
        first = placement[first_station].apply(first_point)
        second = placement[second_station].apply(second_point)
        x = first[0] - second[0]
        y = first[1] - second[1]
        distances.add(x * x + y * y)
    return tuple(sorted(distances))
