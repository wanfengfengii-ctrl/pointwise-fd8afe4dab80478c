from itertools import product

from bundle.request import Window


def _aligned_extent(start, stop, axis):
    first_pair = min(start // 2, max(0, axis.high - 1))
    last_pair, odd = divmod(stop - 1, 2)
    return 2 * first_pair, min(axis.length, 2 * (last_pair + 1) + odd)


def band_window(pixels, band):
    horizontal, vertical = band
    return Window(
        pixels.top // 2, pixels.left // 2,
        (pixels.bottom + (vertical == "L")) // 2,
        (pixels.right + (horizontal == "L")) // 2,
    )


def projected_windows(layout, window):
    for layer in layout.layers:
        top, bottom = _aligned_extent(window.top, window.bottom, layer.rows)
        left, right = _aligned_extent(window.left, window.right, layer.columns)
        pixels = Window(top, left, bottom, right)
        yield layer, pixels
        window = band_window(pixels, "LL")


def plan_block_keys(revision, window, index):
    keys = set()
    for layer, pixels in projected_windows(revision.layout, window):
        for band in revision.layout.stored_bands(layer.number):
            region = band_window(pixels, band.name)
            for row, column in product(range(region.top, region.bottom), range(region.left, region.right)):
                ref = index.locate(revision.key, layer.number, band.name, row, column)
                keys.add(ref.key)
    return tuple(sorted(keys))
