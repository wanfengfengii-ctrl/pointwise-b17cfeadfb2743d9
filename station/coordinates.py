from fractions import Fraction

Point = tuple[Fraction, Fraction]


def parse_rational(value: object) -> Fraction:
    if type(value) is int or isinstance(value, Fraction):
        return Fraction(value)
    if isinstance(value, str):
        try:
            return Fraction(value)
        except (ValueError, ZeroDivisionError) as error:
            raise ValueError(f'Invalid rational reading {value!r}') from error
    raise ValueError('A reading must be an integer, Fraction, or exact rational string')


def parse_point(value: object) -> Point:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError('A point must contain exactly two readings')
    return parse_rational(value[0]), parse_rational(value[1])


def encode_point(point: Point) -> list[str]:
    return [str(point[0]), str(point[1])]
