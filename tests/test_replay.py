from copy import deepcopy
import json
import shutil

from bundle.manifest import PackageError, build_manifest, encode_manifest
from bundle.request import Window
from catalog.registration import register
from catalog.revisions import RevisionKey
from coefficients.integrity import BlockDataError
from quality.inspection import inspect_window
from replay.open import open_package
from replay.window import read_window
from tests.fixtures import (
    LINE, LINE_KEYS, POINT, SQUARE, StationCase, encoded_values, line_submission,
    original_positions, tiled_submission,
)


def dense_axis(low, high):
    if not high:
        return list(low)
    extended_high = [high[0], *high, high[-1]]
    evens = [value - (extended_high[i] + extended_high[i + 1] + 2) // 4 for i, value in enumerate(low)]
    extended_even = [*evens, evens[-1]]
    result = []
    for i, detail in enumerate(high):
        result.extend((evens[i], detail + (extended_even[i] + extended_even[i + 1]) // 2))
    result.extend(evens[len(high):])
    return result


def dense_fixture(rows, columns, layers):
    sizes = []
    bands = {}
    for level in range(1, layers + 1):
        sizes.append((rows, columns))
        low_rows, low_columns = (rows + 1) // 2, (columns + 1) // 2
        for band, height, width in (
            ('LL', low_rows, low_columns), ('HL', low_rows, columns // 2),
            ('LH', rows // 2, low_columns), ('HH', rows // 2, columns // 2),
        ):
            if height and width and (band != 'LL' or level == layers):
                offset = 2 * level + sum(ord(letter) for letter in band)
                bands[level, band] = tuple(
                    tuple((offset + 5 * row + 7 * column) % 19 - 9 for column in range(width))
                    for row in range(height)
                )
        rows, columns = low_rows, low_columns
    pixels = bands[layers, 'LL']
    for level in range(layers, 0, -1):
        height, width = sizes[level - 1]
        horizontal_low = []
        horizontal_high = []
        for low, high, count, output in (
            (pixels, bands.get((level, 'LH'), ()), (width + 1) // 2, horizontal_low),
            (bands.get((level, 'HL'), ()), bands.get((level, 'HH'), ()), width // 2, horizontal_high),
        ):
            for column in range(count):
                output.append(dense_axis([row[column] for row in low], [row[column] for row in high]))
        pixels = tuple(
            tuple(dense_axis([col[row] for col in horizontal_low], [col[row] for col in horizontal_high]))
            for row in range(height)
        )
    return bands, pixels


class ReplayTests(StationCase):
    def test_two_level_crop(self):
        key = register(self.db, *line_submission(levels=2))
        package_id = self.publish(key, Window(0, 5, 1, 6))
        whole_id = self.publish(key, Window(0, 0, 1, 9))
        self.db.close()
        reading = read_window(self.packages, package_id)
        self.assertEqual(reading.origin, (0, 5))
        self.assertEqual(reading.values, ((23,),))
        whole = read_window(self.packages, whole_id).values
        self.assertEqual(reading.values, (whole[0][5:6],))
        coarse = {(2, band, row, column) for _, band, row, column in LINE_KEYS}
        fine = {(1, 'HL', 0, column) for column in (1, 2, 3)}
        self.assertEqual(original_positions(open_package(self.packages, package_id).manifest), coarse | fine)

    def test_three_level_crop(self):
        key = register(self.db, *line_submission(levels=3))
        package_id = self.publish(key, Window(0, 11, 1, 12))
        self.db.close()
        reading = read_window(self.packages, package_id)
        self.assertEqual(reading.origin, (0, 11))
        self.assertEqual(reading.values, ((25,),))
        coarse = {(3, band, row, column) for _, band, row, column in LINE_KEYS}
        middle = {(2, 'HL', 0, column) for column in (1, 2, 3)}
        fine = {(1, 'HL', 0, column) for column in (4, 5, 6)}
        self.assertEqual(original_positions(open_package(self.packages, package_id).manifest), coarse | middle | fine)

    def test_singleton_axis_transpose(self):
        key = register(self.db, *line_submission(levels=2, vertical=True))
        package_id = self.publish(key, Window(5, 0, 6, 1))
        self.db.close()
        reading = read_window(self.packages, package_id)
        self.assertEqual(reading.origin, (5, 0))
        self.assertEqual(reading.values, ((23,),))

    def test_axis_rounding(self):
        key = self.register_sample('axes')
        package_id = self.publish(key, SQUARE)
        self.db.close()
        reading = read_window(self.packages, package_id)
        self.assertEqual(reading.origin, (0, 0))
        self.assertEqual(reading.values, ((-1, -2), (0, 2)))

    def test_signed_floor_in_both_steps(self):
        cases = [((0, 0), (-2,), (1, -1, 1)), ((-1, 0), (0,), (-1, -1, 0))]
        for index, (low, high, expected) in enumerate(cases):
            with self.subTest(low=low, high=high):
                key = RevisionKey('signed', str(index))
                register(self.db, *tiled_submission(key, 1, 3, 1, {(1, 'LL'): (low,), (1, 'HL'): (high,)}))
                package_id = self.publish(key, Window(0, 0, 1, 3))
                self.assertEqual(read_window(self.packages, package_id).values, (expected,))

    def test_changed_block_rejected(self):
        key = self.register_sample()
        package_id = self.publish(key)
        document = self.package_document(package_id)
        for entry in document['payloads']:
            if entry['key'][3:] == ['HL', 0, 1]:
                entry['data'] = encoded_values((12,))
                break
        else:
            self.fail('expected original H[1] in the published package')
        self.write_document(package_id, document)
        self.db.close()
        with self.assertRaisesRegex(BlockDataError, 'digest'):
            read_window(self.packages, package_id)
        with self.assertRaises(BlockDataError):
            inspect_window(self.packages, package_id, 28)

    def test_manifest_binding_rejects_swaps_and_duplicates(self):
        key = self.register_sample()
        first = self.publish(key)
        other = self.publish(key, LINE)
        good = self.package_document(first)
        other_document = self.package_document(other)
        replacement = deepcopy(good)
        replacement['manifest']['window'] = [0, 2, 1, 3]
        duplicate_ref = deepcopy(good)
        duplicate_ref['manifest']['blocks'].append(deepcopy(duplicate_ref['manifest']['blocks'][-1]))
        duplicate_payload = deepcopy(good)
        duplicate_payload['payloads'].append(deepcopy(duplicate_payload['payloads'][0]))
        mismatch = deepcopy(good)
        mismatch['payloads'] = other_document['payloads']
        directory = self.root / 'offline'
        directory.mkdir()
        source = self.package_path(first)
        target = directory / source.name
        self.db.close()
        shutil.copyfile(source, target)
        self.assertEqual(read_window(directory, first).values, ((28,),))
        cases = (
            (replacement, PackageError), (other_document, PackageError),
            (duplicate_ref, PackageError), (duplicate_payload, BlockDataError), (mismatch, BlockDataError),
        )
        for envelope, error in cases:
            with self.subTest(error=error, envelope=envelope):
                target.write_text(json.dumps(envelope), encoding='utf-8')
                with self.assertRaises(error):
                    read_window(directory, first)
                with self.assertRaises(error):
                    inspect_window(directory, first, 28)

    def test_self_consistent_manifest_missing_necessary_leaf_is_rejected(self):
        key = self.register_sample()
        package_id = self.publish(key)
        original = open_package(self.packages, package_id).manifest
        document = self.package_document(package_id)
        remaining = []
        for ref in original.blocks:
            if (ref.key.band, ref.key.block_column) != ('HL', 0):
                remaining.append(ref)
        self.assertEqual(len(original.blocks) - len(remaining), 1)
        reduced = build_manifest(key, original.layout, original.window, remaining)
        document['manifest'] = json.loads(encode_manifest(reduced))
        document['payloads'] = [entry for entry in document['payloads'] if entry['key'][3:] != ['HL', 0, 0]]
        self.write_document(reduced.package_id, document)
        self.db.close()
        self.assertEqual(len(open_package(self.packages, reduced.package_id).manifest.blocks), 3)
        with self.assertRaisesRegex(BlockDataError, 'HL\\[0,0\\]'):
            read_window(self.packages, reduced.package_id)
        with self.assertRaises(BlockDataError):
            inspect_window(self.packages, reduced.package_id, 28)

    def test_mixed_dimensions_match_independent_dense_reference(self):
        cases = ((1, 1, 3), (4, 3, 2), (3, 4, 1), (5, 7, 3), (7, 6, 2))
        issued = []
        for rows, columns, levels in cases:
            bands, whole = dense_fixture(rows, columns, levels)
            for tile in ((1, 1), (2, 3)):
                key = RevisionKey(f'{rows}x{columns}', f'{levels}-{tile[0]}')
                register(self.db, *tiled_submission(key, rows, columns, levels, bands, tile))
                windows = (
                    Window(0, 0, rows, columns),
                    Window(rows - 1, columns - 1, rows, columns),
                    Window(rows // 2, columns // 2, rows, columns),
                )
                for window in windows:
                    expected = tuple(row[window.left:window.right] for row in whole[window.top:window.bottom])
                    issued.append((self.publish(key, window), window, expected))
        self.db.close()
        for package_id, window, expected in issued:
            with self.subTest(package=package_id, window=window):
                reading = read_window(self.packages, package_id)
                self.assertEqual(reading.origin, (window.top, window.left))
                self.assertEqual(reading.values, expected)
