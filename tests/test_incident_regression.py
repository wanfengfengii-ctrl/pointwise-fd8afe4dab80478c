import json

from bundle.manifest import build_manifest, encode_manifest
from bundle.request import Window
from catalog.registration import register
from catalog.revisions import RevisionKey
from coefficients.codec import decode_integers
from coefficients.integrity import BlockDataError
from coefficients.index import BlockIndex
from replay.open import OpenedPackage, open_package
from replay.window import read_window, replay_window
from tests.fixtures import LINE_KEYS, POINT, StationCase, line_submission, original_positions, tiled_submission
from tests.test_replay import dense_fixture


class RecordingBlocks:
    """Records every original coefficient the replay actually reads."""

    def __init__(self, blocks):
        self._blocks = blocks
        self.accessed = set()

    def coefficient_at(self, layer, band, row, column):
        self.accessed.add((layer, band, row, column))
        return self._blocks.coefficient_at(layer, band, row, column)


def touched_blocks(package, accessed):
    index = package.blocks._index
    return {
        index.locate(package.manifest.revision, layer, band, row, column).key
        for layer, band, row, column in accessed
    }


class IncidentRegressionTests(StationCase):
    def reading_with_audit(self, package_id):
        package = open_package(self.packages, package_id)
        recorder = RecordingBlocks(package.blocks)
        reading = replay_window(OpenedPackage(package.manifest, recorder))
        return reading, touched_blocks(package, recorder.accessed)

    def test_single_point_package_reads_the_whole_crop(self):
        key = self.register_sample()
        point_id = self.publish(key, POINT)
        whole_id = self.publish(key, Window(0, 0, 1, 5))
        self.db.close()
        whole = read_window(self.packages, whole_id)
        reading, touched = self.reading_with_audit(point_id)
        self.assertEqual(whole.values, ((10, 14, 19, 28, 29),))
        self.assertEqual(reading.values, (whole.values[0][3:4],))
        self.assertEqual(reading.values, ((28,),))
        # The clamped H[0] neighbor of the first even coefficient is required.
        self.assertEqual(original_positions(open_package(self.packages, point_id).manifest), LINE_KEYS)
        self.assertEqual(touched, {ref.key for ref in open_package(self.packages, point_id).manifest.blocks})

    def test_retiling_does_not_change_the_reading(self):
        fine = self.register_sample()
        tiled = register(self.db, *line_submission('tiled', tile=2))
        fine_id = self.publish(fine)
        tiled_id = self.publish(tiled)
        self.db.close()
        self.assertEqual(read_window(self.packages, fine_id), read_window(self.packages, tiled_id))
        self.assertEqual(read_window(self.packages, fine_id).values, ((28,),))

    def test_window_reads_equal_the_same_slice_of_the_whole_image(self):
        for rows, columns, layers in ((3, 4, 1), (5, 7, 2), (7, 6, 3), (9, 9, 1), (2, 3, 2)):
            bands, whole = dense_fixture(rows, columns, layers)
            key = RevisionKey('slice', f'{rows}x{columns}-{layers}')
            register(self.db, *tiled_submission(key, rows, columns, layers, bands, (2, 1)))
            whole_id = self.publish(key, Window(0, 0, rows, columns))
            whole_reading = read_window(self.packages, whole_id)
            self.assertEqual(whole_reading.values, whole)
            for window in (
                Window(rows - 1, columns - 1, rows, columns),
                Window(0, columns - 1, 1, columns),
                Window(rows // 2, columns // 2, rows, columns),
                Window(0, 0, 1, 1),
            ):
                with self.subTest(shape=(rows, columns, layers), window=window.as_tuple()):
                    package_id = self.publish(key, window)
                    expected = tuple(row[window.left:window.right] for row in whole[window.top:window.bottom])
                    self.assertEqual(read_window(self.packages, package_id).values, expected)

    def test_dependencies_ignore_coefficient_values(self):
        first = self.register_sample()
        other = register(self.db, *line_submission('other', high=(99, 98)))
        first_id = self.publish(first, POINT)
        other_id = self.publish(other, POINT)
        self.db.close()
        self.assertEqual(
            original_positions(open_package(self.packages, first_id).manifest),
            original_positions(open_package(self.packages, other_id).manifest),
        )

    def test_self_consistent_package_without_a_required_clamp_block_is_rejected(self):
        # HL[0,0] carries the clamped left neighbor of LL[0,1]; without it the
        # point cannot be rebuilt, even though the reduced manifest is valid.
        key = self.register_sample()
        package_id = self.publish(key)
        original = open_package(self.packages, package_id).manifest
        document = self.package_document(package_id)
        remaining = tuple(ref for ref in original.blocks if ref.key.band != 'HL')
        reduced = build_manifest(key, original.layout, original.window, remaining)
        document['manifest'] = json.loads(encode_manifest(reduced))
        document['payloads'] = [entry for entry in document['payloads'] if entry['key'][3] != 'HL']
        self.write_document(reduced.package_id, document)
        self.db.close()
        self.assertEqual(len(open_package(self.packages, reduced.package_id).manifest.blocks), 2)
        with self.assertRaises(BlockDataError):
            read_window(self.packages, reduced.package_id)
