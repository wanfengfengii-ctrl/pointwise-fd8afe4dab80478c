from collections import defaultdict
from dataclasses import dataclass

from catalog.layout import BAND_NAMES, is_coordinate
from catalog.revisions import RevisionKey
from coefficients.coverage import BlockBounds
from coefficients.integrity import BlockDataError, is_digest


@dataclass(frozen=True, order=True)
class BlockKey:
    revision: RevisionKey
    layer: int
    band: str
    block_row: int
    block_column: int

    def __post_init__(self):
        if not isinstance(self.revision, RevisionKey):
            raise ValueError('block requires a fixed revision key')
        if type(self.layer) is not int or not 1 <= self.layer <= 3:
            raise ValueError('invalid block layer')
        if self.band not in BAND_NAMES:
            raise ValueError('invalid block band')
        if not is_coordinate(self.block_row) or not is_coordinate(self.block_column):
            raise ValueError('invalid block coordinates')


@dataclass(frozen=True)
class BlockInput:
    key: BlockKey
    bounds: BlockBounds
    rows: tuple[tuple[int, ...], ...]

    def __post_init__(self):
        if not isinstance(self.key, BlockKey) or not isinstance(self.bounds, BlockBounds):
            raise ValueError('block requires an original identity and bounds')


@dataclass(frozen=True)
class BlockRef:
    key: BlockKey
    bounds: BlockBounds
    digest: str

    def __post_init__(self):
        if not isinstance(self.key, BlockKey) or not isinstance(self.bounds, BlockBounds):
            raise ValueError('block reference requires an identity and bounds')
        if not is_digest(self.digest):
            raise ValueError('invalid original block digest')


class BlockIndex:
    def __init__(self, refs):
        refs_by_key = {}
        bands = defaultdict(list)
        for ref in refs:
            key = ref.key
            if key in refs_by_key:
                raise BlockDataError(f'duplicate original block identity: {key!r}')
            refs_by_key[key] = ref
            bands[(key.revision, key.layer, key.band)].append(ref)
        self._refs_by_key = refs_by_key
        self._bands = {band: tuple(items) for band, items in bands.items()}

    def reference(self, key):
        try:
            return self._refs_by_key[key]
        except KeyError as exc:
            raise BlockDataError(f'original block is absent from the index: {key!r}') from exc

    def locate(self, revision, layer, band, row, column):
        candidates = self._bands.get((revision, layer, band), ())
        match = None
        for ref in candidates:
            if ref.bounds.contains(row, column):
                if match is not None:
                    raise BlockDataError(f'multiple original blocks cover layer {layer} {band}[{row},{column}]')
                match = ref
        if match is None:
            raise BlockDataError(f'no original block covers {revision!r} layer {layer} {band}[{row},{column}]')
        return match
