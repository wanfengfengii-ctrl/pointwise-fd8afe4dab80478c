from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from bundle.manifest import PackageManifest
from catalog.revisions import RevisionKey
from coefficients.codec import decode_integers
from coefficients.index import BlockIndex, BlockKey
from coefficients.integrity import BlockDataError, verify_payload


@dataclass(frozen=True)
class PackageBlocks:
    revision: RevisionKey
    _index: BlockIndex
    _values: Mapping[BlockKey, tuple[int, ...]]

    def coefficient_at(self, layer, band, row, column):
        ref = self._index.locate(self.revision, layer, band, row, column)
        offset = (row - ref.bounds.top) * ref.bounds.width + column - ref.bounds.left
        return self._values[ref.key][offset]


def load_package_blocks(manifest: PackageManifest, entries):
    payloads = {}
    for key, payload in entries:
        if key in payloads:
            raise BlockDataError(f'duplicate offline payload for {key!r}')
        payloads[key] = payload
    if payloads.keys() != {ref.key for ref in manifest.blocks}:
        raise BlockDataError('offline payload directory disagrees with the manifest')
    values = {}
    for ref in manifest.blocks:
        try:
            payload = payloads[ref.key]
            verify_payload(payload, ref.digest)
            values[ref.key] = decode_integers(payload, ref.bounds.area)
        except ValueError as exc:
            raise BlockDataError(f'invalid offline payload for {ref.key!r}: {exc}') from exc
    return PackageBlocks(manifest.revision, BlockIndex(manifest.blocks), MappingProxyType(values))
