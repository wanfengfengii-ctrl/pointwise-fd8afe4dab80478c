from contextlib import closing
from hashlib import sha256
import json
import shutil

from bundle.publish import publish_window
from catalog.archive import initialize_archive, open_archive
from catalog.registration import register
from coefficients.index import BlockKey
from coefficients.integrity import BlockDataError
from coefficients.storage import get_block
from quality.export import export_receipt
from quality.inspection import inspect_window
from replay.open import open_package
from replay.window import read_window
from tests.fixtures import LINE, LINE_KEYS, StationCase, line_submission, original_positions


class ShiftWorkflowTests(StationCase):
    def test_archive_handoff_to_an_isolated_terminal(self):
        initialize_archive(self.db)
        r1 = self.register_sample()
        r2 = register(self.db, *line_submission('r2', high=(0, 12)))
        r1_digest = get_block(self.db, BlockKey(r1, 1, 'HL', 0, 1)).ref.digest
        r2_digest = get_block(self.db, BlockKey(r2, 1, 'HL', 0, 1)).ref.digest
        self.assertEqual(r1_digest, sha256(b'\x08').hexdigest())
        self.assertEqual(r2_digest, sha256(b'\x18').hexdigest())
        self.db.close()
        with closing(open_archive(self.archive_path)) as archive:
            full = publish_window(archive, self.packages, r1, LINE)
            package_id = self.publish_from_reopened(archive, r1)
            before = self.inventory()
            archive.execute(
                'DELETE FROM block_payloads WHERE scan = ? AND revision = ? AND band = ? AND block_col = 1',
                (r1.scan, r1.revision, 'HL'),
            )
            with self.assertRaises(BlockDataError):
                publish_window(archive, self.packages, r1, LINE)
            self.assertEqual(self.inventory(), before)
        offline = self.root / 'isolated-terminal'
        offline.mkdir()
        for identifier in (full, package_id):
            source = self.package_path(identifier)
            shutil.copyfile(source, offline / source.name)
        self.archive_path.unlink()
        shutil.rmtree(self.packages)
        reading = read_window(offline, package_id)
        full_reading = read_window(offline, full)
        self.assertEqual(full_reading.values, ((10, 14, 19, 28, 29),))
        self.assertEqual(reading.values, (full_reading.values[0][3:4],))
        self.assertEqual(reading.origin, (0, 3))
        receipt = inspect_window(offline, package_id, 28)
        handoff = self.root / 'handoff.json'
        handoff.write_bytes(export_receipt(receipt))
        review = json.loads(handoff.read_bytes())
        self.assertEqual(review, {
            'version': 1, 'package_id': package_id, 'revision': ['A017', 'r1'],
            'window': [0, 3, 1, 4], 'threshold': 28, 'points': [[0, 3, 28]],
        })
        self.assertEqual(original_positions(open_package(offline, review['package_id']).manifest), LINE_KEYS)
        self.assertEqual(read_window(offline, review['package_id']), reading)

    def publish_from_reopened(self, archive, key):
        from tests.fixtures import POINT

        return publish_window(archive, self.packages, key, POINT)
