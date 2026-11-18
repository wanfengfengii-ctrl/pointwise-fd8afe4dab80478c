from dataclasses import dataclass

from catalog.layout import is_coordinate


class WindowError(ValueError):
    pass


@dataclass(frozen=True)
class Window:
    top: int
    left: int
    bottom: int
    right: int

    def as_tuple(self):
        return self.top, self.left, self.bottom, self.right


def validate_window(window, layout):
    if not isinstance(window, Window) or not all(is_coordinate(v) for v in window.as_tuple()):
        raise WindowError('window requires four nonnegative integer coordinates')
    if not (window.top < window.bottom <= layout.rows and window.left < window.right <= layout.columns):
        raise WindowError('window must be a nonempty half-open rectangle inside the original extent')
