from dataclasses import dataclass

MIN_SIDE = 10


@dataclass
class Region:
    x: int
    y: int
    width: int
    height: int


def normalize_rect(x0, y0, x1, y1):
    left = int(round(min(x0, x1)))
    top = int(round(min(y0, y1)))
    width = int(round(abs(x1 - x0)))
    height = int(round(abs(y1 - y0)))
    return left, top, width, height


def is_large_enough(width, height):
    return width >= MIN_SIDE and height >= MIN_SIDE


HANDLE_RADIUS = 16


def corner_positions(x0, y0, x1, y1):
    return (
        ("nw", x0, y0),
        ("ne", x1, y0),
        ("se", x1, y1),
        ("sw", x0, y1),
    )


def hit_corner(x, y, x0, y0, x1, y1, radius=HANDLE_RADIUS):
    best = None
    best_distance = radius * radius
    for name, corner_x, corner_y in corner_positions(x0, y0, x1, y1):
        distance = (x - corner_x) ** 2 + (y - corner_y) ** 2
        if distance <= best_distance:
            best = name
            best_distance = distance
    return best


def set_corner(name, x0, y0, x1, y1, x, y):
    if name == "nw":
        return x, y, x1, y1
    if name == "ne":
        return x0, y, x, y1
    if name == "se":
        return x0, y0, x, y
    if name == "sw":
        return x, y0, x1, y
    return x0, y0, x1, y1


EDGE_THICKNESS = 8


def hit_edge(x, y, x0, y0, x1, y1, thickness=EDGE_THICKNESS):
    left, top, width, height = normalize_rect(x0, y0, x1, y1)
    right = left + width
    bottom = top + height
    near_vertical = abs(x - left) <= thickness or abs(x - right) <= thickness
    near_horizontal = abs(y - top) <= thickness or abs(y - bottom) <= thickness
    within_height = top - thickness <= y <= bottom + thickness
    within_width = left - thickness <= x <= right + thickness
    return (near_vertical and within_height) or (near_horizontal and within_width)


def point_inside(x, y, x0, y0, x1, y1):
    left, top, width, height = normalize_rect(x0, y0, x1, y1)
    return left <= x <= left + width and top <= y <= top + height


def rectangles_intersect(ax, ay, aw, ah, bx, by, bw, bh):
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by
