import base64
import binascii
import os
from pathlib import Path
import tempfile

from bundle.manifest import (
    PackageError, block_key_document, block_key_from_document, canonical_json,
    decode_manifest, encode_manifest, load_json,
)
from coefficients.integrity import is_digest, verify_payload


class PackageStoreError(OSError):
    pass


def _package_path(directory, package_id):
    if not is_digest(package_id):
        raise PackageError('invalid package ID')
    return Path(directory) / f'{package_id}.json'


def _encode_package(manifest, payloads):
    manifest_document = load_json(encode_manifest(manifest))
    if set(payloads) != {ref.key for ref in manifest.blocks}:
        raise PackageError('payload keys do not match the manifest block directory')
    entries = []
    for ref in manifest.blocks:
        payload = payloads[ref.key]
        verify_payload(payload, ref.digest)
        entries.append({'key': block_key_document(ref.key), 'data': base64.b64encode(payload).decode('ascii')})
    return canonical_json({'manifest': manifest_document, 'payloads': entries})


def publish_package(directory, manifest, payloads):
    destination = _package_path(directory, manifest.package_id)
    encoded = _encode_package(manifest, payloads)
    pending = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='wb', dir=destination.parent, prefix='.pending-', delete=False) as stream:
            pending = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(pending, destination)
        except FileExistsError:
            if destination.read_bytes() != encoded:
                raise PackageStoreError('existing package at this ID differs from the staged content')
    except OSError as exc:
        raise PackageStoreError(f'cannot publish package {manifest.package_id}: {exc}') from exc
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
    return manifest.package_id


def load_package(directory, package_id):
    path = _package_path(directory, package_id)
    try:
        encoded = path.read_bytes()
    except OSError as exc:
        raise PackageError(f'cannot read package {package_id}: {exc}') from exc
    try:
        document = load_json(encoded)
        if type(document) is not dict or document.keys() != {'manifest', 'payloads'}:
            raise PackageError('invalid offline package envelope')
        manifest = decode_manifest(canonical_json(document['manifest']), expected_id=package_id)
        if type(document['payloads']) is not list:
            raise PackageError('offline payload directory must be a list')
        payloads = []
        for entry in document['payloads']:
            if type(entry) is not dict or entry.keys() != {'key', 'data'} or type(entry['data']) is not str:
                raise PackageError('invalid offline payload entry')
            key = block_key_from_document(entry['key'])
            payloads.append((key, base64.b64decode(entry['data'], validate=True)))
    except PackageError:
        raise
    except (TypeError, ValueError, binascii.Error, RecursionError) as exc:
        raise PackageError(f'cannot decode offline package: {exc}') from exc
    return manifest, tuple(payloads)
