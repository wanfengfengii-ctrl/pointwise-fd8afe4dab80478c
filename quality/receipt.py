from dataclasses import dataclass

from bundle.manifest import PackageManifest
from bundle.request import Window
from catalog.layout import is_coordinate
from catalog.revisions import RevisionKey
from coefficients.integrity import is_digest
from quality.thresholds import meets_threshold, validate_threshold


@dataclass(frozen=True)
class InspectionPoint:
    row: int
    column: int
    value: int


@dataclass(frozen=True)
class InspectionReceipt:
    package_id: str
    revision: RevisionKey
    window: Window
    threshold: int
    points: tuple[InspectionPoint, ...]

    def __post_init__(self):
        if not is_digest(self.package_id) or not isinstance(self.revision, RevisionKey):
            raise ValueError('inspection receipt requires a verified package reference')
        window = self.window
        if (
            not isinstance(window, Window) or not all(is_coordinate(v) for v in window.as_tuple())
            or window.top >= window.bottom or window.left >= window.right
        ):
            raise ValueError('inspection receipt requires a nonempty window')
        validate_threshold(self.threshold)
        if not isinstance(self.points, tuple):
            raise ValueError('inspection receipt requires a fixed sequence of points')
        previous = None
        for point in self.points:
            if not isinstance(point, InspectionPoint) or type(point.value) is not int:
                raise ValueError('inspection point requires an integer count')
            if not is_coordinate(point.row) or not is_coordinate(point.column):
                raise ValueError('inspection point requires integer coordinates')
            if not (window.top <= point.row < window.bottom and window.left <= point.column < window.right):
                raise ValueError('inspection point lies outside the receipt window')
            if not meets_threshold(point.value, self.threshold):
                raise ValueError('inspection point is below the receipt threshold')
            coordinates = point.row, point.column
            if previous is not None and coordinates <= previous:
                raise ValueError('inspection points must be unique and in original row order')
            previous = coordinates


def make_receipt(manifest: PackageManifest, threshold, points):
    return InspectionReceipt(manifest.package_id, manifest.revision, manifest.window, threshold, tuple(points))
