from collections import defaultdict

from catalog.layout import validate_layout
from catalog.revisions import Revision, RevisionKey
from coefficients.codec import encode_integers
from coefficients.coverage import validate_band_coverage
from coefficients.index import BlockInput, BlockRef
from coefficients.integrity import payload_digest
from coefficients.storage import StoredBlock


def validate_registration(revision, blocks):
    if not isinstance(revision, Revision) or not isinstance(revision.key, RevisionKey):
        raise ValueError('expected a fixed scan revision')
    validate_layout(revision.layout)
    expected_bands = {
        (layer.number, band.name): band
        for layer in revision.layout.layers
        for band in revision.layout.stored_bands(layer.number)
    }
    coverage = defaultdict(list)
    keys = set()
    prepared = []
    for block in blocks:
        if not isinstance(block, BlockInput) or block.key.revision != revision.key:
            raise ValueError('block identity does not belong to the submitted revision')
        if block.key in keys:
            raise ValueError(f'duplicate original block {block.key!r}')
        keys.add(block.key)
        identity = (block.key.layer, block.key.band)
        band = expected_bands.get(identity)
        if band is None or not block.bounds.fits(band.rows, band.columns):
            raise ValueError(f'block is outside its stored band: {block.key!r}')
        if not isinstance(block.rows, (tuple, list)) or len(block.rows) != block.bounds.height:
            raise ValueError('block row count disagrees with the declared bounds')
        for row in block.rows:
            if not isinstance(row, (tuple, list)) or len(row) != block.bounds.width:
                raise ValueError('block column count disagrees with the declared bounds')
        values = tuple(value for row in block.rows for value in row)
        payload = encode_integers(values)
        ref = BlockRef(block.key, block.bounds, payload_digest(payload))
        prepared.append(StoredBlock(ref, payload, values))
        coverage[identity].append(block.bounds)
    for identity, band in expected_bands.items():
        try:
            validate_band_coverage(coverage[identity], band.rows, band.columns)
        except ValueError as exc:
            raise ValueError(f'invalid coverage of layer {identity[0]} band {identity[1]}: {exc}') from exc
    return tuple(sorted(prepared, key=lambda block: block.ref.key))
