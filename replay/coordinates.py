from dataclasses import dataclass

from bundle.request import Window
from catalog.layout import clamp_index


@dataclass(frozen=True)
class StagePoint:
    layer: int
    stage: str
    row: int
    column: int


@dataclass(frozen=True)
class WindowReading:
    origin: tuple[int, int]
    values: tuple[tuple[int, ...], ...]


def axis_neighbors(axis, position):
    if not 0 <= position < axis.length:
        raise ValueError('stage coordinate lies outside the original axis')
    slot, parity = divmod(position, 2)
    if axis.length == 1:
        return (slot,)
    if parity:
        return slot, 2 * slot, 2 * clamp_index(slot + 1, axis.low)
    return slot, clamp_index(slot - 1, axis.high), clamp_index(slot, axis.high)


def iter_window_points(window: Window):
    for row in range(window.top, window.bottom):
        for column in range(window.left, window.right):
            yield row, column
