#!/usr/bin/python3
"""Run the same three mDNS queries sequentially through Windows and WSL sockets."""
import base64
import json
import shutil
import subprocess
import tempfile


def queries(spec, client):
    return [{'name': name, 'type': kind, 'query_base64': base64.b64encode(client['query'](name, kind)).decode()}
            for name, kind in (('_ntp._udp.local', 12), (spec['hostname']+'.local', 1), (spec['hostname']+'.local', 28))]


def decode(result, spec, client):
    records = []
    if len(result['replies']) > 64: raise ValueError('native reply count bound')
    for reply in result['replies']:
        raw = base64.b64decode(reply['base64'], validate=True)
        if len(raw) > 9001: raise ValueError('native reply size bound')
        reply['accepted_source'] = reply['source'] == [spec['endpoints'][0], 5353]
        try: reply['records'] = client['dns_records'](raw)
        except (ValueError, IndexError) as error: reply['parse_error'] = str(error)[:500]
        else:
            if reply['accepted_source']: records.extend(reply['records'])
    result['accepted_source_records'] = records
    result['matched'] = client['discovery_matches'](records, spec['endpoints'], spec['hostname'])


def native_capture(spec, client, windows_source, output):
    executable = shutil.which('powershell.exe')
    if executable is None: raise ValueError('native Windows PowerShell unavailable')
    expected = queries(spec, client)
    payload = base64.b64encode(json.dumps({'source_ipv4': spec['source_ipv4'], 'queries': expected}).encode()).decode()
    command = windows_source.decode()+'\nInvoke-MdnsCapture -SpecBase64 "'+payload+'"\n'
    encoded = base64.b64encode(command.encode('utf-16-le')).decode()
    native = {'executable': executable}; output['windows'] = native
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            process = subprocess.run([executable, '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                                     stdout=out, stderr=err, timeout=20, check=False)
            native['returncode'] = process.returncode
        except (OSError, subprocess.TimeoutExpired) as error:
            native['error'] = str(error)[:500]
        finally:
            for name, stream in (('stdout', out), ('stderr', err)):
                stream.seek(0); raw = stream.read(1024**2+1)
                native[name] = raw[:1024**2].decode('utf-8-sig', errors='replace')
                native[name+'_truncated'] = len(raw) > 1024**2
    if native.get('returncode') != 0 or native['stdout_truncated']:
        raise ValueError('native capture failed; retained output; no replay')
    native['capture'] = json.loads(native['stdout']); decode(native['capture'], spec, client)
    return native['capture']


def capture(spec, client, diagnostic, windows_source, output):
    native = native_capture(spec, client, windows_source, output)
    expected = queries(spec, client)
    output['wsl'] = {}
    diagnostic['capture'](dict(spec, skip_network_metadata=True), client, output['wsl'])
    captures = (native, output['wsl']['mdns'])
    for value in captures:
        actual = [{k: q[k] for k in ('name', 'type', 'query_base64')} for q in value['queries']]
        if actual != expected: raise ValueError('paired query bytes/order mismatch')
    output['identical_queries'] = True
    output['comparison_source_ipv4'] = spec['source_ipv4']
    output['timing_note'] = 'Sequential captures; source ports differ. Results do not alone locate a packet drop.'
