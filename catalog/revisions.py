from dataclasses import dataclass
import json
import sqlite3

from catalog.layout import RevisionLayout, layout_document, layout_from_document


@dataclass(frozen=True, order=True)
class RevisionKey:
    scan: str
    revision: str

    def __post_init__(self):
        for value in (self.scan, self.revision):
            if type(value) is not str or not value or '\x00' in value:
                raise ValueError('scan and revision must be nonempty text without NUL')
            try:
                value.encode('utf-8')
            except UnicodeError as exc:
                raise ValueError('scan and revision must be valid UTF-8 text') from exc


@dataclass(frozen=True)
class Revision:
    key: RevisionKey
    layout: RevisionLayout


class RevisionNotFound(LookupError):
    pass


class RevisionDataError(ValueError):
    pass


def create_revision_schema(connection: sqlite3.Connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS revisions (
            scan TEXT NOT NULL,
            revision TEXT NOT NULL,
            layout TEXT NOT NULL,
            PRIMARY KEY (scan, revision)
        ) WITHOUT ROWID
    ''')


def insert_revision(connection, revision):
    encoded = json.dumps(layout_document(revision.layout), separators=(',', ':'))
    connection.execute(
        'INSERT INTO revisions (scan, revision, layout) VALUES (?, ?, ?)',
        (revision.key.scan, revision.key.revision, encoded),
    )


def find_revision(connection, key):
    row = connection.execute(
        'SELECT layout FROM revisions WHERE scan = ? AND revision = ?',
        (key.scan, key.revision),
    ).fetchone()
    if row is None:
        raise RevisionNotFound(f'unknown revision {key.scan}/{key.revision}')
    try:
        layout = layout_from_document(json.loads(row[0]))
    except (TypeError, ValueError) as exc:
        raise RevisionDataError(f'invalid stored layout for {key!r}') from exc
    return Revision(key, layout)
