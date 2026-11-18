from bundle.dependencies import axis_ranges, projected_windows
from catalog.layout import clamp_index
from replay.coordinates import WindowReading
from replay.integer_steps import restore_even, restore_odd
from replay.open import OpenedPackage, open_package


def _rebuild_axis(start, stop, length, low_at, high_at):
    """Rebuild original axis pixels ``[start, stop)`` from low/high coefficients.

    ``low_at`` and ``high_at`` are indexed by whole-axis coefficient position and
    already apply the domain clamp; this keeps a cropped replay identical to the
    same slice of a whole-axis replay.
    """
    if length == 1:
        return tuple(low_at(0) for _ in range(start, stop))
    low_count, high_count = (length + 1) // 2, length // 2
    even_cache = {}

    def even(index):
        index = clamp_index(index, low_count)
        cached = even_cache.get(index)
        if cached is None:
            cached = restore_even(
                low_at(index),
                high_at(clamp_index(index - 1, high_count)),
                high_at(clamp_index(index, high_count)),
            )
            even_cache[index] = cached
        return cached

    pixels = []
    for position in range(start, stop):
        slot = position // 2
        if position & 1:
            pixels.append(restore_odd(
                high_at(clamp_index(slot, high_count)),
                even(slot),
                even(slot + 1),
            ))
        else:
            pixels.append(even(slot))
    return tuple(pixels)


def _reconstruct_layer(package, layer, pixels, predecessor):
    rows_axis, columns_axis = layer.rows, layer.columns
    low_columns, high_columns = axis_ranges(pixels.left, pixels.right, columns_axis)

    def coefficient(band, row, column):
        return package.blocks.coefficient_at(layer.number, band, row, column)

    if predecessor is None:
        def low_low(row, column):
            return coefficient('LL', row, column)
    else:
        extent, matrix = predecessor

        def low_low(row, column):
            return matrix[row - extent.top][column - extent.left]

    vertical_low = {}
    for column in range(low_columns[0], low_columns[1]):
        vertical_low[column] = _rebuild_axis(
            pixels.top, pixels.bottom, rows_axis.length,
            lambda row, column=column: low_low(row, column),
            lambda row, column=column: coefficient('LH', row, column),
        )
    vertical_high = {}
    for column in range(high_columns[0], high_columns[1]):
        vertical_high[column] = _rebuild_axis(
            pixels.top, pixels.bottom, rows_axis.length,
            lambda row, column=column: coefficient('HL', row, column),
            lambda row, column=column: coefficient('HH', row, column),
        )

    matrix = []
    for row in range(pixels.top, pixels.bottom):
        matrix.append(_rebuild_axis(
            pixels.left, pixels.right, columns_axis.length,
            lambda column, row=row: vertical_low[column][row - pixels.top],
            lambda column, row=row: vertical_high[column][row - pixels.top],
        ))
    return tuple(matrix)


def replay_window(package: OpenedPackage):
    layout, window = package.manifest.layout, package.manifest.window
    previous = None
    for layer, pixels in reversed(tuple(projected_windows(layout, window))):
        matrix = _reconstruct_layer(package, layer, pixels, previous)
        previous = pixels, matrix
    return WindowReading((window.top, window.left), previous[1])


def read_window(directory, package_id):
    return replay_window(open_package(directory, package_id))
