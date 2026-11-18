from contextlib import contextmanager
import sqlite3

from catalog.revisions import create_revision_schema
from coefficients.storage import create_block_schema


class ArchiveError(RuntimeError):
    pass


@contextmanager
def write_transaction(connection):
    if connection.in_transaction:
        raise ArchiveError('an archive write requires a connection outside a transaction')
    try:
        connection.execute('BEGIN IMMEDIATE')
        try:
            yield
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
    except sqlite3.Error as exc:
        raise ArchiveError(f'archive write failed: {exc}') from exc


def initialize_archive(connection):
    if connection.in_transaction:
        raise ArchiveError('archive initialization requires its own transaction')
    connection.execute('PRAGMA foreign_keys = ON')
    with write_transaction(connection):
        create_revision_schema(connection)
        create_block_schema(connection)


def open_archive(path):
    try:
        connection = sqlite3.connect(path, isolation_level=None)
    except sqlite3.Error as exc:
        raise ArchiveError(f'cannot open archive: {exc}') from exc
    try:
        initialize_archive(connection)
    except BaseException:
        connection.close()
        raise
    return connection
