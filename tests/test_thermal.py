import unittest
from bipe.thermal import Queue, select_queue, text_queue, thermal_payload, thermal_lines


class ThermalTest(unittest.TestCase):
    def test_real_pos80_queue_profile(self):
        profile = {'printer-make-and-model': 'Generic Text-Only Printer', 'media': 'A4',
                   'printer-state': '3', 'printer-is-accepting-jobs': 'true'}
        queue = text_queue('POS-80', profile)
        self.assertEqual(queue.width, 80)
        self.assertTrue(queue.ready)
        self.assertEqual(select_queue([queue], 'auto'), queue)
        self.assertIsNone(select_queue([queue], 'system'))
        self.assertIsNone(text_queue('Office', profile))
        self.assertIsNone(text_queue('POS-80', {'printer-make-and-model': 'Driver PDF'}))
        other = text_queue('POS-58', {**profile, 'printer-state': '5'})
        self.assertEqual(other.width, 58)
        self.assertFalse(other.ready)
        with self.assertRaisesRegex(ValueError, 'mais de uma'):
            select_queue([queue, other], 'auto')
        with self.assertRaisesRegex(ValueError, 'não está disponível'):
            select_queue([other], 'POS-80')
        self.assertEqual(select_queue([queue, other], 'POS-58'), other)

    def test_layout_and_cutter_only_for_recognized_pos80(self):
        profile = {'printer-make-and-model': 'Generic Text-Only Printer',
                   'device-uri': 'usb://Printer/POS-80?serial=sample'}
        pos80 = text_queue('POS-80', profile)
        self.assertTrue(pos80.cutter)
        self.assertFalse(text_queue('POS-80', {**profile, 'device-uri': 'ipp://other/print'}).cutter)
        sale = {'id': 10, 'created': '2026-11-12T10:24:00-03:00', 'store': 'Mercantil', 'footer': 'Volte sempre!',
                'total': 2000, 'payment': 'PIX', 'received': None, 'change_value': 0,
                'items': [{'name': 'Café' + ' X' * 40 + '\x1b\x1d', 'price': 500, 'quantity': 4}]}
        for width, columns in [(58, 32), (80, 42)]:
            lines = thermal_lines(sale, columns)
            subtotal, total = [line for line in lines if line.endswith('R$ 20,00')]
            self.assertEqual(len(subtotal), columns)
            self.assertEqual(len(total), columns)
            self.assertTrue(all(len(line) <= columns for line in lines))
            self.assertIn('4x Cafe', '\n'.join(lines))
            result, fmt = thermal_payload(sale, Queue('térmica', 'text-only', width, True))
            self.assertEqual(fmt, 'text/plain')
            self.assertTrue(all(c == 10 or 32 <= c < 127 for c in result))
        result, fmt = thermal_payload(sale, pos80)
        self.assertEqual(fmt, 'application/vnd.cups-raw')
        self.assertTrue(result.startswith(b'\x1b@\x1b3\x18'))
        self.assertTrue(result.endswith(b'Volte sempre!\n\x1dVB\x30'))
        self.assertEqual(result.count(b'\x1d'), 1)
        self.assertEqual(thermal_payload(sale, pos80, False)[1], 'text/plain')
