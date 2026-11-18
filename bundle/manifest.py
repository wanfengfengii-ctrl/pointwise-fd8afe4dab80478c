from collections import defaultdict
from dataclasses import dataclass
import json

from bundle.request import Window, validate_window
from catalog.layout import RevisionLayout, layout_document, layout_from_document, validate_layout
from catalog.revisions import RevisionKey
from coefficients.coverage import BlockBounds, validate_band_coverage
from coefficients.index import BlockKey, BlockRef
from coefficients.integrity import is_digest, payload_digest


class PackageError(ValueError):
    pass


@dataclass(frozen=True)
class PackageManifest:
    package_id: str
    revision: RevisionKey
    layout: RevisionLayout
    window: Window
    blocks: tuple[BlockRef, ...]


def canonical_json(document):
    return json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def _unique_fields(pairs):
    document = {}
    for name, value in pairs:
        if name in document:
            raise PackageError(f'duplicate package field {name!r}')
        document[name] = value
    return document


def load_json(encoded):
    return json.loads(encoded, object_pairs_hook=_unique_fields)


def block_key_document(key):
    return [key.revision.scan, key.revision.revision, key.layer, key.band, key.block_row, key.block_column]


def block_key_from_document(document):
    if not isinstance(document, list) or len(document) != 6:
        raise PackageError('invalid original block identity in package')
    return BlockKey(RevisionKey(*document[:2]), *document[2:])


def _manifest_body(revision, layout, window, blocks):
    return {
        'version': 1,
        'revision': [revision.scan, revision.revision],
        'layout': layout_document(layout),
        'window': list(window.as_tuple()),
        'blocks': [
            {'key': block_key_document(ref.key), 'bounds': list(ref.bounds.as_tuple()), 'digest': ref.digest}
            for ref in blocks
        ],
    }


def _check_contents(revision, layout, window, blocks):
    if not isinstance(revision, RevisionKey):
        raise ValueError('manifest has no fixed revision')
    validate_layout(layout)
    validate_window(window, layout)
    by_band = defaultdict(list)
    previous = None
    for ref in blocks:
        if not isinstance(ref, BlockRef) or ref.key.revision != revision:
            raise ValueError('manifest block belongs to a different revision')
        if previous is not None and previous >= ref.key:
            raise ValueError('manifest original block keys must be unique and sorted')
        previous = ref.key
        by_band[(ref.key.layer, ref.key.band)].append(ref.bounds)
    for (level, name), bounds in by_band.items():
        band = layout.stored_band(level, name)
        validate_band_coverage(bounds, band.rows, band.columns, complete=False)


def build_manifest(revision, layout, window, refs):
    try:
        blocks = tuple(sorted(refs, key=lambda ref: ref.key))
        _check_contents(revision, layout, window, blocks)
        package_id = payload_digest(canonical_json(_manifest_body(revision, layout, window, blocks)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise PackageError(f'invalid package manifest: {exc}') from exc
    return PackageManifest(package_id, revision, layout, window, blocks)


def validate_manifest(manifest, expected_id=None):
    try:
        _check_contents(manifest.revision, manifest.layout, manifest.window, manifest.blocks)
        body = _manifest_body(manifest.revision, manifest.layout, manifest.window, manifest.blocks)
        if not is_digest(manifest.package_id) or manifest.package_id != payload_digest(canonical_json(body)):
            raise ValueError('package ID disagrees with its manifest')
        if expected_id is not None and manifest.package_id != expected_id:
            raise ValueError('manifest does not match the requested package ID')
    except (AttributeError, TypeError, ValueError) as exc:
        raise PackageError(f'invalid package manifest: {exc}') from exc


def encode_manifest(manifest):
    validate_manifest(manifest)
    body = _manifest_body(manifest.revision, manifest.layout, manifest.window, manifest.blocks)
    return canonical_json({**body, 'package_id': manifest.package_id})


def decode_manifest(encoded, expected_id=None):
    try:
        data = load_json(encoded)
        fields = {'version', 'revision', 'layout', 'window', 'blocks', 'package_id'}
        if type(data) is not dict or data.keys() != fields or type(data['version']) is not int or data['version'] != 1:
            raise PackageError('invalid manifest fields or manifest version')
        revision_doc, window_doc = data['revision'], data['window']
        if type(revision_doc) is not list or len(revision_doc) != 2:
            raise PackageError('invalid manifest revision key')
        if type(window_doc) is not list or len(window_doc) != 4:
            raise PackageError('invalid manifest window')
        if type(data['blocks']) is not list:
            raise PackageError('manifest block directory must be a list')
        blocks = []
        for entry in data['blocks']:
            if type(entry) is not dict or entry.keys() != {'key', 'bounds', 'digest'}:
                raise PackageError('invalid manifest block entry')
            bounds = entry['bounds']
            if type(bounds) is not list or len(bounds) != 4:
                raise PackageError('invalid original block bounds')
            blocks.append(BlockRef(block_key_from_document(entry['key']), BlockBounds(*bounds), entry['digest']))
        manifest = PackageManifest(
            data['package_id'], RevisionKey(*revision_doc), layout_from_document(data['layout']),
            Window(*window_doc), tuple(blocks),
        )
    except PackageError:
        raise
    except (TypeError, ValueError, RecursionError) as exc:
        raise PackageError(f'cannot decode package manifest: {exc}') from exc
    validate_manifest(manifest, expected_id)
    return manifest
