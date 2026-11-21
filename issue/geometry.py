from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType

from issue.freeze import FrozenScan
from station.markers import NamedPoints


@dataclass(frozen=True)
class RelativeGeometry:
    markers: NamedPoints
    probes: NamedPoints
    allow_flip: bool


def build_relative_geometry(scan: FrozenScan) -> RelativeGeometry:
    # The same origin and positive axes apply to both point catalogs.
    origin_points = scan.markers or scan.probes
    origin_x, origin_y = origin_points[min(origin_points)] if origin_points else (
        Fraction(0), Fraction(0),
    )

    def relative(points: NamedPoints) -> NamedPoints:
        return MappingProxyType({
            name: (x - origin_x, y - origin_y)
            for name, (x, y) in sorted(points.items())
        })

    return RelativeGeometry(relative(scan.markers), relative(scan.probes), scan.allow_flip)
