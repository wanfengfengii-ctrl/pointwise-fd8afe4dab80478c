from dataclasses import dataclass


MAX_COORDINATE = (1 << 63) - 1
BAND_NAMES = ('LL', 'HL', 'LH', 'HH')


def is_coordinate(value):
    return type(value) is int and 0 <= value <= MAX_COORDINATE


@dataclass(frozen=True)
class AxisLayout:
    length: int

    def __post_init__(self):
        if not is_coordinate(self.length) or self.length == 0:
            raise ValueError('axis length must be a positive SQLite coordinate')

    @property
    def low(self):
        return (self.length + 1) // 2

    @property
    def high(self):
        return self.length // 2


@dataclass(frozen=True)
class BandLayout:
    name: str
    rows: int
    columns: int

    def __post_init__(self):
        if self.name not in BAND_NAMES:
            raise ValueError('unknown coefficient band')
        if not is_coordinate(self.rows) or not is_coordinate(self.columns):
            raise ValueError('invalid band dimensions')

    @property
    def empty(self):
        return self.rows == 0 or self.columns == 0


@dataclass(frozen=True)
class LayerLayout:
    number: int
    rows: AxisLayout
    columns: AxisLayout
    bands: tuple[BandLayout, ...]


@dataclass(frozen=True)
class RevisionLayout:
    layers: tuple[LayerLayout, ...]

    @property
    def rows(self):
        return self.layers[0].rows.length

    @property
    def columns(self):
        return self.layers[0].columns.length

    def stored_bands(self, level):
        if type(level) is not int or not 1 <= level <= len(self.layers):
            raise ValueError('unknown layer')
        return tuple(
            band for band in self.layers[level - 1].bands
            if not band.empty and (band.name != 'LL' or level == len(self.layers))
        )

    def stored_band(self, level, name):
        for band in self.stored_bands(level):
            if band.name == name:
                return band
        raise ValueError(f'layer {level} has no stored {name} band')


def derive_layout(rows, columns, levels):
    if type(levels) is not int or not 1 <= levels <= 3:
        raise ValueError('a revision must have one to three layers')
    layers = []
    for number in range(1, levels + 1):
        vertical, horizontal = AxisLayout(rows), AxisLayout(columns)
        bands = (
            BandLayout('LL', vertical.low, horizontal.low),
            BandLayout('HL', vertical.low, horizontal.high),
            BandLayout('LH', vertical.high, horizontal.low),
            BandLayout('HH', vertical.high, horizontal.high),
        )
        layers.append(LayerLayout(number, vertical, horizontal, bands))
        rows, columns = vertical.low, horizontal.low
    return RevisionLayout(tuple(layers))


def validate_layout(layout):
    if not isinstance(layout, RevisionLayout) or not isinstance(layout.layers, tuple):
        raise ValueError('expected a revision layout')
    if not 1 <= len(layout.layers) <= 3:
        raise ValueError('a revision must have one to three layers')
    for layer in layout.layers:
        if (
            not isinstance(layer, LayerLayout) or type(layer.number) is not int
            or not isinstance(layer.rows, AxisLayout)
            or not isinstance(layer.columns, AxisLayout)
        ):
            raise ValueError('invalid layer declaration')
    if layout != derive_layout(layout.rows, layout.columns, len(layout.layers)):
        raise ValueError('layer or band dimensions disagree with the original extent')


def layout_document(layout):
    return [[layer.rows.length, layer.columns.length] for layer in layout.layers]


def layout_from_document(dimensions):
    if not isinstance(dimensions, list) or not 1 <= len(dimensions) <= 3:
        raise ValueError('invalid layer dimensions')
    for pair in dimensions:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError('each layer needs a row and a column length')
        AxisLayout(pair[0])
        AxisLayout(pair[1])
    layout = derive_layout(*dimensions[0], len(dimensions))
    if dimensions != layout_document(layout):
        raise ValueError('declared layer extent disagrees with the derived layout')
    return layout


def clamp_index(index, length):
    if length <= 0:
        raise ValueError('cannot select a neighbor on an empty axis')
    return min(max(index, 0), length - 1)
