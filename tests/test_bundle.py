from contextlib import contextmanager
import re

from bundle.publish import publish_window
from bundle.request import Window, WindowError
from bundle.store import PackageStoreError
from catalog.registration import register
from coefficients.codec import encode_integers
from coefficients.integrity import BlockDataError
from replay.open import open_package
from replay.window import read_window
from tests.fixtures import LINE, LINE_KEYS, POINT, StationCase, line_submission, original_positions


@contextmanager
def trace_archive(connection):
    statements = []
    connection.set_trace_callback(statements.append)
    try:
        yield statements
    finally:
        connection.set_trace_callback(None)


def fetched_positions(statements):
    positions = []
    pattern = re.compile(
        r"p\.layer = (\d+)\s+AND p\.band = '([A-Z]+)' AND p\.block_row = (\d+) AND p\.block_col = (\d+)"
    )
    for statement in statements:
        if not statement.lstrip().startswith('SELECT p.payload,'):
            continue
        match = pattern.search(statement)
        if not match:
            raise AssertionError(f'payload lookup lost its original block coordinates: {statement.strip()}')
        layer, band, row, column = match.groups()
        positions.append((int(layer), band, int(row), int(column)))
    return positions


class BundleTests(StationCase):
    def test_window_original_blocks(self):
        key = self.register_sample()
        package_id = self.publish(key)
        opened = open_package(self.packages, package_id)
        self.assertEqual(opened.manifest.revision, key)
        self.assertEqual(opened.manifest.window, POINT)
        self.assertEqual(original_positions(opened.manifest), LINE_KEYS)
        self.assertEqual(len(opened.manifest.blocks), 4)
        self.assertEqual(self.publish(key), package_id)
        self.assertEqual(self.inventory(), [f'{package_id}.json'])

    def test_only_required_payloads_are_fetched(self):
        key = self.register_sample()
        self.db.execute(
            'UPDATE block_payloads SET payload = ? WHERE scan = ? AND revision = ? AND band = ? AND block_col = 0',
            (encode_integers((99,)), key.scan, key.revision, 'LL'),
        )
        with trace_archive(self.db) as statements:
            package_id = self.publish(key)
        fetched = fetched_positions(statements)
        self.assertCountEqual(fetched, LINE_KEYS)
        self.assertEqual(original_positions(open_package(self.packages, package_id).manifest), LINE_KEYS)
        self.assertEqual(read_window(self.packages, package_id).values, ((28,),))

    def test_retile_preserves_reading_and_uses_new_original_blocks(self):
        fine = self.register_sample()
        tiled = register(self.db, *line_submission('tiled', tile=2))
        fine_id = self.publish(fine)
        tiled_id = self.publish(tiled)
        fine_package = open_package(self.packages, fine_id)
        tiled_package = open_package(self.packages, tiled_id)
        self.assertEqual(original_positions(fine_package.manifest), LINE_KEYS)
        self.assertEqual(original_positions(tiled_package.manifest), {(1, 'HL', 0, 0), (1, 'LL', 0, 0), (1, 'LL', 0, 1)})
        bounds = {(ref.key.band, ref.key.block_column): ref.bounds.as_tuple() for ref in tiled_package.manifest.blocks}
        self.assertEqual(bounds, {('HL', 0): (0, 0, 1, 2), ('LL', 0): (0, 0, 1, 2), ('LL', 1): (0, 2, 1, 3)})
        self.assertEqual(read_window(self.packages, fine_id), read_window(self.packages, tiled_id))
        self.assertEqual(read_window(self.packages, tiled_id).values, ((28,),))

    def test_out_of_extent_window(self):
        key = self.register_sample()
        with trace_archive(self.db) as statements:
            with self.assertRaises(WindowError):
                self.publish(key, Window(0, 4, 1, 6))
        self.assertEqual(fetched_positions(statements), [])
        self.assertEqual(self.inventory(), [])

    def test_half_open_final_pixel_and_empty_window(self):
        key = self.register_sample()
        package_id = self.publish(key, Window(0, 4, 1, 5))
        self.assertEqual(read_window(self.packages, package_id).values, ((29,),))
        before = self.inventory()
        for window in (Window(0, 4, 1, 4), Window(0, 4, 0, 5), Window(-1, 0, 1, 1), Window(0, 4, 1, 6)):
            with self.subTest(window=window), self.assertRaises(WindowError):
                self.publish(key, window)
        self.assertEqual(self.inventory(), before)

    def test_required_block_failure(self):
        key = self.register_sample()
        old = self.publish(key)
        before = self.inventory()
        self.db.execute(
            'DELETE FROM block_payloads WHERE scan = ? AND revision = ? AND band = ? AND block_col = 2',
            (key.scan, key.revision, 'LL'),
        )
        with trace_archive(self.db) as statements:
            with self.assertRaisesRegex(BlockDataError, 'missing'):
                self.publish(key, LINE)
        fetched = fetched_positions(statements)
        self.assertEqual(fetched[0], (1, 'HL', 0, 0))
        self.assertEqual(fetched[-1], (1, 'LL', 0, 2))
        self.assertGreater(len(fetched), 1)
        self.db.close()
        self.assertEqual(self.inventory(), before)
        self.assertEqual(read_window(self.packages, old).values, ((28,),))

    def test_unreadable_required_payload(self):
        key = self.register_sample()
        old = self.publish(key)
        before = self.inventory()
        self.db.execute(
            'UPDATE block_payloads SET payload = ? WHERE scan = ? AND revision = ? AND band = ? AND block_col = 1',
            (encode_integers((12,)), key.scan, key.revision, 'HL'),
        )
        with self.assertRaisesRegex(BlockDataError, 'digest'):
            self.publish(key, LINE)
        self.assertEqual(self.inventory(), before)
        self.db.close()
        self.assertEqual(read_window(self.packages, old).values, ((28,),))

    def test_commit_failure_cleans_stage_and_preserves_old_package(self):
        key = self.register_sample()
        previous = self.publish(key)
        expected_id = publish_window(self.db, self.root / 'second-directory', key, LINE)
        obstruction = self.package_path(expected_id)
        obstruction.mkdir()
        (obstruction / 'owner.txt').write_text('existing directory', encoding='utf-8')
        before = self.inventory()
        with trace_archive(self.db) as statements:
            with self.assertRaises(PackageStoreError):
                self.publish(key, LINE)
        self.assertCountEqual(fetched_positions(statements), LINE_KEYS | {(1, 'LL', 0, 0)})
        self.assertEqual(self.inventory(), before)
        self.assertEqual((obstruction / 'owner.txt').read_text(encoding='utf-8'), 'existing directory')
        self.db.close()
        self.assertEqual(read_window(self.packages, previous).values, ((28,),))
