from contextlib import closing
from dataclasses import replace
from hashlib import sha256

from catalog.archive import initialize_archive, open_archive
from catalog.registration import RegistrationError, register
from catalog.revisions import RevisionNotFound, find_revision
from coefficients.codec import decode_integers, encode_integers
from coefficients.coverage import BlockBounds
from coefficients.index import BlockInput, BlockKey
from coefficients.integrity import BlockDataError
from coefficients.storage import get_block
from tests.fixtures import StationCase, line_submission


class RegistrationTests(StationCase):
    def test_fixed_revisions(self):
        r1 = self.register_sample()
        r2 = register(self.db, *line_submission('r2', high=(0, 12)))
        keys = [BlockKey(version, 1, 'HL', 0, 1) for version in (r1, r2)]
        for key, expected, encoded in zip(keys + keys, (4, 12, 4, 12), (8, 24, 8, 24)):
            block = get_block(self.db, key)
            self.assertEqual(block.values, (expected,))
            self.assertEqual(block.payload, bytes([encoded]))
            self.assertEqual(block.ref.key, key)
            self.assertEqual(block.ref.digest, sha256(bytes([encoded])).hexdigest())
        self.assertEqual(find_revision(self.db, r1).layout.columns, 5)
        with self.assertRaises(RegistrationError):
            register(self.db, *line_submission('r1', high=(0, 99)))
        self.assertEqual(get_block(self.db, keys[0]).values, (4,))

    def test_initialize_preserves_revisions_and_user_rows(self):
        r1 = self.register_sample()
        r2 = register(self.db, *line_submission('r2', high=(0, 12)))
        keys = [BlockKey(revision, 1, 'HL', 0, 1) for revision in (r1, r2)]
        before = [get_block(self.db, key) for key in keys]
        self.db.execute('CREATE TABLE shift_notes (note TEXT NOT NULL)')
        self.db.execute('INSERT INTO shift_notes VALUES (?)', ('A line checked',))
        self.db.close()
        with closing(open_archive(self.archive_path)) as reopened:
            initialize_archive(reopened)
            self.assertEqual([get_block(reopened, key) for key in keys], before)
            self.assertEqual(reopened.execute('SELECT note FROM shift_notes').fetchall(), [('A line checked',)])

    def test_registration_rolls_back_after_payload_write_failure(self):
        old = self.register_sample()
        revision, blocks = line_submission('r2')
        before = self.db.execute('SELECT COUNT(*) FROM block_payloads').fetchone()
        self.db.execute('''
            CREATE TRIGGER stop_second_payload BEFORE INSERT ON block_payloads
            WHEN NEW.revision = 'r2' AND EXISTS (
                SELECT 1 FROM block_payloads WHERE scan = NEW.scan AND revision = NEW.revision
            )
            BEGIN
                SELECT RAISE(ABORT, 'second payload rejected');
            END
        ''')
        with self.assertRaisesRegex(RegistrationError, 'second payload rejected'):
            register(self.db, revision, blocks)
        with closing(open_archive(self.archive_path)) as observer:
            with self.assertRaises(RevisionNotFound):
                find_revision(observer, revision.key)
            self.assertEqual(observer.execute('SELECT COUNT(*) FROM block_payloads').fetchone(), before)
            self.assertEqual(observer.execute('SELECT COUNT(*) FROM block_index WHERE revision = ?', ('r2',)).fetchone(), (0,))
            self.assertEqual(get_block(observer, BlockKey(old, 1, 'HL', 0, 1)).values, (4,))
        self.db.execute('DROP TRIGGER stop_second_payload')
        self.assertEqual(register(self.db, revision, blocks), revision.key)

    def test_payload_integrity_after_archive_corruption(self):
        key = self.register_sample()
        block_key = BlockKey(key, 1, 'HL', 0, 1)
        self.db.execute(
            'UPDATE block_payloads SET payload = ? WHERE scan = ? AND revision = ? AND layer = 1 AND band = ? AND block_row = 0 AND block_col = 1',
            (encode_integers((12,)), key.scan, key.revision, 'HL'),
        )
        with self.assertRaisesRegex(BlockDataError, 'digest'):
            get_block(self.db, block_key)
        self.assertEqual(get_block(self.db, BlockKey(key, 1, 'HL', 0, 0)).values, (0,))

    def test_reject_bad_edge_block(self):
        old = self.register_sample()
        revision, blocks = line_submission('edge', tile=2)
        edge_key = BlockKey(revision.key, 1, 'LL', 0, 1)
        invalid = tuple(
            replace(block, bounds=BlockBounds(0, 2, 1, 4), rows=((31, 77),))
            if block.key == edge_key else block for block in blocks
        )
        with self.assertRaises(RegistrationError):
            register(self.db, revision, invalid)
        with self.assertRaises(RevisionNotFound):
            find_revision(self.db, revision.key)
        self.assertEqual(get_block(self.db, BlockKey(old, 1, 'LL', 0, 2)).values, (31,))
        wrong_shape = tuple(replace(block, rows=((31, 77),)) if block.key == edge_key else block for block in blocks)
        with self.assertRaisesRegex(RegistrationError, 'column count'):
            register(self.db, revision, wrong_shape)
        register(self.db, revision, blocks)
        edge = get_block(self.db, edge_key)
        self.assertEqual(edge.ref.bounds, BlockBounds(0, 2, 1, 3))
        self.assertEqual(edge.values, (31,))

    def test_equal_area_overlap_and_gap_rejected(self):
        revision, blocks = line_submission('overlap', tile=2)
        edge = BlockKey(revision.key, 1, 'LL', 0, 1)
        invalid = tuple(
            BlockInput(edge, BlockBounds(0, 1, 1, 2), ((31,),)) if block.key == edge else block
            for block in blocks
        )
        with self.assertRaisesRegex(RegistrationError, 'overlapping'):
            register(self.db, revision, invalid)
        with self.assertRaises(RevisionNotFound):
            find_revision(self.db, revision.key)

    def test_invalid_counts_rejected_and_wide_integers_remain_exact(self):
        revision, blocks = line_submission('wide')
        invalid = (replace(blocks[0], rows=((True,),)), *blocks[1:])
        with self.assertRaisesRegex(RegistrationError, 'require integers'):
            register(self.db, revision, invalid)
        wide = -(1 << 130) + 7
        prepared = (replace(blocks[0], rows=((wide,),)), *blocks[1:])
        register(self.db, revision, prepared)
        self.assertEqual(get_block(self.db, blocks[0].key).values, (wide,))
        for malformed in (b'\x80', b'\x80\x00', b'\x00\x00'):
            with self.subTest(payload=malformed), self.assertRaises(ValueError):
                decode_integers(malformed, 1)
