from catalog.archive import ArchiveError, write_transaction
from catalog.revisions import insert_revision
from catalog.validation import validate_registration
from coefficients.storage import insert_blocks


class RegistrationError(ValueError):
    pass


def register(connection, revision, blocks):
    try:
        prepared = validate_registration(revision, blocks)
        with write_transaction(connection):
            insert_revision(connection, revision)
            insert_blocks(connection, prepared)
    except (TypeError, ValueError, ArchiveError) as exc:
        raise RegistrationError(f'revision registration rejected: {exc}') from exc
    return revision.key
