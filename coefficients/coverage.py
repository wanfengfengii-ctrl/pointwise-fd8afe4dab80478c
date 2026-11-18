from dataclasses import dataclass

from catalog.layout import is_coordinate


@dataclass(frozen=True)
class BlockBounds:
    top: int
    left: int
    bottom: int
    right: int

    def __post_init__(self):
        if not all(is_coordinate(value) for value in self.as_tuple()):
            raise ValueError('block bounds must be nonnegative SQLite coordinates')
        if self.top >= self.bottom or self.left >= self.right:
            raise ValueError('an original block must have positive height and width')

    @property
    def height(self):
        return self.bottom - self.top

    @property
    def width(self):
        return self.right - self.left

    @property
    def area(self):
        return self.height * self.width

    def as_tuple(self):
        return self.top, self.left, self.bottom, self.right

    def contains(self, row, column):
        return self.top <= row < self.bottom and self.left <= column < self.right

    def fits(self, rows, columns):
        return self.bottom <= rows and self.right <= columns


def validate_band_coverage(bounds, rows, columns, *, complete=True):
    events = {0: [], rows: []}
    for index, rectangle in enumerate(bounds):
        if not rectangle.fits(rows, columns):
            raise ValueError('original block crosses the band boundary')
        events.setdefault(rectangle.top, []).append((index, rectangle))
        events.setdefault(rectangle.bottom, []).append((index, None))
    active = {}
    # Between consecutive event rows the horizontal coverage is constant.
    for row in sorted(events)[:-1]:
        for index, rectangle in events[row]:
            if rectangle is None:
                del active[index]
            else:
                active[index] = rectangle
        right = 0
        for rectangle in sorted(active.values(), key=lambda item: item.left):
            if rectangle.left < right:
                raise ValueError(f'overlapping original blocks at row {row}')
            if complete and rectangle.left != right:
                raise ValueError(f'gap in original blocks at row {row}, column {right}')
            right = rectangle.right
        if complete and right != columns:
            raise ValueError(f'gap in original blocks at row {row}, column {right}')
