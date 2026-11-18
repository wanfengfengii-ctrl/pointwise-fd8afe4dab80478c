from decimal import Decimal
import json

from quality.receipt import InspectionReceipt


def export_receipt(receipt):
    if not isinstance(receipt, InspectionReceipt):
        raise ValueError('expected a complete inspection receipt')
    binding = json.dumps(
        {
            'version': 1,
            'package_id': receipt.package_id,
            'revision': [receipt.revision.scan, receipt.revision.revision],
            'window': receipt.window.as_tuple(),
        },
        sort_keys=True, ensure_ascii=True, separators=(',', ':'),
    )
    # Decimal constructed from an integer renders the count exactly, including
    # counts beyond the interpreter's default int-to-decimal string limit.
    threshold = str(Decimal(receipt.threshold))
    points = ','.join(
        f'[{point.row},{point.column},{Decimal(point.value)}]' for point in receipt.points
    )
    return f'{binding[:-1]},"threshold":{threshold},"points":[{points}]}}'.encode('ascii')
