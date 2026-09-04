"""Warning-area relevance, separate from the displayed incident-marker distance.

Rings contain (latitude, longitude); a polygon is exterior followed by holes.
Point containment uses unwrapped longitudes. Boundary distances use spherical
Earth great-circle segments. These are proximity checks, not fire predictions.
"""
from __future__ import annotations

from math import asin, atan2, cos, isfinite, radians, sin, sqrt
from typing import Iterable

Point = tuple[float, float]
Ring = tuple[Point, ...]
Polygon = tuple[Ring, ...]
EARTH_KM = 6371.0088


def valid_point(point: Point) -> bool:
    return all(isfinite(x) for x in point) and -90 <= point[0] <= 90 and -180 <= point[1] <= 180


def _wrap(longitude: float) -> float:
    return (longitude + 180) % 360 - 180


def _angle(a: Point, b: Point) -> float:
    p, q = radians(a[0]), radians(b[0])
    h = sin((q-p)/2)**2 + cos(p)*cos(q)*sin(radians(_wrap(b[1]-a[1]))/2)**2
    return 2 * asin(sqrt(min(1.0, max(0.0, h))))


def _bearing(a: Point, b: Point) -> float:
    p, q, dl = radians(a[0]), radians(b[0]), radians(_wrap(b[1]-a[1]))
    return atan2(sin(dl)*cos(q), cos(p)*sin(q)-sin(p)*cos(q)*cos(dl))


def _segment_distance(point: Point, a: Point, b: Point) -> float:
    length = _angle(a, b)
    if length < 1e-12:
        return _angle(point, a) * EARTH_KM
    distance = _angle(a, point)
    bearing = _bearing(a, point) - _bearing(a, b)
    along = atan2(sin(distance)*cos(bearing), cos(distance))
    if 0 <= along <= length:
        cross = asin(min(1.0, max(-1.0, sin(distance)*sin(bearing))))
        return abs(cross) * EARTH_KM
    return min(_angle(point, a), _angle(point, b)) * EARTH_KM


def _edges(ring: Ring) -> Iterable[tuple[Point, Point]]:
    for index, a in enumerate(ring):
        yield a, ring[(index+1) % len(ring)]


def _ring_contains(point: Point, ring: Ring) -> bool:
    y, longitude = point
    unwrapped = [(ring[0][0], ring[0][1])]
    for latitude, lon in ring[1:]:
        previous = unwrapped[-1][1]
        unwrapped.append((latitude, previous + _wrap(lon-previous)))
    x = unwrapped[0][1] + _wrap(longitude-unwrapped[0][1])
    inside = False
    for a, b in _edges(tuple(unwrapped)):
        if (a[0] > y) != (b[0] > y):
            intercept = a[1] + (y-a[0])*(b[1]-a[1])/(b[0]-a[0])
            if intercept > x:
                inside = not inside
    return inside


def area_relevance(point: Point, polygons: Iterable[Polygon]) -> tuple[bool | None, float | None]:
    """Return containment and distance, or unknown for absent/invalid geometry.

    Holes exclude their interiors. Boundaries count as part of the warned area.
    """
    areas = tuple(polygons)
    if not areas or not valid_point(point):
        return None, None
    distances: list[float] = []
    inside = False
    for polygon in areas:
        if not polygon or any(len(set(ring)) < 3 or not all(valid_point(p) for p in ring) for ring in polygon):
            return None, None
        boundary = min(_segment_distance(point, a, b) for ring in polygon for a, b in _edges(ring))
        distances.append(boundary)
        contained = _ring_contains(point, polygon[0]) and not any(_ring_contains(point, hole) for hole in polygon[1:])
        inside = inside or contained or boundary < 1e-6
    return inside, 0.0 if inside else min(distances)
