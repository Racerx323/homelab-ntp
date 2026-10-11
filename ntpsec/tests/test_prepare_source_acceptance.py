#!/usr/bin/python3
"""Offline rendering and origin authority checks for source acceptance preparation."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
s = importlib.util.spec_from_file_location('preparer', ROOT / 'scripts/prepare-source-acceptance.py')
p = importlib.util.module_from_spec(s)
s.loader.exec_module(p)


class Preparation(unittest.TestCase):
    def test_wrong_origin_rejected_before_reading_or_loading_external_inputs(self):
        with self.assertRaisesRegex(ValueError, 'only the retained v5'):
            p.prepare(SimpleNamespace(origin_sha256='a'*64, origin=Path('/nonexistent')))

    def test_rendered_adapter_executes_only_continuation_and_exposes_readback(self):
        worker = b'value=42\ndef evidence(): return {"fixture":value}\n'
        continuation = b'def continue_entry(s,f,e,m,w): return {"mode":m,"value":w.value}\n'
        ns = {'__name__': 'sealed_fixture'}
        exec(compile(p.render(worker, continuation), 'rendered', 'exec'), ns)
        self.assertEqual(ns['entry']({}, {}, 1, 'accept'), {'mode': 'accept', 'value': 42})
        self.assertEqual(ns['evidence'](), {'fixture': 42})


if __name__ == '__main__':
    unittest.main()
