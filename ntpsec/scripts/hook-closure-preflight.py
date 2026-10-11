#!/usr/bin/python3
"""Bounded static hook evidence. Never executes package hooks or Debconf code."""
import hashlib
from itertools import islice
import json
import os
from pathlib import Path
import pwd
import re
import selectors
import signal
import socket
import stat
import subprocess
import time

FILE_LIMIT = 1024 * 1024
TOTAL_LIMIT = 48 * 1024 * 1024
ANSWERS = {'watchdog/run', 'watchdog/restart', 'watchdog/run_keepalive',
           'watchdog/module', 'msmtp/apparmor'}
OVERRIDES = ('DEBCONF_SYSTEMRC', 'DEBCONF_DB_REPLACE', 'DEBCONF_DB_OVERRIDE',
             'DEBCONF_DB_FALLBACK', 'DPKG_ROOT', 'DEBCONF_USE_CDEBCONF',
             'APT_CONFIG', 'DEBCONF_FRONTEND', 'DEBIAN_FRONTEND')
SOURCES = ('/usr/share/debconf/confmodule', '/usr/share/debconf/frontend', '/usr/bin/debconf',
           '/usr/bin/debconf-apt-progress', '/usr/bin/debconf-copydb',
           '/usr/bin/debconf-get-selections', '/usr/sbin/invoke-rc.d',
           '/usr/bin/deb-systemd-invoke', '/usr/bin/deb-systemd-helper',
           '/usr/sbin/policy-rc.d', '/etc/init.d/watchdog',
           '/usr/share/watchdog/init.d', '/usr/lib/watchdog/watchdog.sh',
           '/usr/share/lighttpd/create-mime.assign.pl',
           '/usr/share/javascript-common/lighttpd.conf',
           '/usr/share/javascript-common/javascript-common.conf',
           '/usr/share/apache2/apache2-maintscript-helper',
           '/usr/sbin/a2enconf', '/usr/sbin/lighty-enable-mod')
CONFIGS = ('/etc/apt/apt.conf', '/etc/apt/listchanges.conf',
           '/etc/default/watchdog', '/etc/default/wd_keepalive',
           '/etc/default/msmtpd', '/etc/needrestart/needrestart.conf')
DIRECTORIES = ('/etc/apt/apt.conf.d', '/etc/apt/listchanges.conf.d',
               '/etc/needrestart/conf.d')
METADATA = ('/etc/watchdog.conf', '/etc/msmtprc', '/usr/sbin/sendmail',
            '/etc/lighttpd', '/etc/lighttpd/conf-enabled', '/etc/apache2',
            '/etc/apache2/conf-enabled', '/usr/share/javascript-common',
            '/var/lib/apt/listchanges', '/var/lib/apt/listchanges.db',
            '/var/lib/apt/listchanges-snapshot', '/var/lib/munin',
            '/etc/munin/plugins', '/var/lib/systemd/deb-systemd-helper-enabled',
            '/var/lib/systemd/deb-systemd-helper-masked',
            '/run/systemd/system', '/var/lib/dpkg/lock', '/var/lib/dpkg/lock-frontend')
UNITS = ('apt-daily.timer', 'apt-daily-upgrade.timer', 'apt-daily.service',
         'apt-daily-upgrade.service', 'unattended-upgrades.service',
         'watchdog.service', 'wd_keepalive.service', 'munin-node.service',
         'msmtpd.service', 'apparmor.service', 'lighttpd.service', 'apache2.service')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_protected(path, limit=FILE_LIMIT):
    path = Path(path)
    for parent in path.parents:
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                or info.st_gid != 0 or info.st_mode & 0o022):
            raise ValueError('unprotected ancestor')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
                or info.st_mode & 0o022 or info.st_nlink != 1 or info.st_size > limit):
            raise ValueError('unprotected or oversized file')
        data = bytearray()
        while len(data) <= limit:
            block = os.read(fd, min(65536, limit + 1 - len(data)))
            if not block:
                return bytes(data), {'uid': info.st_uid, 'gid': info.st_gid,
                                     'mode': oct(stat.S_IMODE(info.st_mode))}
            data.extend(block)
        raise ValueError('file bound exceeded')
    finally:
        os.close(fd)


def redact(text):
    lines = []
    changed = False
    for line in text.splitlines():
        if re.search(r'(?i)password|passwd|secret|token|credential|authorization|api.?key|proxy|header', line):
            lines.append('[sensitive line omitted]')
            changed = True
        else:
            clean = re.sub(r'\b(?:https?|socks\d?)://\S+', '[URI omitted]', line)
            changed |= clean != line
            lines.append(clean)
    return '\n'.join(lines), changed


def paragraphs(text):
    result = []
    for block in re.split(r'\n\s*\n', text):
        fields = {}
        for line in block.splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            if line[0].isspace() or ':' not in line:
                raise ValueError('unsupported continuation or field syntax')
            key, value = line.split(':', 1)
            key = key.lower().replace('-', '_').strip()
            if not re.fullmatch(r'[a-z_]+', key) or key in fields:
                raise ValueError('duplicate or invalid field')
            fields[key] = value.strip()
        if fields:
            result.append(fields)
    return result


def debconf_structure(text):
    """Parse only the reviewed static subset; never expand env or load drivers."""
    if '${' in text:
        raise ValueError('environment interpolation requires separate review')
    blocks = paragraphs(text)
    if not blocks or not {'config', 'templates'} <= blocks[0].keys():
        raise ValueError('Debconf database selection missing')
    allowed = {'name', 'driver', 'filename', 'directory', 'stack', 'mode',
               'readonly', 'required', 'backup', 'accept_type', 'reject_type',
               'accept_name', 'reject_name', 'config', 'templates'}
    result = []
    for fields in blocks:
        safe = {}
        for key, value in fields.items():
            if key in allowed:
                if not re.fullmatch(r'[A-Za-z0-9_./, ^$*+|()?:=-]{0,256}', value):
                    raise ValueError('unsupported structural field value')
                safe[key] = value
        safe['omitted_fields'] = sorted(set(fields) - allowed)
        result.append(safe)
    names = [b.get('name') for b in result[1:]]
    if None in names or len(names) != len(set(names)):
        raise ValueError('missing or duplicate backend name')
    return result


def answer_subset(text):
    """Scan records without retaining unrelated database contents or hashes."""
    answers = {}
    for block in re.split(r'\n\s*\n', text):
        names = re.findall(r'^Name: (.*)$', block, re.M)
        if not any(name in ANSWERS for name in names):
            continue
        if len(names) != 1 or names[0] in answers:
            raise ValueError('duplicate selected answer')
        fields = paragraphs(block)[0]
        name = names[0]
        value = fields.get('value')
        if value is not None:
            pattern = r'(?:true|false)' if name != 'watchdog/module' else r'[A-Za-z0-9_-]{0,64}'
            if not re.fullmatch(pattern, value):
                raise ValueError('unsupported selected answer value')
        answers[name] = {'value': value, 'present': True}
    return {name: answers.get(name, {'present': False}) for name in sorted(ANSWERS)}


def command(argv, seconds=15, limit=1024 * 1024):
    """Bound both pipes in memory; kill the process group on deadline or overflow."""
    output = [bytearray(), bytearray()]
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          stdin=subprocess.DEVNULL, cwd='/', start_new_session=True,
                          env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C',
                               'SYSTEMD_PAGER': '', 'SYSTEMD_COLORS': '0'}) as proc:
        try:
            end = time.monotonic() + seconds
            with selectors.DefaultSelector() as selector:
                for i, pipe in enumerate((proc.stdout, proc.stderr)):
                    selector.register(pipe, selectors.EVENT_READ, i)
                while selector.get_map():
                    left = end - time.monotonic()
                    if left <= 0:
                        raise ValueError('command deadline exceeded')
                    for key, _ in selector.select(left):
                        block = os.read(key.fd, 65536)
                        if not block:
                            selector.unregister(key.fileobj)
                        else:
                            output[key.data].extend(block)
                            if sum(map(len, output)) > limit:
                                raise ValueError('command output bound exceeded')
                rc = proc.wait(timeout=max(0.01, end - time.monotonic()))
        except BaseException:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            raise
    return {'argv': argv, 'rc': rc, 'stdout': output[0].decode('utf-8'),
            'stderr': output[1].decode('utf-8')}


def collect(spec):
    now = int(time.time())
    if (os.geteuid() != 0 or not __import__('sys').flags.isolated
            or not __import__('sys').dont_write_bytecode
            or socket.gethostname() != spec['hostname']
            or os.uname().machine != 'aarch64' or os.uname().release != spec['kernel']
            or os.environ.get('SUDO_USER') != 'ama' or os.environ.get('SUDO_UID') != '1000'
            or not spec['not_before'] <= now < spec['expires_epoch']):
        raise ValueError('approved identity, interpreter or window mismatch')
    release = Path('/usr/lib/os-release').read_text().splitlines()
    if not all(x in release for x in ('ID=debian', 'VERSION_ID="13"', 'VERSION_CODENAME=trixie')):
        raise ValueError('OS identity mismatch')
    if pwd.getpwnam('ama').pw_uid != 1000:
        raise ValueError('approved caller UID drift')
    report = {'state': 'collected', 'installation_authorized': False,
              'identity': {'hostname': socket.gethostname(), 'kernel': os.uname().release},
              'files': [], 'commands': [], 'gaps': [], 'started_epoch': now}
    total = 0
    reads = 0
    deadline = time.monotonic() + 120

    def get(path, text=False, limit=FILE_LIMIT, retain_hash=True):
        nonlocal total, reads
        reads += 1
        if reads > 512 or total > TOTAL_LIMIT:
            raise ValueError('aggregate read/count bound exceeded')
        if time.monotonic() > deadline:
            raise ValueError('overall collection deadline exceeded')
        record = {'path': str(path)}
        data = None
        try:
            data, metadata = read_protected(path, limit)
            total += len(data)
            if total > TOTAL_LIMIT:
                raise ValueError('aggregate read bound exceeded')
            record.update(metadata)
            if retain_hash:
                record['sha256'] = digest(data)
            if text:
                record['text'], record['redacted'] = redact(data.decode('utf-8'))
                if record['redacted']:
                    report['gaps'].append('redacted input: ' + str(path))
        except FileNotFoundError:
            record['absent'] = True
        except (OSError, ValueError, UnicodeError) as exc:
            # Do not put arbitrary exception messages or input values in evidence.
            record['error'] = type(exc).__name__
            report['gaps'].append('unreadable/unsupported input: ' + str(path))
            data = None
        report['files'].append(record)
        return data, record

    boot_before = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    continuity = {}
    for path, expected in spec['input_hashes'].items():
        _, record = get(path)
        continuity[path] = (record.get('sha256') == expected
                            and all(record.get(k) == v for k, v in spec['input_metadata'][path].items()))
    for path in spec['absent_inputs']:
        _, record = get(path)
        continuity[path] = record.get('absent', False)
    report['v6_input_continuity'] = continuity
    if not all(continuity.values()):
        report['gaps'].append('v6 input continuity failed')
    for path in SOURCES + CONFIGS:
        get(path, text=True)
    for directory in DIRECTORIES:
        root = Path(directory)
        if root.is_symlink():
            report['gaps'].append('symlink config directory: ' + directory)
            continue
        entries = sorted(islice(root.iterdir(), 49)) if root.exists() else []
        if len(entries) > 48:
            report['gaps'].append('config directory count exceeds 48: ' + directory)
            continue
        for path in entries:
            get(path, text=True)
    report['metadata'] = []
    for name in METADATA:
        entry = {'path': name}
        try:
            info = Path(name).lstat()
            entry.update(uid=info.st_uid, gid=info.st_gid, mode=oct(info.st_mode), size=info.st_size)
            if stat.S_ISLNK(info.st_mode):
                entry['symlink_target'], redacted = redact(os.readlink(name))
                if redacted:
                    report['gaps'].append('redacted symlink: ' + name)
        except FileNotFoundError:
            entry['absent'] = True
        report['metadata'].append(entry)
    # Native tool symlinks are resolved explicitly; configuration symlinks are rejected.
    for name in ('/usr/bin/dpkg', '/usr/bin/dpkg-query', '/usr/bin/systemctl'):
        resolved = Path(name).resolve(strict=True)
        data, _ = get(resolved, limit=32 * FILE_LIMIT)
        if data is None:
            raise ValueError('native command protection failed')
    report['extraction_helper_paths'] = []
    for name in ('/usr/lib/apt/apt-extracttemplates', '/usr/bin/apt-extracttemplates',
                 '/usr/lib/cdebconf/dpkg-preconfigure', '/usr/lib/cdebconf/frontend'):
        path = Path(name)
        entry = {'path': name, 'absent': not path.exists()}
        if path.exists():
            resolved = path.resolve(strict=True)
            entry['resolved'] = str(resolved)
            get(resolved, limit=32 * FILE_LIMIT)
        report['extraction_helper_paths'].append(entry)
    for label, argv in (
        ('packages', ['/usr/bin/dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n']),
        ('audit', ['/usr/bin/dpkg', '--audit']),
        ('architecture', ['/usr/bin/dpkg', '--print-architecture']),
        ('foreign_architectures', ['/usr/bin/dpkg', '--print-foreign-architectures']),
        ('units', ['/usr/bin/systemctl', '--no-pager', 'show',
                   '--property=Id,LoadState,ActiveState,SubState,UnitFileState,FragmentPath,DropInPaths', *UNITS]),
        ('helper_owners', ['/usr/bin/dpkg-query', '-S', *SOURCES])):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('overall command deadline exceeded')
        record = command(argv, seconds=min(15, remaining))
        record['label'] = label
        if label == 'packages':
            # Fixed package/version/status format contains no configuration values.
            redacted_out = False
        else:
            record['stdout'], redacted_out = redact(record['stdout'])
        record['stderr'], redacted_err = redact(record['stderr'])
        report['commands'].append(record)
        # Missing optional helper owners are retained for review; never accepted automatically.
        if record['rc'] or record['stderr'].strip() or redacted_out or redacted_err:
            report['gaps'].append('command requires review: ' + label)
    if report['commands'][3]['stdout'].strip():
        report['gaps'].append('foreign architectures require separate continuity review')
    versions = report['commands'][0]['stdout'].splitlines()
    report['v6_versions_present'] = all(line in versions for line in spec['version_lines'])
    current = {parts[0].split(':')[0]: (parts[1], parts[2]) for line in versions
               if len(parts := line.split('\t')) == 3}
    report['v6_unchanged_plan_packages_match'] = all(
        current.get(name) == (version, 'ii ') for name, version in spec['unchanged_packages'].items())
    installed = {line.split('\t')[0].split(':')[0] for line in versions
                 if len(line.split('\t')) == 3 and line.split('\t')[2] != 'un '}
    report['v6_new_packages_still_absent'] = not (installed & set(spec['new_packages']))
    if not all(report[k] for k in ('v6_versions_present', 'v6_new_packages_still_absent',
                                 'v6_unchanged_plan_packages_match')):
        report['gaps'].append('v6 package plan continuity failed')
    status_data, _ = get('/var/lib/dpkg/status', limit=4 * FILE_LIMIT)
    report['pending_package_triggers'] = []
    if status_data is not None:
        for block in re.split(rb'\n\n', status_data):
            trigger_lines = [line.decode('ascii') for line in block.splitlines()
                             if line.startswith((b'Triggers-Pending:', b'Triggers-Awaited:'))]
            if trigger_lines:
                name = re.search(rb'^Package: ([a-z0-9+.-]+)$', block, re.M)
                report['pending_package_triggers'].append(
                    {'package': name[1].decode() if name else None, 'triggers': trigger_lines})
    if report['pending_package_triggers']:
        report['gaps'].append('pending package triggers')
    data, _ = get('/var/lib/dpkg/triggers/Unincorp', text=True)
    if data and data.strip():
        report['gaps'].append('unincorporated triggers')
    updates = Path('/var/lib/dpkg/updates')
    report['dpkg_updates'] = sorted(p.name for p in islice(updates.iterdir(), 65))
    if len(report['dpkg_updates']) > 64:
        raise ValueError('dpkg update record count exceeded')
    if report['dpkg_updates']:
        report['gaps'].append('pending dpkg update records')
    report['environment_overrides_present'] = [key for key in OVERRIDES if key in os.environ]
    if report['environment_overrides_present']:
        report['gaps'].append('environment overrides need review; values omitted')
    candidates = [Path(pwd.getpwuid(0).pw_dir) / '.debconfrc', Path('/etc/debconf.conf'),
                  Path('/usr/share/debconf/debconf.conf')]
    selected = next((p for p in candidates if p.exists() or p.is_symlink()), None)
    report['debconf_candidates'] = [str(p) for p in candidates]
    report['debconf_selected_default'] = str(selected) if selected else None
    # Collect candidate structure only; no config source, driver, or helper is executed.
    structures = {}
    for path in candidates:
        data, _ = get(path, retain_hash=False)
        if data is not None:
            try:
                structures[str(path)] = debconf_structure(data.decode('utf-8'))
                if any(b['omitted_fields'] for b in structures[str(path)]):
                    report['gaps'].append('omitted Debconf fields: ' + str(path))
            except (ValueError, UnicodeError):
                report['gaps'].append('unsupported Debconf config: ' + str(path))
    report['debconf_structure'] = structures
    blocks = structures.get(str(selected), [])
    answer_path = None
    if blocks and not report['environment_overrides_present']:
        by_name = {b['name']: b for b in blocks[1:]}
        config = by_name.get(blocks[0]['config'], {})
        report['debconf_answers'] = {}
        filename = config.get('filename', '')
        if (config.get('driver') == 'File' and not config['omitted_fields']
                and re.fullmatch(r'/var/(?:cache|lib)/debconf/[A-Za-z0-9_.-]+', filename)
                and not any(k in config for k in ('accept_name', 'reject_name', 'accept_type'))
                and config.get('reject_type', 'password') == 'password'):
            data, _ = get(filename, limit=4 * FILE_LIMIT, retain_hash=False)
            if data is not None:
                try:
                    report['debconf_answers'] = answer_subset(data.decode('utf-8'))
                    answer_path = filename
                except (ValueError, UnicodeError):
                    report['gaps'].append('unsupported selected Debconf answers')
            else:
                report['gaps'].append('selected Debconf database missing')
        else:
            report['gaps'].append('selected Debconf backend requires review; database not read')
    else:
        report['gaps'].append('Debconf selection unresolved')
    report['debconf_answer_snapshot_unchanged'] = False
    if answer_path:
        data, _ = get(answer_path, limit=4 * FILE_LIMIT, retain_hash=False)
        try:
            report['debconf_answer_snapshot_unchanged'] = (data is not None and
                answer_subset(data.decode('utf-8')) == report['debconf_answers'])
        except (ValueError, UnicodeError):
            pass
        if not report['debconf_answer_snapshot_unchanged']:
            report['gaps'].append('selected Debconf answers changed or became unreadable')
    if selected and str(selected) in structures:
        data, _ = get(selected, retain_hash=False)
        try:
            report['debconf_structure_unchanged'] = (data is not None and
                debconf_structure(data.decode('utf-8')) == structures[str(selected)])
        except (ValueError, UnicodeError):
            report['debconf_structure_unchanged'] = False
        if not report['debconf_structure_unchanged']:
            report['gaps'].append('selected Debconf structure changed')
    unit_output = next(c['stdout'] for c in report['commands'] if c['label'] == 'units')
    unit_paths = []
    for line in unit_output.splitlines():
        if line.startswith(('FragmentPath=', 'DropInPaths=')):
            for value in line.partition('=')[2].split():
                if not re.fullmatch(r'/(?:usr/lib|lib|etc|run)/systemd/system/[A-Za-z0-9_.@/-]+', value):
                    report['gaps'].append('unsupported unit path')
                else:
                    unit_paths.append(value)
    if len(set(unit_paths)) > 48:
        raise ValueError('unit source path count exceeds 48')
    for name in sorted(set(unit_paths)):
        resolved = Path(name).resolve(strict=True)
        if not re.fullmatch(r'/(?:usr/lib|lib|etc|run)/systemd/system/[A-Za-z0-9_.@/-]+', str(resolved)):
            report['gaps'].append('unit resolved outside approved paths')
            continue
        get(resolved, text=True)
    # Reread non-secret files to detect collection drift. Database has no retained hash.
    before = list(report['files'])
    report['file_continuity'] = True
    for record in before:
        if 'sha256' in record:
            _, after = get(record['path'], limit=32 * FILE_LIMIT)
            if any(after.get(k) != record.get(k) for k in ('sha256', 'uid', 'gid', 'mode')):
                report['file_continuity'] = False
    after_packages = command(report['commands'][0]['argv'], seconds=min(15, max(.01, deadline - time.monotonic())))
    report['package_snapshot_unchanged'] = (after_packages['rc'] == 0 and not after_packages['stderr']
                                          and after_packages['stdout'].splitlines() == versions)
    report['boot_unchanged'] = boot_before == Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if not all(report[k] for k in ('file_continuity', 'package_snapshot_unchanged', 'boot_unchanged')):
        report['gaps'].append('collection continuity failed')
    report['finished_epoch'] = int(time.time())
    report['gaps'] = sorted(set(report['gaps']))
    report['state'] = 'collected_with_gaps' if report['gaps'] else 'collected'
    report['installation_ready'] = False
    return report
