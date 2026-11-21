from collections.abc import Mapping
from types import MappingProxyType

from station.coordinates import Point, parse_point

NamedPoints = Mapping[str, Point]


def require_label(value: object, role: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f'{role} must be a nonempty string without surrounding whitespace')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as error:
        raise ValueError(f'{role} must be valid Unicode') from error
    return value


def collect_named_points(readings: object) -> NamedPoints:
    if not isinstance(readings, (tuple, list)):
        raise ValueError('Named readings must be a sequence of name and point pairs')
    points = {}
    for entry in readings:
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            raise ValueError('A named reading must contain a name and a point')
        name = require_label(entry[0], 'Point name')
        point = parse_point(entry[1])
        if name in points and points[name] != point:
            raise ValueError(f'Conflicting readings for {name}')
        points[name] = point
    return MappingProxyType(dict(sorted(points.items())))
