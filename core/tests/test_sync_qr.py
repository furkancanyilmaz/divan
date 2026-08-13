import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sync_qr import MAX_PAIRING_TEXT_BYTES, pairing_qr_matrix


class SyncQrTests(unittest.TestCase):
    def test_pairing_payload_becomes_bounded_square_matrix(self):
        matrix = pairing_qr_matrix(
            "divan-sync://pair?v=1&host=192.168.1.8&port=43123")

        self.assertGreaterEqual(matrix["size"], 21)
        self.assertEqual(matrix["size"] % 2, 1)
        self.assertEqual(len(matrix["rows"]), matrix["size"])
        self.assertTrue(all(
            len(row) == matrix["size"] and set(row) <= {"0", "1"}
            for row in matrix["rows"]))

    def test_empty_and_oversized_payloads_are_rejected(self):
        with self.assertRaises(ValueError):
            pairing_qr_matrix("")
        with self.assertRaises(ValueError):
            pairing_qr_matrix("ü" * (MAX_PAIRING_TEXT_BYTES + 1))


if __name__ == "__main__":
    unittest.main()
