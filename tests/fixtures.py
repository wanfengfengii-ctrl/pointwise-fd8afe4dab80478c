import base64
import json
from pathlib import Path
import tempfile
import unittest

from bundle.publish import publish_window
from bundle.request import Window
from catalog.archive import open_archive
from catalog.layout import derive_layout
from catalog.registration import register
from catalog.revisions import Revision, RevisionKey
from coefficients.codec import encode_integers
from coefficients.coverage import BlockBounds
from coefficients.index import BlockInput, BlockKey
from station import load_submission


SAMPLES = Path(__file__).resolve().parents[1] / 'samples'
POINT = Window(0, 3, 1, 4)
LINE = Window(0, 0, 1, 5)
SQUARE = Window(0, 0, 2, 2)
LINE_KEYS = {(1, 'HL', 0, 0), (1, 'HL', 0, 1), (1, 'LL', 0, 1), (1, 'LL', 0, 2)}


def original_positions(manifest):
    return {(ref.key.layer, ref.key.band, ref.key.block_row, ref.key.block_column) for ref in manifest.blocks}


def tiled_submission(key, height, width, levels, bands, tile=(1, 1)):
    revision = Revision(key, derive_layout(height, width, levels))
    tile_height, tile_width = tile
    blocks = []
    for (layer, band), values in bands.items():
        for top in range(0, len(values), tile_height):
            for left in range(0, len(values[0]), tile_width):
                bottom = min(top + tile_height, len(values))
                right = min(left + tile_width, len(values[0]))
                bounds = BlockBounds(top, left, bottom, right)
                block_key = BlockKey(key, layer, band, top // tile_height, left // tile_width)
                payload = tuple(tuple(row[left:right]) for row in values[top:bottom])
                blocks.append(BlockInput(block_key, bounds, payload))
    return revision, tuple(blocks)


def line_submission(revision='r1', *, levels=1, vertical=False, tile=2 ** 0, high=(0, 4)):
    length = (5, 9, 17)[levels - 1]

    def line(values):
        if vertical:
            return tuple((value,) for value in values)
        return (tuple(values),)

    high_band = 'LH' if vertical else 'HL'
    bands = {(levels, 'LL'): line((10, 20, 31)), (levels, high_band): line(high)}
    for current in range(1, levels):
        finer_length = (5, 9, 17)[levels - current]
        bands[current, high_band] = line((0,) * (finer_length // 2))
    height, width = (length, 1) if vertical else (1, length)
    tile_shape = (tile, 1) if vertical else (1, tile)
    return tiled_submission(RevisionKey('A017', revision), height, width, levels, bands, tile_shape)


def encoded_values(values):
    return base64.b64encode(encode_integers(values)).decode('ascii')


class StationCase(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory(prefix='station-test-')
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        self.archive_path = self.root / 'archive.sqlite'
        self.db = open_archive(self.archive_path)
        self.addCleanup(self.db.close)
        self.packages = self.root / 'packages'
        self.packages.mkdir()

    def register_sample(self, sample='line'):
        return register(self.db, *load_submission(SAMPLES / f'{sample}.json'))

    def publish(self, key, window=POINT):
        return publish_window(self.db, self.packages, key, window)

    def package_path(self, package_id):
        return self.packages / f'{package_id}.json'

    def package_document(self, package_id):
        return json.loads(self.package_path(package_id).read_bytes())

    def write_document(self, package_id, document):
        self.package_path(package_id).write_text(json.dumps(document), encoding='utf-8')

    def inventory(self):
        return sorted(path.name for path in self.packages.iterdir())
