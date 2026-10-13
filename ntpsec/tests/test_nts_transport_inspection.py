#!/usr/bin/python3
"""Offline controller boundaries, account-context probes and sealed node capture."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]


def load(path):
    s=importlib.util.spec_from_file_location(path.stem.replace('-','_'),path)
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


m=load(ROOT/'scripts/run-nts-transport-inspection.py')
n=load(ROOT/'scripts/inspect-nts-network.py')
b=load(ROOT/'tests/test_cutover_inspection.py')
R=json.loads((ROOT/'configs/nts-transport-inspection.json').read_bytes())


def fixture():
    spec,old=b.fixture();d=m.base()
    # CI has only this repository. The real sealer still requires and hashes
    # the network owner's access reference; the offline fixture supplies prose.
    files={name:(b'# Synthetic network-owner access reference\n' if name=='network-access.md' else (ROOT/path).read_bytes())
           for name,path in m.PATHS.items()}
    files.update({name:old[name] for name in d.EXTRA})
    spec['members']={name:m.sha(raw) for name,raw in files.items()}
    files['spec.json']=m.encoded(spec);files['review.md']=m.review(spec).encode()
    files['manifest.json']=m.encoded({name:m.sha(raw) for name,raw in files.items()})
    return spec,files


def addresses():
    return [{'hostname':h,'family':f,'address':'93.184.216.34' if f==4 else '2606:4700:f1::1'} for h in R['upstreams'] for f in (4,6)]


class BindingTests(unittest.TestCase):
    def test_fixture_needs_no_sibling_checkout(self):
        read=Path.read_bytes
        def local_only(path):
            if 'homelab-network' in path.parts:raise AssertionError('unexpected sibling dependency')
            return read(path)
        with patch.object(Path,'read_bytes',local_only):
            spec,files=fixture();m.base().validate(spec,files)

    def test_archive_and_remote_payloads(self):
        spec,files=fixture();d=m.base();d.validate(spec,files)
        c=d.load(ROOT/'scripts/run-service-cutover.py')
        for mode in ('start','readback','cleanup'):compile(c.payload(spec,files,mode),mode,'exec')
        with tempfile.TemporaryDirectory() as tmp:
            import io,tarfile
            raw=io.BytesIO()
            with tarfile.open(fileobj=raw,mode='w') as archive:
                for name,data in files.items():
                    item=tarfile.TarInfo(name);item.size=len(data);archive.addfile(item,io.BytesIO(data))
            self.assertEqual(c.unpack(raw.getvalue()),files)

    def test_rebound_scope_change_rejected(self):
        for key,value in [('port',123),('maximum_connections',24),('controller','elsewhere.example'),('ntp_uid',0)]:
            spec,files=fixture();r=dict(R,**{key:value});files['recipe.json']=m.encoded(r)
            spec['members']['recipe.json']=m.sha(files['recipe.json'])
            with self.subTest(key=key),self.assertRaises(ValueError):m.base().validate(spec,files)

    def test_controller_receipt_required_before_target_start(self):
        spec,files=fixture();d=m.base();d.prepare=Mock(return_value=(spec,files));d.execute=Mock()
        with tempfile.TemporaryDirectory() as tmp,patch.object(m,'base',return_value=d):
            args=SimpleNamespace(bundle=Path(tmp)/'bundle.tar',sha256='a'*64,mode='start')
            with self.assertRaises(FileNotFoundError):m.execute(args)
            d.execute.assert_not_called()


class ProbeTests(unittest.TestCase):
    def test_public_destinations_only(self):
        for address in ('127.0.0.1','10.1.0.1','::1','fd00::1','169.254.169.254','ff02::1'):
            with self.subTest(address=address),self.assertRaises(ValueError):n.public_address(address)

    def test_exact_endpoint_slots(self):
        rows=addresses();rows[0]=rows[1]
        with self.assertRaises(ValueError):n.probes(R,rows,'root')

    def test_probe_bound_and_account_drop(self):
        connection=Mock();connection.__enter__=Mock(return_value=connection);connection.__exit__=Mock()
        connection.getsockname.return_value=('192.0.2.1',45000)
        with patch.object(n.socket,'socket',return_value=connection) as create,patch.object(n.os,'setgroups') as groups, \
             patch.object(n.os,'setgid') as gid,patch.object(n.os,'setuid') as uid, \
             patch.object(n.os,'geteuid',return_value=999),patch.object(n.os,'getegid',return_value=985):
            result=n.probes(R,addresses(),'ntp')
        self.assertEqual(create.call_count,6);self.assertTrue(all(x['connected'] for x in result))
        groups.assert_called_once_with([]);gid.assert_called_once_with(985);uid.assert_called_once_with(999)
        self.assertTrue(all(call.args[0][1]==4460 for call in connection.connect.call_args_list))
        self.assertEqual(connection.settimeout.call_args.args,(2,))

    def test_refusal_is_observation_not_retry(self):
        connection=Mock();connection.__enter__=Mock(return_value=connection);connection.__exit__=Mock()
        connection.connect.side_effect=ConnectionRefusedError(111,'refused');connection.getsockname.return_value=('::',0)
        with patch.object(n.socket,'socket',return_value=connection),patch.object(n.os,'geteuid',return_value=0):
            result=n.probes(R,addresses(),'root')
        self.assertEqual(connection.connect.call_count,6)
        self.assertTrue(all(x['connected'] is False and x['errno']==111 for x in result))

    def test_dns_missing_family_is_retained(self):
        def lookup(host,port,family,kind):
            if family==socket.AF_INET6:raise socket.gaierror('unavailable')
            return [(family,kind,0,'',('93.184.216.34',port))]
        with patch.object(n.socket,'getaddrinfo',side_effect=lookup):rows=n.resolve(R)
        self.assertEqual(len(rows),6);self.assertEqual(sum('error' in x for x in rows),3)


class ControllerTests(unittest.TestCase):
    def test_redacts_credentials_and_values(self):
        result=n.redact({'password':'hidden','nested':['value-private-key'],'X-API-KEY':'private-key','private-key':'echo'},'private-key')
        self.assertNotIn('private-key',json.dumps(result));self.assertNotIn('hidden',json.dumps(result))

    def test_grouped_ordering_covers_user_rules_and_preserves_system_rules(self):
        policies=[{'id':'a','metadata':{'origin':'USER_DEFINED'}},{'id':'b','metadata':{'origin':'SYSTEM_DEFINED'}}]
        n.validate_ordering({'orderedFirewallPolicyIds':{'beforeSystemDefined':['a'],'afterSystemDefined':[]}},policies)
        for groups in ({'beforeSystemDefined':[],'afterSystemDefined':[]}, {'beforeSystemDefined':['a'],'afterSystemDefined':['a']}, ['a']):
            with self.assertRaises((ValueError,TypeError)):n.validate_ordering({'orderedFirewallPolicyIds':groups},policies)

    def test_page_bound_and_stall(self):
        c=n.Controller(R);c.get=Mock(return_value={'offset':0,'totalCount':1,'data':[]})
        with self.assertRaises(ValueError):c.pages('/proxy/network/integration/v1/sites')
        self.assertEqual(c.get.call_count,1)

    def test_dns_failure_never_retrieves_secret(self):
        with patch.object(n.socket,'getaddrinfo',return_value=[(socket.AF_INET,1,0,'',('192.0.2.1',443))]),patch.object(n.subprocess,'run') as run:
            result=n.controller_collect(R)
        self.assertEqual(result['phase'],'held');run.assert_not_called()

    def test_tls_failure_never_retrieves_secret(self):
        with patch.object(n.socket,'getaddrinfo',return_value=[(socket.AF_INET,1,0,'',('10.1.0.1',443))]), \
             patch.object(n.Controller,'get',side_effect=n.ssl.SSLError('fixture')),patch.object(n.subprocess,'run') as run:
            result=n.controller_collect(R)
        self.assertEqual(result['phase'],'held');run.assert_not_called()

    def test_closed_get_path_and_request_limit(self):
        c=n.Controller(R)
        with self.assertRaises(ValueError):c.get('https://elsewhere.example/')
        c.count=40
        with self.assertRaises(ValueError):c.get('/proxy/network/integration/v1/info')

    def test_successful_collection_with_synthetic_controller(self):
        source='11111111-1111-1111-1111-111111111111';dest='22222222-2222-2222-2222-222222222222'
        rule='33333333-3333-3333-3333-333333333333';group='44444444-4444-4444-4444-444444444444'
        class Fake:
            def __init__(self,r):self.records=[];self.count=0;self.last_path=None;self.key=None
            def get(self,path,authenticated=True):
                self.count+=1;self.last_path=path
                if authenticated:self.records.append({'path':path})
                if '/ordering?' in path:return {'orderedFirewallPolicyIds':{'beforeSystemDefined':[rule] if 'sourceFirewallZoneId='+source in path else [],'afterSystemDefined':[]}}
                return {}
            def pages(self,path):
                if path.endswith('/sites'):return [{'id':R['site_id']}]
                if path.endswith('/zones'):return [{'id':dest,'name':'External'}]
                if path.endswith('/networks'):return [{'enabled':True,'name':'Default LAN','zoneId':source}]
                if path.endswith('/policies'):return [{'id':rule,'source':{'zoneId':source,'trafficMatchingListId':group},'destination':{'zoneId':dest},'metadata':{'origin':'USER_DEFINED'}}]
                raise AssertionError(path)
        with patch.object(n,'Controller',Fake),patch.object(n.socket,'getaddrinfo',return_value=[(2,1,0,'',('10.1.0.1',443))]), \
             patch.object(n.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'fixture-secret')):
            result=n.controller_collect(R)
        self.assertEqual(result['phase'],'captured');self.assertFalse(result['rule_hit_proven'])
        self.assertNotIn('fixture-secret',json.dumps(result));self.assertTrue(any('/traffic-matching-lists/' in x['path'] for x in result['records']))


class NodeTests(unittest.TestCase):
    def test_real_file_capture_preserves_source_and_limits_commands(self):
        spec,files=fixture();d=m.base();calls=[]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'stage';source=Path(tmp)/'source';root.mkdir();source.mkdir()
            (source/'state.json').write_bytes(b'{"phase":"recovered"}\n');spec.update(stage=str(root),source_stage=str(source))
            def command(h,r,name,argv):
                calls.append(argv)
                raw=b'[]'
                if name=='services':raw=b'Id=timeservice.service\nActiveState=inactive\n\nId=systemd-timesyncd.service\nActiveState=active\n'
                elif name=='resolve':raw=m.encoded(addresses())
                for suffix,data in (('.json',b'{}'),('.stdout',raw),('.stderr',b'')):h.create(r/(name+suffix),data)
                return raw
            with patch.object(d,'source_lock',return_value=os.open(source,os.O_RDONLY)),patch.object(d,'command',side_effect=command), \
                 patch.object(d,'metadata',return_value={'exists':False}),patch.object(m.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=999,pw_gid=985)), \
                 patch.object(m.shutil,'which',return_value='/usr/sbin/ip'):
                report=d.capture(b.LocalFiles,spec,files)
            self.assertEqual(report['phase'],'captured');self.assertEqual(set(report['evidence']),set(m.CAPTURE_FILES))
            self.assertEqual((source/'state.json').read_bytes(),b'{"phase":"recovered"}\n')
            self.assertEqual(sum('probe' in x for x in calls),2)
            self.assertNotIn('restart',str(calls));self.assertNotIn('ntpd',str(calls))


if __name__=='__main__':unittest.main()
