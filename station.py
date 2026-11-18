import argparse
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile

from bundle.publish import publish_window
from bundle.request import Window
from catalog.archive import open_archive
from catalog.layout import layout_from_document
from catalog.registration import register
from catalog.revisions import Revision, RevisionKey
from coefficients.coverage import BlockBounds
from coefficients.index import BlockInput, BlockKey
from coefficients.storage import get_block
from quality.export import export_receipt
from quality.inspection import inspect_window
from replay.open import open_package
from replay.window import read_window


SAMPLES = Path(__file__).resolve().parent / 'samples'


def load_submission(path):
    document = json.loads(Path(path).read_bytes())
    if type(document) is not dict or document.keys() != {'scan', 'revision', 'layout', 'blocks'}:
        raise ValueError('invalid registration document fields')
    key = RevisionKey(document['scan'], document['revision'])
    revision = Revision(key, layout_from_document(document['layout']))
    blocks = []
    if type(document['blocks']) is not list:
        raise ValueError('registration blocks must be a list')
    for item in document['blocks']:
        if type(item) is not dict or item.keys() != {'layer', 'band', 'block', 'bounds', 'rows'}:
            raise ValueError('invalid registration block fields')
        if type(item['block']) is not list or len(item['block']) != 2:
            raise ValueError('original block needs a block row and column')
        if type(item['bounds']) is not list or len(item['bounds']) != 4:
            raise ValueError('original block needs four bounds')
        if type(item['rows']) is not list or any(type(row) is not list for row in item['rows']):
            raise ValueError('registration block needs row arrays')
        block_key = BlockKey(key, item['layer'], item['band'], *item['block'])
        blocks.append(BlockInput(block_key, BlockBounds(*item['bounds']), tuple(map(tuple, item['rows']))))
    return revision, tuple(blocks)


def demo():
    revision, blocks = load_submission(SAMPLES / 'line.json')
    correction = RevisionKey(revision.key.scan, 'r2')
    corrected_blocks = []
    detail = BlockKey(revision.key, 1, 'HL', 0, 1)
    for block in blocks:
        rows = ((12,),) if block.key == detail else block.rows
        corrected_blocks.append(replace(block, key=replace(block.key, revision=correction), rows=rows))
    window = Window(0, 3, 1, 4)
    with tempfile.TemporaryDirectory(prefix='line-review-') as name:
        root = Path(name)
        packages = root / 'packages'
        with closing(open_archive(root / 'archive.sqlite')) as archive:
            register(archive, revision, blocks)
            register(archive, replace(revision, key=correction), corrected_blocks)
            old_detail = get_block(archive, detail).values
            new_detail = get_block(archive, replace(detail, revision=correction)).values
            if (old_detail, new_detail) != ((4,), (12,)):
                raise RuntimeError('fixed revision block lookup differs from the submitted counts')
            package_id = publish_window(archive, packages, revision.key, window)
        opened = open_package(packages, package_id)
        actual_blocks = sorted([ref.key.band, ref.key.block_column] for ref in opened.manifest.blocks)
        expected_blocks = [['HL', 0], ['HL', 1], ['LL', 1], ['LL', 2]]
        reading = read_window(packages, package_id)
        receipt = json.loads(export_receipt(inspect_window(packages, package_id, 28)))
        actual = {
            'origin': list(reading.origin), 'values': [list(row) for row in reading.values],
            'blocks': actual_blocks,
        }
        expected = {'origin': [0, 3], 'values': [[28]], 'blocks': expected_blocks}
        downstream = {'points': receipt['points'], 'package_id': receipt['package_id']}
        downstream_expected = {'points': [[0, 3, 28]], 'package_id': package_id}
        if actual != expected or downstream != downstream_expected:
            raise RuntimeError(f'offline review differs from the hand-calculated result: {actual!r}, {downstream!r}')
        evidence = {
            'case_id': 'threshold',
            'input': {'L': [10, 20, 31], 'H': [0, 4], 'window': window.as_tuple(), 'threshold': 28},
            'expected': expected,
            'actual': actual,
            'downstream_expected': downstream_expected,
            'downstream_actual': downstream,
            'code_paths': ['bundle/dependencies.py', 'bundle/publish.py', 'replay/window.py', 'quality/inspection.py', 'quality/export.py'],
            'oracle': 'The original axis gives E[1]=19 and E[2]=29, so O[1]=4+(19+29)//2=28 and meets threshold 28.',
        }
        print('POINTWISE_SCENARIO ' + json.dumps(evidence, sort_keys=True))
        print(json.dumps(receipt, sort_keys=True))


def _arguments(argv):
    parser = argparse.ArgumentParser(description='Archive line scan coefficients and review offline windows')
    subcommands = parser.add_subparsers(dest='command', required=True)
    subcommands.add_parser('demo')
    registration = subcommands.add_parser('register')
    registration.add_argument('archive', type=Path)
    registration.add_argument('submission', type=Path)
    block = subcommands.add_parser('get-block')
    block.add_argument('archive', type=Path)
    block.add_argument('scan')
    block.add_argument('revision')
    block.add_argument('layer', type=int)
    block.add_argument('band')
    block.add_argument('block_row', type=int)
    block.add_argument('block_column', type=int)
    publish = subcommands.add_parser('publish')
    publish.add_argument('archive', type=Path)
    publish.add_argument('directory', type=Path)
    publish.add_argument('scan')
    publish.add_argument('revision')
    for coordinate in ('top', 'left', 'bottom', 'right'):
        publish.add_argument(coordinate, type=int)
    for name in ('read', 'inspect'):
        reader = subcommands.add_parser(name)
        reader.add_argument('directory', type=Path)
        reader.add_argument('package_id')
        if name == 'inspect':
            reader.add_argument('threshold', type=int)
    return parser.parse_args(argv)


def _run(args):
    if args.command == 'demo':
        demo()
        return
    if args.command == 'read':
        reading = read_window(args.directory, args.package_id)
        print(json.dumps({'origin': reading.origin, 'values': reading.values}))
        return
    if args.command == 'inspect':
        print(export_receipt(inspect_window(args.directory, args.package_id, args.threshold)).decode('ascii'))
        return
    with closing(open_archive(args.archive)) as archive:
        if args.command == 'register':
            revision, blocks = load_submission(args.submission)
            key = register(archive, revision, blocks)
            print(json.dumps({'scan': key.scan, 'revision': key.revision}))
            return
        key = RevisionKey(args.scan, args.revision)
        if args.command == 'get-block':
            block = get_block(archive, BlockKey(key, args.layer, args.band, args.block_row, args.block_column))
            print(json.dumps({'bounds': block.ref.bounds.as_tuple(), 'digest': block.ref.digest, 'values': block.values}))
            return
        window = Window(args.top, args.left, args.bottom, args.right)
        print(publish_window(archive, args.directory, key, window))


def main(argv=None):
    args = _arguments(argv)
    try:
        _run(args)
    except (OSError, LookupError, ValueError, RuntimeError, sqlite3.Error) as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
