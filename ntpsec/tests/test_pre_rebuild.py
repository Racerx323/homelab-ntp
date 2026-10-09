"""Offline preflight regression tests: no sockets or remote commands executed."""
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/pre-rebuild-health.sh'
SOURCE = SCRIPT.read_text().split("<<'PYTHON'\n", 1)[1].rsplit('\nPYTHON', 1)[0]
ENGINE = {'__name__': 'offline_test'}
exec(compile(SOURCE, str(SCRIPT), 'exec'), ENGINE)


class HealthTests(unittest.TestCase):
    def test_system_good(self):
        self.assertEqual(ENGINE['system_health'](
            'leap=00, stratum=1, peer=7, offset=-0.123, rootdisp=1.2')['peer'], '7')

    def test_system_rejections(self):
        good = 'leap=00, stratum=1, peer=7, offset=0.1, rootdisp=1.2'
        for bad in ('', '***Request timed out', good + ', peer=8',
                    good.replace('leap=00', 'leap=11'), good.replace('stratum=1', 'stratum=2'),
                    good.replace('peer=7', 'peer=0'), good.replace('offset=0.1', 'offset=nan'),
                    good.replace(', rootdisp=1.2', ''), good + '\n***Permission denied'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ENGINE['system_health'](bad)

    def test_wrong_primary_prevents_commands(self):
        with patch.object(ENGINE['socket'], 'gethostname', return_value='other'), \
                patch.object(ENGINE['subprocess'], 'run') as run:
            with self.assertRaises(ValueError):
                ENGINE['primary']()
            run.assert_not_called()

    def test_response_rejections(self):
        request = bytes(40) + struct.pack('!II', 123, 456)
        valid = bytearray(48)
        valid[0], valid[1] = 0x24, 1
        valid[24:32] = request[40:48]
        valid[32:40] = valid[40:48] = bytes([1]) * 8
        self.assertEqual(ENGINE['response_health'](valid, request)['stratum'], 1)
        for index, value in ((0, 0xe4), (0, 0x23), (1, 0), (1, 16), (24, 0)):
            bad = bytearray(valid)
            bad[index] = value if bad[index] != value else 255
            with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                ENGINE['response_health'](bad, request)
        for bad in (valid[:47], bytes(513), valid[:32] + bytes(16)):
            with self.assertRaises(ValueError):
                ENGINE['response_health'](bad, request)

    def test_client_fixed_scope_and_no_retry(self):
        sockets = []
        class Fake:
            def __init__(self, *args):
                self.args = args
                self.sent = []
                sockets.append(self)
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def settimeout(self, seconds): self.timeout = seconds
            def connect(self, target): self.target = target
            def getsockname(self): return ('10.1.0.20', 54321)
            def send(self, packet): self.sent.append(packet); return len(packet)
            def recv(self, size):
                packet = bytearray(48)
                packet[0], packet[1] = 0x24, 1
                packet[24:32] = self.sent[0][40:48]
                packet[32:48] = bytes([1]) * 16
                return packet
        result = ENGINE['client'](Fake)
        self.assertTrue(result['checks']['direct_ipv4_responses'])
        self.assertEqual([s.target for s in sockets], [('10.1.0.50', 123), ('10.1.0.51', 123)])
        self.assertTrue(all(len(s.sent) == 1 and s.timeout == 5 for s in sockets))
        class Failing(Fake):
            def recv(self, size): raise TimeoutError('fixture timeout')
        result = ENGINE['client'](Failing)
        self.assertFalse(result['checks']['direct_ipv4_responses'])
        self.assertTrue(all('fixture timeout' in r['error'] for r in result['records']))

    def test_primary_does_not_accept_errors_or_config_change(self):
        good = {'rc': 0, 'stderr': '', 'stdout':
                'leap=00, stratum=1, peer=7, offset=0.1, rootdisp=1.2'}
        peer = {'rc': 0, 'stderr': '', 'stdout': 'oSHM(1) .PPS. 0 l 1 16 377 0 0 0'}
        ordinary = {'rc': 0, 'stderr': '', 'stdout': 'fixture'}
        with patch.object(ENGINE['socket'], 'gethostname', return_value='j1-svntp'):
            for fail in ('none', 'stderr', 'changed', 'peererror'):
                records = [dict(good), dict(peer), dict(ordinary), dict(ordinary)]
                if fail == 'stderr': records[0]['stderr'] = 'error'
                if fail == 'peererror': records[1]['stdout'] += '\n***Request timed out'
                hashes = [{'sha256': 'same'}, {'sha256': 'other' if fail == 'changed' else 'same'}]
                with patch.dict(ENGINE, trusted_ntpq=lambda: '/fixture/ntpq',
                                run=lambda args: records.pop(0), file_hash=lambda: hashes.pop(0)):
                    result = ENGINE['primary']()
                    self.assertEqual(all(result['checks'].values()), fail == 'none')

    def test_invalid_invocation_no_commands(self):
        with patch.object(ENGINE['sys'], 'argv', ['probe', '--unapproved']), \
                patch.object(ENGINE['subprocess'], 'run') as run:
            self.assertEqual(ENGINE['main'](), 64)
            run.assert_not_called()

    def test_command_failures_preserved(self):
        with patch.object(ENGINE['subprocess'], 'run', side_effect=FileNotFoundError('fixture')):
            self.assertEqual(ENGINE['run'](['/missing'])['rc'], 127)
        timeout = ENGINE['subprocess'].TimeoutExpired(['fixture'], 12, output=b'partial', stderr=b'error')
        with patch.object(ENGINE['subprocess'], 'run', side_effect=timeout):
            record = ENGINE['run'](['fixture'])
            self.assertEqual((record['rc'], record['stdout'], record['stderr']), (124, 'partial', 'error'))


if __name__ == '__main__':
    unittest.main()
