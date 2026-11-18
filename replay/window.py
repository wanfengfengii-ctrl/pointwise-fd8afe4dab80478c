from itertools import repeat

from bundle.dependencies import band_window, projected_windows
from replay.coordinates import WindowReading
from replay.integer_steps import restore_even, restore_odd
from replay.open import OpenedPackage, open_package


def _inverse_axis(low, high):
    if not high:
        return tuple(low)
    even = tuple(
        restore_even(value, high[max(0, index - 1)], high[min(index, len(high) - 1)])
        for index, value in enumerate(low)
    )
    pixels = []
    for index, detail in enumerate(high):
        pixels.append(even[index])
        pixels.append(restore_odd(detail, even[index], even[min(index + 1, len(even) - 1)]))
    pixels.extend(even[len(high):])
    return tuple(pixels)


def _inverse_columns(low, high):
    high_columns = zip(*high) if high else repeat(())
    return tuple(_inverse_axis(low_column, high_column) for low_column, high_column in zip(zip(*low), high_columns))


def _inverse_tile(bands):
    vertical_low = _inverse_columns(bands["LL"], bands.get("LH", ()))
    vertical_high = _inverse_columns(bands.get("HL", ()), bands.get("HH", ()))
    high_rows = zip(*vertical_high) if vertical_high else repeat(())
    return tuple(_inverse_axis(low_row, high_row) for low_row, high_row in zip(zip(*vertical_low), high_rows))


def _crop(matrix, extent, region):
    start = region.left - extent.left
    stop = region.right - extent.left
    return tuple(row[start:stop] for row in matrix[region.top - extent.top:region.bottom - extent.top])


def _read_band(package, layer, band, region):
    return tuple(
        tuple(package.blocks.coefficient_at(layer, band, row, column) for column in range(region.left, region.right))
        for row in range(region.top, region.bottom)
    )


def replay_window(package: OpenedPackage):
    layout, window = package.manifest.layout, package.manifest.window
    previous = None
    for layer, pixels in reversed(tuple(projected_windows(layout, window))):
        bands = {
            band.name: _read_band(package, layer.number, band.name, band_window(pixels, band.name))
            for band in layout.stored_bands(layer.number)
        }
        if previous is not None:
            coarse_extent, coarse_matrix = previous
            bands["LL"] = _crop(coarse_matrix, coarse_extent, band_window(pixels, "LL"))
        matrix = _inverse_tile(bands)
        previous = pixels, matrix
    return WindowReading((window.top, window.left), _crop(matrix, pixels, window))


def read_window(directory, package_id):
    return replay_window(open_package(directory, package_id))
