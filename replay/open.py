from dataclasses import dataclass

from bundle.manifest import PackageManifest
from bundle.store import load_package
from replay.payloads import PackageBlocks, load_package_blocks


@dataclass(frozen=True)
class OpenedPackage:
    manifest: PackageManifest
    blocks: PackageBlocks


def open_package(directory, package_id):
    manifest, entries = load_package(directory, package_id)
    return OpenedPackage(manifest, load_package_blocks(manifest, entries))
