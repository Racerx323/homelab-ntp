#!/usr/bin/python3
"""Offline redaction, read-only command scope and sealed node/master checks."""
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


def load(path):
    s=importlib.util.spec_from_file_location(path.stem,path)
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


r=load(ROOT/'scripts/run-munin-prerequisites.py')
r.h=load(ROOT/'scripts/run-production-inspection.py')
r.network=load(r.SOURCES['network-profile.py']) if r.SOURCES['network-profile.py'].exists() else types.SimpleNamespace(review=lambda spec:'Fixture network review '+json.dumps(spec,sort_keys=True))
r.readiness=load(r.SOURCES['network-readiness.py']) if r.SOURCES['network-readiness.py'].exists() else types.SimpleNamespace(review=lambda spec:'Fixture readiness review '+json.dumps(spec,sort_keys=True))


class MuninTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.profile=self.root/'profile.md';self.profile.write_text('Review draft, not deployed.\n')
        p=patch.dict(r.SOURCES,{'profile-review.md':self.profile,'package-qualification.md':self.profile,
                             'network-profile.py':self.profile,'network-profile-tests.py':self.profile,
                             **{key:self.profile for key in ('network-readiness.py','network-readiness-tests.py',
                                                           'network-readiness-review.md','network-ipam.yaml')}});p.start();self.addCleanup(p.stop)

    def test_contact_credentials_and_url_queries_are_not_exported(self):
        p=self.root/'munin.conf'
        p.write_text('[ntp.example]\n address 10.1.0.51\n contact.mail.command curl SECRET-PASSWORD\n contacts mail\n df.root.warning 92\n includedir /etc/munin/munin-conf.d\n')
        row=r.configuration(p);text=json.dumps(row)
        self.assertNotIn('SECRET-PASSWORD',text)
        self.assertIn('contact.mail.command',text)
        self.assertIn('10.1.0.51',text)
        self.assertIn('92',text)
        clean=r.safe_url_text('origin https://user:password@example.test/repo?token=SECRET#fragment')
        self.assertEqual(clean,'origin https://example.test/repo')

    def test_missing_indirect_and_oversized_config(self):
        self.assertTrue(r.configuration(self.root/'missing')['record']['missing'])
        p=self.root/'link';p.symlink_to('/missing/secret')
        self.assertTrue(r.configuration(p)['indirect'])
        p=self.root/'large';p.write_bytes(b'x'*65537)
        with self.assertRaisesRegex(ValueError,'size bound'):r.configuration(p)

    def test_config_include_does_not_expand_arbitrary_paths(self):
        root=self.root/'etc';root.mkdir();(root/'munin.conf').write_text('includedir /outside/scope\n')
        (root/'munin-conf.d').mkdir();(root/'munin-conf.d/nodes').write_text('[node.example]\naddress 192.0.2.1\n')
        result=r.master_configuration(root)
        self.assertEqual(len(result),2)
        self.assertTrue(all(str(root) in row['path'] for row in result))

    def collect(self,mode,code=0):
        boot=self.root/'boot';boot.write_text('boot\n')
        def path(*parts):
            p=Path(*parts)
            if str(p)=='/proc/sys/kernel/random/boot_id':return boot
            if str(p) in ('/var/lib/apt/lists','/usr/sbin/ip','/usr/bin/ip'):return self.root/'absent'
            return p
        calls=[]
        def cmd(argv,**kwargs):
            calls.append(argv)
            text='MainPID=814\n' if argv[:3]==['/usr/bin/systemctl','show','timeservice.service'] else ''
            return {'argv':argv,'returncode':code if '--simulate' in argv else 0,'stdout':text,'stderr':''}
        spec={'mode':mode,'operation_id':'fixture','boot_id':'boot','service_identity':{'MainPID':'814'}}
        with patch.object(r,'Path',side_effect=path),patch.object(r.os,'geteuid',return_value=0), \
             patch.object(r.socket,'gethostname',return_value='j2-svntp1' if mode=='node-dependencies' else 'J1-SVMF'), \
             patch.object(r.h,'bounded',side_effect=cmd),patch.object(r,'master_configuration',return_value=[]), \
             patch.object(r,'configuration',return_value={}),patch.object(r.h,'file_record',return_value={'missing':True}):
            result=r.collect(spec)
        return result,calls

    def test_node_dependency_commands_are_cached_and_simulated(self):
        result,calls=self.collect('node-dependencies')
        self.assertTrue(result['capture_complete'],result)
        self.assertFalse(result['dependencies_accepted'])
        apt=[a for a in calls if a[0]=='/usr/bin/apt-get']
        self.assertEqual(len(apt),1);self.assertIn('--simulate',apt[0]);self.assertIn('--no-install-recommends',apt[0])
        self.assertEqual(apt[0][-2:],['munin-node','munin-plugins-core'])
        self.assertTrue(all('Dir::Cache::pkgcache=' in a for a in calls if 'apt-' in a[0]))
        self.assertFalse(any('update' in a or 'download' in a or 'munin-run' in ' '.join(a) for a in calls))
        result,_=self.collect('node-dependencies',100)
        self.assertTrue(result['capture_complete']);self.assertEqual(result['commands']['simulation']['returncode'],100)

    def test_master_never_executes_plugins_limits_or_polling(self):
        result,calls=self.collect('master')
        self.assertTrue(result['capture_complete'],result)
        self.assertFalse(result['polling_accepted']);self.assertFalse(result['delivery_verified'])
        self.assertTrue(all(a[0] in ('/usr/bin/dpkg','/usr/bin/dpkg-query','/usr/bin/systemctl') for a in calls))

    def test_wrong_root_runs_no_command(self):
        with patch.object(r.os,'geteuid',return_value=1000),patch.object(r.h,'bounded') as command:
            result=r.collect({'operation_id':'bad'})
        self.assertFalse(result['capture_complete']);command.assert_not_called()

    def baseline(self,mode):
        d=self.root/('baseline-'+mode);d.mkdir(mode=0o700)
        spec={'operation_id':'baseline','boot_id':'boot','service_identity':{'MainPID':'814'},'monitoring':True}
        if mode!='node-dependencies':spec.update(endpoint='10.1.3.83',user='pi',host_key_alias='svmf.local.theama.co',mode='master')
        if mode=='master-profile-save':spec.update(mode='master-persistence',hostname='J1-SVMF')
        if mode=='master-network-readiness':spec.update(mode='master-profile-save',hostname='J1-SVMF')
        if mode=='master-recovery-readiness':spec.update(mode='master-network-readiness',hostname='J1-SVMF')
        with tarfile.open(d/'inspection.tar','w') as t:
            for n,raw in {'spec.json':r.h.encoded(spec),'known_hosts':b'fixture key\n'}.items():
                m=tarfile.TarInfo(n);m.size=len(raw);t.addfile(m,io.BytesIO(raw))
        (d/'result.json').write_bytes(r.h.encoded({'capture_complete':True,'returncode':0,'bundle_sha256':r.h.sha((d/'inspection.tar').read_bytes())}))
        (d/'stdout.txt').write_bytes(r.h.encoded({'capture_complete':True,'operation_id':'baseline','spec_sha256':r.h.sha(r.h.encoded(spec)),'hostname':'J1-SVMF','boot_after':'boot','selected_profile_filename':'/run/NetworkManager/system-connections/Wired connection 1.nmconnection','persisted':True,'running_network_unchanged':True,'target_mutation':False}))
        for p in d.iterdir():p.chmod(0o600)
        return d

    def test_both_target_seals_review_tampering_and_single_use(self):
        for mode in r.TARGETS:
            d=self.root/('review-'+mode)
            result=r.seal(types.SimpleNamespace(mode=mode,baseline=self.baseline(mode),output=d))
            spec,_=r.prepare(d,result['sha256'])
            self.assertEqual(spec['user'],r.TARGETS[mode][1])
            (d/'execution.json').write_text('{}')
            with patch.object(r.h,'bounded') as cmd:
                with self.assertRaises(FileExistsError):r.execute(types.SimpleNamespace(directory=d,sha256=result['sha256']))
                cmd.assert_not_called()
            (d/'review.md').write_text('changed')
            with self.assertRaisesRegex(ValueError,'approval input drift'):r.prepare(d,result['sha256'])

    def test_network_readiness_requires_accepted_profile_save(self):
        d=self.baseline('master-network-readiness')
        capture=json.loads((d/'stdout.txt').read_text());capture['persisted']=False
        (d/'stdout.txt').write_bytes(r.h.encoded(capture))
        with self.assertRaisesRegex(ValueError,'accepted persistent profile-save'):
            r.seal(types.SimpleNamespace(mode='master-network-readiness',baseline=d,output=self.root/'bad'))

    def test_cron_parser_omits_body_and_retains_actual_schedule(self):
        rows=r.cron_structure(b'MAILTO=SECRET\n*/5 * * * * munin test -x /usr/bin/munin-cron && /usr/bin/munin-cron --secret SECRET\n')
        self.assertEqual(rows[0]['schedule'],['*/5','*','*','*','*'])
        self.assertEqual(rows[0]['user'],'munin')
        self.assertEqual(rows[0]['recognized_paths'],['/usr/bin/munin-cron'])
        self.assertNotIn('SECRET',json.dumps(rows))

    def test_effective_nm_policy_omits_credentials_and_stable_id_literals(self):
        raw='[main]\npassword=SECRET\n[connection-lan]\nmatch-device=interface-name:eth0\nipv6.addr-gen-mode=stable-privacy\nconnection.stable-id=SECRET-${BOOT}\nother=SECRET\n'
        rows=r.nm_policy(raw);text=json.dumps(rows)
        self.assertIn('stable-privacy',text);self.assertNotIn('SECRET',text)
        self.assertTrue(rows[-1]['features']['boot_dependent'])
        self.assertTrue(r.stable_id_features('--')['unset'])
        self.assertTrue(r.stable_id_features('${RANDOM}')['random_dependent'])

    def test_saved_profile_exports_only_selected_nonsecret_fields(self):
        import base64
        raw=b'[connection]\nuuid=fixture-uuid\ntype=ethernet\ninterface-name=eth0\nstable-id=SECRET-${BOOT}\n[ipv6]\nmethod=auto\naddr-gen-mode=3\n[wifi-security]\npsk=SECRET\n'
        row={'uid':0,'mode':0o600,'base64':base64.b64encode(raw).decode(),'sha256':'secret-covering-hash'}
        with patch.object(r.h,'file_record',side_effect=lambda *a,**k:dict(row)):
            result=r.saved_profile('/etc/NetworkManager/system-connections/fixture.nmconnection','fixture-uuid')
            self.assertNotIn('SECRET',json.dumps(result));self.assertNotIn('secret-covering-hash',json.dumps(result))
            self.assertTrue(result['fields']['stable_id']['boot_dependent'])
            self.assertEqual(r.saved_profile('/etc/NetworkManager/system-connections/legacy-profile','fixture-uuid')['fields']['connection']['uuid'],'fixture-uuid')
            with self.assertRaisesRegex(ValueError,'UUID mismatch'):r.saved_profile('/etc/NetworkManager/system-connections/fixture.nmconnection','other')
            with self.assertRaisesRegex(ValueError,'persistent system'):r.saved_profile('/run/fixture.nmconnection','fixture-uuid')
            row['mode']=0o644
            with self.assertRaisesRegex(ValueError,'root-private'):r.saved_profile('/etc/NetworkManager/system-connections/fixture.nmconnection','fixture-uuid')

    def test_log_summary_is_bounded_and_never_exports_lines(self):
        p=self.root/'log'
        p.write_text('x'*70000+'\n[2026/10/20-10:00:00] Starting munin-update SECRET\n[2026/10/20-10:00:01] Munin-update finished ERROR SECRET\n')
        row=r.activity_summary(p)
        self.assertLessEqual(row['tail_bytes'],65536)
        self.assertEqual(row['start_markers'],1);self.assertEqual(row['finish_markers'],1)
        self.assertEqual(row['error_marker_count'],1)
        self.assertNotIn('SECRET',json.dumps(row))
        p=self.root/'indirect';p.symlink_to('/missing/secret')
        self.assertTrue(r.activity_summary(p)['indirect'])

    def test_master_qualification_uses_only_local_route_queries(self):
        boot=self.root/'boot';boot.write_text('boot\n')
        ip=self.root/'ip';ip.touch()
        def path(*parts):
            p=Path(*parts)
            if str(p)=='/proc/sys/kernel/random/boot_id':return boot
            if str(p)=='/usr/sbin/ip':return ip
            if str(p).startswith(('/proc/sys/net/','/usr/bin/nmcli','/usr/sbin/nmcli')):return self.root/'absent'
            return p
        calls=[]
        def cmd(argv,**kwargs):
            calls.append(argv)
            return {'argv':argv,'returncode':0,'stdout':'[]','stderr':''}
        import base64
        spec={'operation_id':'qualify','mode':'master-qualification','hostname':'J1-SVMF','boot_id':'boot'}
        with patch.object(r,'Path',side_effect=path),patch.object(r.os,'geteuid',return_value=0), \
             patch.object(r.socket,'gethostname',return_value='J1-SVMF'),patch.object(r.h,'bounded',side_effect=cmd), \
             patch.object(r.h,'file_record',return_value={'base64':base64.b64encode(b'*/5 * * * * munin /usr/bin/munin-cron').decode()}), \
             patch.object(r,'scheduler_sources',return_value=[]),patch.object(r,'activity_summary',return_value={}), \
             patch.object(r,'master_configuration',return_value=[]):
            result=r.collect(spec)
        self.assertTrue(result['capture_complete'],result)
        routes=[a for a in calls if 'route' in a]
        self.assertEqual(len(routes),2)
        self.assertTrue(all('get' in a for a in routes))
        self.assertTrue(all(a[0] in ('/usr/sbin/ip','/usr/bin/systemctl') for a in calls))

    def test_incomplete_baseline_rejected(self):
        b=self.baseline('master');(b/'result.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'complete bound inspection'):
            r.seal(types.SimpleNamespace(mode='master',baseline=b,output=self.root/'bad'))

    def test_identity_collection_discards_raw_nm_config_and_never_reads_secrets(self):
        boot=self.root/'boot';boot.write_text('boot\n')
        executable=self.root/'tool';executable.touch()
        def path(*parts):
            p=Path(*parts)
            if str(p)=='/proc/sys/kernel/random/boot_id':return boot
            if str(p) in ('/usr/sbin/ip','/usr/bin/nmcli','/usr/sbin/NetworkManager'):return executable
            return self.root/'absent'
        calls=[]
        def cmd(argv,**kwargs):
            calls.append(argv);text=''
            if '--active' in argv:text='2cad90ef-210e-329a-bc55-9e23fa8160dd:eth0\n'
            if '--print-config' in argv:text='[connection]\nipv6.addr-gen-mode=stable-privacy\npassword=SECRET\n'
            if 'connection.stable-id' in argv:text='SECRET-${RANDOM}\n'
            return {'argv':argv,'returncode':0,'stdout':text,'stderr':'SECRET'}
        spec={'mode':'master-identity','operation_id':'identity','hostname':'J1-SVMF','boot_id':'boot'}
        with patch.object(r,'Path',side_effect=path),patch.object(r.os,'geteuid',return_value=0), \
             patch.object(r.socket,'gethostname',return_value='J1-SVMF'),patch.object(r.h,'bounded',side_effect=cmd):
            result=r.collect(spec)
        self.assertTrue(result['capture_complete'],result)
        # Ordinary command stderr is preserved; raw policy/stable-id stderr is not.
        self.assertNotIn('SECRET',json.dumps(result['stable_id']))
        self.assertNotIn('SECRET',json.dumps(result['effective_nm_policy']))
        self.assertTrue(result['stable_id']['random_dependent'])
        self.assertNotIn('cron',result);self.assertFalse(result['persistence_accepted'])
        self.assertTrue(all(a[0] in ('/usr/sbin/ip','/usr/bin/nmcli','/usr/sbin/NetworkManager','/usr/bin/systemctl') for a in calls))


if __name__=='__main__':unittest.main()
