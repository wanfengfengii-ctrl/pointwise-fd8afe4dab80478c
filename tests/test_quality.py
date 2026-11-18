import json

from bundle.request import Window
from catalog.registration import register
from quality.export import export_receipt
from quality.inspection import inspect_window
from quality.receipt import InspectionPoint
from replay.open import open_package
from replay.window import read_window
from tests.fixtures import LINE_KEYS, POINT, SQUARE, StationCase, line_submission, original_positions


class InspectionTests(StationCase):
    def test_threshold_equality(self):
        key = self.register_sample()
        package_id = self.publish(key)
        self.db.close()
        receipt = inspect_window(self.packages, package_id, 28)
        self.assertEqual(receipt.points, (InspectionPoint(0, 3, 28),))
        self.assertEqual((receipt.package_id, receipt.revision, receipt.window), (package_id, key, POINT))
        self.assertEqual(receipt.threshold, 28)
        self.assertEqual(json.loads(export_receipt(receipt))['points'], [[0, 3, 28]])

    def test_global_neighborhood_and_nonzero_neighbor(self):
        key = self.register_sample()
        changed = register(self.db, *line_submission('changed', high=(12, 4)))
        package_id = self.publish(key)
        changed_id = self.publish(changed)
        self.db.close()
        for issued in (package_id, changed_id):
            self.assertEqual(original_positions(open_package(self.packages, issued).manifest), LINE_KEYS)
        self.assertEqual(read_window(self.packages, package_id).values, ((28,),))
        self.assertEqual(read_window(self.packages, changed_id).values, ((26,),))
        self.assertEqual(inspect_window(self.packages, package_id, 28).points, (InspectionPoint(0, 3, 28),))
        self.assertEqual(inspect_window(self.packages, changed_id, 28).points, ())

    def test_audit_order_and_equality(self):
        key = self.register_sample('axes')
        package_id = self.publish(key, SQUARE)
        self.db.close()
        receipt = inspect_window(self.packages, package_id, -2)
        expected = [[0, 0, -1], [0, 1, -2], [1, 0, 0], [1, 1, 2]]
        self.assertEqual([[point.row, point.column, point.value] for point in receipt.points], expected)
        encoded = export_receipt(receipt)
        self.assertEqual(encoded, export_receipt(receipt))
        self.assertEqual(json.loads(encoded)['points'], expected)
        self.assertEqual(json.loads(encoded)['package_id'], package_id)

    def test_empty_receipt_preserves_evidence(self):
        key = self.register_sample()
        package_id = self.publish(key)
        self.db.close()
        receipt = inspect_window(self.packages, package_id, 29)
        self.assertEqual(receipt.points, ())
        self.assertEqual(json.loads(export_receipt(receipt)), {
            'version': 1, 'package_id': package_id, 'revision': ['A017', 'r1'],
            'window': [0, 3, 1, 4], 'threshold': 29, 'points': [],
        })

    def test_export_binding_across_distinct_windows(self):
        key = self.register_sample()
        first_id = self.publish(key, POINT)
        last = Window(0, 4, 1, 5)
        last_id = self.publish(key, last)
        self.assertNotEqual(first_id, last_id)
        self.db.close()
        result = [json.loads(export_receipt(inspect_window(self.packages, identifier, 28))) for identifier in (first_id, last_id)]
        self.assertEqual([item['package_id'] for item in result], [first_id, last_id])
        self.assertEqual([item['window'] for item in result], [[0, 3, 1, 4], [0, 4, 1, 5]])
        self.assertEqual([item['points'] for item in result], [[[0, 3, 28]], [[0, 4, 29]]])

    def test_threshold_requires_an_integer_count(self):
        key = self.register_sample()
        package_id = self.publish(key)
        for threshold in (True, 28.0, '28', None):
            with self.subTest(threshold=threshold), self.assertRaisesRegex(ValueError, 'integer sample count'):
                inspect_window(self.packages, package_id, threshold)
