#!/usr/bin/python3
"""Exercise actual pairing acceptance through delayed receiver acquisition."""
import importlib.util
import json
import os
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('pairing',ROOT/'scripts/gpsd-pairing.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)


def samples(unit='NTP2', leap=0):
    rows=[{'class':'WATCH','pps':True}]; shm=[]
    for kind,device,name in [('TOFF','/dev/serial0','NTP0'),('PPS','/dev/pps0',unit)]:
        for sec in range(5):
            rows.append({'class':kind,'device':device,'shm':name,'clock_sec':100+sec,
                         'clock_nsec':0,'real_sec':100+sec,'real_nsec':0})
            shm.append(f'sample {name} 100 {100+sec}.000000000 {100+sec}.000000000 {leap} -20')
    return ('\n'.join(map(json.dumps,rows))+'\n','\n'.join(shm)+'\n')


class Acquisition(unittest.TestCase):
    def exercise(self, ready_window=1, wait=True, stop_at=None, raw=None, dead=False):
        clock=[0.0]; children=[]; updates=[];gpsd=Mock();gpsd.poll.return_value=None
        valid=raw or samples()
        pending=(json.dumps({'class':'WATCH','pps':True})+'\n','')
        def launch(argv,stdout,**kwargs):
            index=len(children);window=index//2+1
            data=valid if window>=ready_window else pending
            stdout.write(data[index%2].encode());stdout.flush()
            child=Mock();child.poll.return_value=1 if dead else None;children.append(child)
            return child
        def sleep(seconds):clock[0]+=seconds
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(p.socket,'create_connection'), \
                patch.object(p.subprocess,'Popen',side_effect=launch), \
                patch.object(p.time,'monotonic',side_effect=lambda:clock[0]), \
                patch.object(p.time,'sleep',side_effect=sleep):
            try:
                result=p.startup(gpsd,lambda:stop_at is not None and clock[0]>=stop_at,
                                 {'TOFF':'NTP0','PPS':'NTP2'},Path(directory),
                                 acquisition_wait=wait,progress=updates.append)
                self.assertFalse(list(Path(directory).iterdir()))
                return result,updates,clock[0]
            finally:
                for child in children:
                    child.wait.assert_called_once()
                    if not dead:child.terminate.assert_called_once()

    def test_warm_receiver_passes_without_wait(self):
        result,updates,elapsed=self.exercise()
        self.assertTrue(result['observed']);self.assertEqual(result['windows'],1)
        self.assertEqual(elapsed,0)

    def test_cold_receiver_after_12_5_minutes_uses_actual_matching(self):
        result,updates,elapsed=self.exercise(ready_window=27)
        self.assertTrue(result['observed']);self.assertEqual(elapsed,780)
        self.assertEqual(len(updates),27)
        self.assertTrue(all(x['state']=='acquiring' for x in updates))

    def test_acquisition_over_30_minutes_is_not_a_shutdown_deadline(self):
        result,updates,elapsed=self.exercise(ready_window=62)
        self.assertTrue(result['observed']);self.assertEqual(elapsed,1830)
        self.assertEqual(result['sources']['PPS']['matching_samples'],5)

    def test_legacy_bounded_gate_remains_bounded(self):
        with self.assertRaisesRegex(ValueError,'30-second'):
            self.exercise(ready_window=3,wait=False)

    def test_operator_stop_reaps_readers(self):
        with self.assertRaisesRegex(ValueError,'stopped'):
            self.exercise(ready_window=100,stop_at=45)

    def test_wrong_unit_and_dead_monitor_are_faults_not_wait_states(self):
        with self.assertRaisesRegex(ValueError,'assignments'):
            self.exercise(raw=samples(unit='NTP3'))
        with self.assertRaisesRegex(ValueError,'stopped'):
            self.exercise(dead=True)

    def test_unqualified_leap_samples_cannot_pass(self):
        with self.assertRaisesRegex(ValueError,'stopped'):
            self.exercise(raw=samples(leap=3),stop_at=45)

    def test_malformed_and_unacknowledged_streams_fail(self):
        with self.assertRaises(ValueError):self.exercise(raw=('not json\n',''))
        with self.assertRaisesRegex(ValueError,'acknowledge'):
            self.exercise(raw=(json.dumps({'class':'VERSION'})+'\n',''))

    def test_production_policy_explicitly_selects_wait(self):
        gate=json.loads((ROOT/'configs/production-startup-gate.json').read_text())
        self.assertEqual(gate['acquisition_policy'],'wait')
        self.assertEqual(gate['timeout_seconds'],30)
        self.assertEqual(gate['matching_samples_per_source'],5)


class ProgressRecord(unittest.TestCase):
    def test_real_atomic_progress_and_terminal_records_include_current_invocation(self):
        spec=importlib.util.spec_from_file_location('service',ROOT/'scripts/timeservice.py')
        service=importlib.util.module_from_spec(spec);spec.loader.exec_module(service)
        for fail in (False,True):
            with self.subTest(fail=fail),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);root.chmod(0o700);seen=[]
                original_lstat=Path.lstat
                def lstat(path,*args,**kwargs):
                    if path==root:return SimpleNamespace(st_mode=0o40700,st_uid=0)
                    return original_lstat(path,*args,**kwargs)
                def startup(gpsd,stopping,expected,directory,**options):
                    self.assertTrue(options['acquisition_wait'])
                    options['progress']({'observed':False,'windows':1})
                    seen.append(json.loads((root/'gate.json').read_text()))
                    if fail:raise ValueError('fixture fault')
                    return {'observed':True}
                helper=SimpleNamespace(startup=startup)
                loader=SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module:None))
                with patch.object(service,'Path',side_effect=lambda value:root if str(value)=='/run/ntpsec-startup' else Path(value)), \
                        patch.object(Path,'lstat',lstat), \
                        patch.object(service.importlib.util,'spec_from_file_location',return_value=loader), \
                        patch.object(service.importlib.util,'module_from_spec',return_value=helper):
                    if fail:
                        with self.assertRaisesRegex(ValueError,'fixture fault'):
                            service.check_startup(SimpleNamespace(pid=os.getpid()),lambda:False,{'units':{},'acquisition_policy':'wait'})
                    else:service.check_startup(SimpleNamespace(pid=os.getpid()),lambda:False,{'units':{},'acquisition_policy':'wait'})
                final=json.loads((root/'gate.json').read_text())
                self.assertEqual(seen[0]['state'],'acquiring')
                self.assertEqual(final['state'],'failed' if fail else 'passed')
                self.assertEqual(final['boot_id'],Path('/proc/sys/kernel/random/boot_id').read_text().strip())
                self.assertEqual(final['gpsd_pid'],os.getpid())
                self.assertTrue(final['gpsd_start_ticks'].isdigit())
                self.assertGreaterEqual(final['updated_monotonic'],seen[0]['updated_monotonic'])
                self.assertEqual((root/'gate.json').stat().st_mode&0o777,0o600)
                self.assertFalse((root/'gate.json.new').exists())


if __name__=='__main__':unittest.main()
