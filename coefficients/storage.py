from dataclasses import dataclass
import sqlite3

from coefficients.codec import decode_integers
from coefficients.coverage import BlockBounds
from coefficients.index import BlockIndex, BlockKey, BlockRef
from coefficients.integrity import BlockDataError, verify_payload


@dataclass(frozen=True)
class StoredBlock:
    ref: BlockRef
    payload: bytes
    values: tuple[int, ...]


def create_block_schema(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS block_index (
            scan TEXT NOT NULL, revision TEXT NOT NULL,
            layer INTEGER NOT NULL, band TEXT NOT NULL,
            block_row INTEGER NOT NULL, block_col INTEGER NOT NULL,
            top INTEGER NOT NULL, left_edge INTEGER NOT NULL,
            bottom INTEGER NOT NULL, right_edge INTEGER NOT NULL,
            digest TEXT NOT NULL,
            PRIMARY KEY (scan, revision, layer, band, block_row, block_col),
            FOREIGN KEY (scan, revision) REFERENCES revisions (scan, revision)
        ) WITHOUT ROWID
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS block_payloads (
            scan TEXT NOT NULL, revision TEXT NOT NULL,
            layer INTEGER NOT NULL, band TEXT NOT NULL,
            block_row INTEGER NOT NULL, block_col INTEGER NOT NULL,
            payload BLOB NOT NULL,
            PRIMARY KEY (scan, revision, layer, band, block_row, block_col),
            FOREIGN KEY (scan, revision, layer, band, block_row, block_col)
                REFERENCES block_index (scan, revision, layer, band, block_row, block_col)
        ) WITHOUT ROWID
    ''')


def _key_arguments(key):
    return (
        key.revision.scan, key.revision.revision, key.layer, key.band,
        key.block_row, key.block_column,
    )


def _reference(key, row):
    return BlockRef(key, BlockBounds(*row[:4]), row[4])


def insert_blocks(connection, blocks):
    for block in blocks:
        key = _key_arguments(block.ref.key)
        connection.execute('''
            INSERT INTO block_index (
                scan, revision, layer, band, block_row, block_col,
                top, left_edge, bottom, right_edge, digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (*key, *block.ref.bounds.as_tuple(), block.ref.digest))
        connection.execute('''
            INSERT INTO block_payloads (
                scan, revision, layer, band, block_row, block_col, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (*key, block.payload))


def load_block_index(connection, revision):
    try:
        rows = connection.execute('''
            SELECT layer, band, block_row, block_col, top, left_edge, bottom, right_edge, digest
            FROM block_index WHERE scan = ? AND revision = ?
            ORDER BY layer, band, block_row, block_col
        ''', (revision.scan, revision.revision))
        return BlockIndex(_reference(BlockKey(revision, *row[:4]), row[4:]) for row in rows)
    except (sqlite3.Error, ValueError) as exc:
        raise BlockDataError(f'cannot read the original block index for {revision!r}: {exc}') from exc


def get_block(connection, key):
    try:
        row = connection.execute('''
            SELECT p.payload, b.top, b.left_edge, b.bottom, b.right_edge, b.digest
            FROM block_payloads AS p JOIN block_index AS b
              USING (scan, revision, layer, band, block_row, block_col)
            WHERE p.scan = ? AND p.revision = ? AND p.layer = ?
              AND p.band = ? AND p.block_row = ? AND p.block_col = ?
        ''', _key_arguments(key)).fetchone()
        if row is None:
            raise BlockDataError('original block is missing')
        payload = row[0]
        ref = _reference(key, row[1:])
        verify_payload(payload, ref.digest)
        values = decode_integers(payload, ref.bounds.area)
    except (sqlite3.Error, ValueError) as exc:
        raise BlockDataError(f'cannot read original block {key!r}: {exc}') from exc
    return StoredBlock(ref, payload, values)
