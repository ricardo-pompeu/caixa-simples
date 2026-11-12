from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'instalar-bipe.sh'
USB = 'usb://Printer/POS-80?serial=OUTRO-COMPUTADOR'
MODEL = 'drv:///cupsfilters.drv/textonly.ppd'


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.log = self.folder / 'calls'
        self.env = {**os.environ, 'PATH': f'{self.folder}:/usr/bin:/bin', 'FAKE_LOG': str(self.log),
                    'FAKE_DEVICES': f'direct {USB}', 'FAKE_QUEUES': '', 'FAKE_MODEL': MODEL}
        program = f'#!{sys.executable}\n' + '''
import os, sys
from pathlib import Path
cmd, *args = sys.argv
name = Path(cmd).name
if name == 'id':
    print('1000')
elif name == 'lpinfo':
    print(os.environ['FAKE_DEVICES'] if '-v' in args else os.environ['FAKE_MODEL'] + ' Generic Text-Only Printer')
elif name == 'lpstat':
    if '-v' in args:
        print(os.environ['FAKE_QUEUES'])
elif name == 'lpoptions':
    print(os.environ.get('FAKE_OPTIONS', "printer-make-and-model='Generic Text-Only Printer' printer-state=3"))
elif name == 'sudo':
    with open(os.environ['FAKE_LOG'], 'a') as log:
        print(*args, file=log)
'''
        for name in ['id', 'lpinfo', 'lpstat', 'lpoptions', 'sudo', 'lpadmin']:
            p = self.folder / name
            p.write_text(program)
            p.chmod(0o755)

    def run_installer(self, mode):
        return subprocess.run(['sh', str(SCRIPT), mode], env=self.env, capture_output=True, text=True)

    def test_fresh_queue_uses_connected_usb_and_text_driver(self):
        result = self.run_installer('--so-impressora')
        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.log.read_text()
        self.assertIn(f'-p POS-80 -v {USB} -m {MODEL}', call)
        self.assertIn('Pagination=False', call)
        self.assertIn('SendFF=False', call)
        self.assertIn('printer-is-shared=false', call)

    def test_same_working_queue_is_unchanged(self):
        self.env['FAKE_QUEUES'] = f'device for POS-80: {USB}'
        result = self.run_installer('--so-impressora')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Nenhuma alteração', result.stdout)
        self.assertFalse(self.log.exists())

    def test_refuses_to_overwrite_queue_or_guess_device(self):
        cases = [
            (f'device for POS-80: {USB}2', f'direct {USB}', 'outro dispositivo'),
            ('', f'direct {USB}\ndirect {USB}2', 'Mais de uma'),
            ('', 'direct usb://Generic/Other', 'não foi encontrada'),
        ]
        for queues, devices, message in cases:
            with self.subTest(message=message):
                self.env.update(FAKE_QUEUES=queues, FAKE_DEVICES=devices)
                result = self.run_installer('--so-impressora')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertFalse(self.log.exists())

    def test_check_mode_never_creates_queue(self):
        result = self.run_installer('--verificar')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ainda não há uma fila', result.stderr)
        self.assertFalse(self.log.exists())
