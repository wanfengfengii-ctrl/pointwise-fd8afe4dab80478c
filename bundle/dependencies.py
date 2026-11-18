from itertools import product

from bundle.request import Window
from catalog.layout import clamp_index


def _span(indices):
    return min(indices), max(indices) + 1


def axis_ranges(start, stop, axis):
    """Coefficient ranges needed to rebuild original pixels ``[start, stop)``.

    Returns ``((low_start, low_stop), (high_start, high_stop))``.  Neighbors are
    clamped inside the whole original axis, not inside the requested slice, so
    the result depends only on the layout geometry and never on coefficient
    values.  When a window touches the axis boundary the clamped boundary
    coefficient is still required even though it lies outside the slice range.
    """
    length = axis.length
    if length == 1:
        return (0, 1), (0, 0)
    low_count, high_count = axis.low, axis.high
    low_indices = set()
    high_indices = set()
    for pixel in range(start, stop):
        slot = pixel // 2
        if pixel & 1:
            high_indices.add(slot)
            even_slots = (slot, min(slot + 1, low_count - 1))
        else:
            even_slots = (slot,)
        for even_slot in even_slots:
            low_indices.add(even_slot)
            high_indices.add(clamp_index(even_slot - 1, high_count))
            high_indices.add(clamp_index(even_slot, high_count))
    return _span(low_indices), _span(high_indices)


def band_window(layer, pixels, band):
    """Rectangle of original coefficients in one stored band needed for ``pixels``."""
    horizontal, vertical = band
    low_rows, high_rows = axis_ranges(pixels.top, pixels.bottom, layer.rows)
    low_columns, high_columns = axis_ranges(pixels.left, pixels.right, layer.columns)
    top, bottom = low_rows if vertical == "L" else high_rows
    left, right = low_columns if horizontal == "L" else high_columns
    return Window(top, left, bottom, right)


def projected_windows(layout, window):
    """Yield each layer and the original-pixel window reconstructed there.

    The low-low band of a layer is the pixel domain of the next coarser layer,
    so the low coefficient range becomes the coarse window.
    """
    for layer in layout.layers:
        pixels = window
        yield layer, pixels
        low_rows = axis_ranges(pixels.top, pixels.bottom, layer.rows)[0]
        low_columns = axis_ranges(pixels.left, pixels.right, layer.columns)[0]
        window = Window(low_rows[0], low_columns[0], low_rows[1], low_columns[1])


def plan_block_keys(revision, window, index):
    keys = set()
    for layer, pixels in projected_windows(revision.layout, window):
        for band in revision.layout.stored_bands(layer.number):
            region = band_window(layer, pixels, band.name)
            for row, column in product(range(region.top, region.bottom), range(region.left, region.right)):
                ref = index.locate(revision.key, layer.number, band.name, row, column)
                keys.add(ref.key)
    return tuple(sorted(keys))
