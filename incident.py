from contextlib import closing
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from bundle.publish import publish_window
from bundle.request import Window
from catalog.archive import open_archive
from catalog.registration import register
from quality.export import export_receipt
from quality.inspection import inspect_window
from replay.open import open_package
from replay.window import read_window
from station import SAMPLES, load_submission


def observe(archive_path, packages):
    revision, blocks = load_submission(SAMPLES / "line.json")
    with closing(open_archive(archive_path)) as archive:
        key = register(archive, revision, blocks)
        whole_id = publish_window(archive, packages, key, Window(0, 0, 1, 5))
        crop_id = publish_window(archive, packages, key, Window(0, 3, 1, 4))
    whole = read_window(packages, whole_id)
    crop = read_window(packages, crop_id)
    manifest = open_package(packages, crop_id).manifest
    receipt = json.loads(export_receipt(inspect_window(packages, crop_id, 28)))
    return {
        "whole_crop": [list(row[3:4]) for row in whole.values],
        "window": [list(row) for row in crop.values],
        "origin": list(crop.origin),
        "blocks": [[ref.key.layer, ref.key.band, ref.key.block_row, ref.key.block_column] for ref in manifest.blocks],
        "threshold_points": receipt["points"],
        "receipt_bound": receipt["package_id"] == crop_id,
    }


def main():
    expected = {
        "whole_crop": [[28]],
        "window": [[28]],
        "origin": [0, 3],
        "blocks": [[1, "HL", 0, 0], [1, "HL", 0, 1], [1, "LL", 0, 1], [1, "LL", 0, 2]],
        "threshold_points": [[0, 3, 28]],
        "receipt_bound": True,
    }
    with TemporaryDirectory(prefix="scan-window-incident-") as name:
        root = Path(name)
        actual = observe(root / "archive.sqlite", root / "packages")
    print(json.dumps({"actual": actual, "expected": expected}, sort_keys=True), flush=True)
    if actual != expected:
        print("WINDOW_RECONSTRUCTION_MISMATCH", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
