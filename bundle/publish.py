from bundle.dependencies import plan_block_keys
from bundle.manifest import build_manifest
from bundle.request import validate_window
from bundle.store import publish_package
from catalog.revisions import find_revision
from coefficients.integrity import BlockDataError
from coefficients.storage import get_block, load_block_index


def publish_window(connection, directory, key, window):
    revision = find_revision(connection, key)
    validate_window(window, revision.layout)
    index = load_block_index(connection, revision.key)
    required = plan_block_keys(revision, window, index)
    payloads = {}
    refs = []
    for block_key in required:
        block = get_block(connection, block_key)
        if block.ref != index.reference(block_key):
            raise BlockDataError(f'original block changed during pickup: {block_key!r}')
        refs.append(block.ref)
        payloads[block_key] = block.payload
    manifest = build_manifest(revision.key, revision.layout, window, refs)
    return publish_package(directory, manifest, payloads)
