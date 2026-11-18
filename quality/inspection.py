from quality.receipt import InspectionPoint, make_receipt
from quality.thresholds import meets_threshold, validate_threshold
from replay.open import open_package
from replay.window import replay_window


def inspect_window(directory, package_id, threshold):
    validate_threshold(threshold)
    package = open_package(directory, package_id)
    reading = replay_window(package)
    top, left = reading.origin
    points = (
        InspectionPoint(top + row, left + column, value)
        for row, values in enumerate(reading.values)
        for column, value in enumerate(values)
        if meets_threshold(value, threshold)
    )
    return make_receipt(package.manifest, threshold, points)
