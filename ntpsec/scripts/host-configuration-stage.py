#!/usr/bin/python3
"""Sealed boot bring-up or account/loader prerequisites; never activate time services."""
import argparse
import base64
from contextlib import contextmanager
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import stat
import sys
import time

ACCEPTANCE_MODES = ('start','probe','accept','readback','cleanup')

BOOT_PATHS = ('/boot/firmware/config.txt', '/boot/firmware/cmdline.txt')
HARDWARE_LABELS = {'network', 'native', 'boot_files', 'new_boot', 'uart', 'pps', 'rtc', 'no_clock_cutover'}
RUNTIME_LABELS = {'network', 'native', 'hardware_gate', 'account', 'loader', 'python', 'candidate', 'no_clock_cutover'}


def encoded(value):
    return (json.dumps(value, sort_keys=True)+'\n').encode()


def render_boot(config, cmdline):
    """Preserve unrelated boot settings and the storage/root command line."""
    for line in config.splitlines():
        value = line.split('#', 1)[0].strip()
        if (value.startswith(('include ', 'enable_uart=', 'dtparam=i2c_arm=',
                              'dtparam=uart', 'dtoverlay=uart', 'dtoverlay=miniuart',
                              'dtoverlay=disable-bt', 'dtoverlay=pps-gpio', 'dtoverlay=i2c-rtc'))):
            raise ValueError('existing UART/PPS/RTC settings or includes require review')
    lines = cmdline.splitlines()
    if len(lines) != 1 or any(c in cmdline for c in ('\x00', '\r')):
        raise ValueError('single boot command line required')
    tokens = lines[0].split()
    if (tokens.count('console=serial0,115200') != 1 or
            len([t for t in tokens if t.startswith('root=')]) != 1 or
            any(t.startswith(('console=ttyAMA', 'console=ttyS')) for t in tokens)):
        raise ValueError('exact observed serial console/root required')
    candidate = config + ('' if config.endswith('\n') else '\n')
    candidate += ('\n# Source-built GPSD: Uputronics M8, PPS BCM18, RV3028 at 0x52\n'
                  '[all]\nenable_uart=1\ndtparam=i2c_arm=on\ndtoverlay=disable-bt\n'
                  'dtoverlay=pps-gpio,gpiopin=18\ndtoverlay=i2c-rtc,rv3028\n')
    tokens.remove('console=serial0,115200')
    return candidate.encode(), (' '.join(tokens)+ ('\n' if cmdline.endswith('\n') else '')).encode()


def sanitized_services(text):
    # PIDs/restart counters cannot remain equal across a controlled reboot.
    return '\n'.join(l for l in text.splitlines() if not l.startswith(('MainPID=', 'NRestarts=')))


def pps_mapping(cells, controller, falling):
    return pps_checker().pps_mapping(cells, controller, falling)


def observation_equal(actual, expected, new_boot=False):
    a, b = dict(actual), dict(expected)
    if new_boot:
        a.pop('boot_id'); b.pop('boot_id')
        a['services'] = sanitized_services(a['services']); b['services'] = sanitized_services(b['services'])
    return a == b


def unit_states(text):
    states={}
    fields={'Id','LoadState','ActiveState','SubState','UnitFileState','FragmentPath','DropInPaths','User','Group'}
    for block in text.strip().split('\n\n'):
        values=dict(line.split('=',1) for line in block.splitlines() if '=' in line and line.split('=',1)[0] in fields)
        name=values.get('Id')
        if not name or name in states:raise ValueError('unique service identities required')
        states[name]=values
    return states


def validate_recipe(kind, value):
    if value.get('schema') != 1 or value.get('hostname') != 'j2-svntp1' or value.get('receiver_io_authorized') is not False:
        raise ValueError('fixed node/no receiver I/O recipe required')
    if kind == 'hardware':
        keys = {'schema','hostname','model_prefix','config_path','cmdline_path','uart_alias','uart_driver',
                'pps_gpio','pps_edge','rtc_compatible','rtc_address','datasheet_sha256',
                'snapshot_max_age_seconds','reboot_delay_seconds','receiver_io_authorized'}
        if (set(value) != keys or value['model_prefix'] != 'Raspberry Pi 4 Model B '
                or value['config_path'] != BOOT_PATHS[0] or value['cmdline_path'] != BOOT_PATHS[1]
                or value['uart_alias'] != '/dev/serial0' or value['uart_driver'] != 'uart-pl011'
                or value['pps_gpio'] != 18 or value['pps_edge'] != 'rising'
                or value['rtc_compatible'] != 'microcrystal,rv3028' or value['rtc_address'] != '0052'
                or not re.fullmatch('[0-9a-f]{64}',value['datasheet_sha256'])
                or value['snapshot_max_age_seconds'] != 86400 or value['reboot_delay_seconds'] != 5):
            raise ValueError('reviewed BCM18/RV3028/PL011 boot recipe required')
    elif kind == 'runtime':
        keys = {'schema','hostname','ntp_user','ntp_group','account_home','account_shell','gpsd_user','gpsd_group',
                'cache_path','cache_refresh','python_modules_root','gpsd_baud','installed_modes_preserved',
                'service_installation_authorized','service_activation_authorized','receiver_io_authorized'}
        if (set(value) != keys or value['ntp_user'] != 'ntp' or value['ntp_group'] != 'ntp'
                or value['account_home'] != '/nonexistent' or value['account_shell'] != '/usr/sbin/nologin'
                or value['gpsd_user'] != 'nobody' or value['gpsd_group'] != 'dialout'
                or value['cache_path'] != '/etc/ld.so.cache' or value['cache_refresh'] != ['/usr/sbin/ldconfig','-X']
                or value['python_modules_root'] != '/usr/local/lib/python3.13/dist-packages' or value['gpsd_baud'] != 115200
                or value['installed_modes_preserved'] is not True
                or value['service_installation_authorized'] is not False or value['service_activation_authorized'] is not False):
            raise ValueError('account/cache/candidate-only runtime recipe required')
    else:
        raise ValueError('closed configuration stage required')


def identity(spec, initial=False):
    if (os.geteuid() or os.getegid() or not sys.flags.isolated or not sys.dont_write_bytecode
            or socket.gethostname() != spec['hostname'] or os.uname().machine != 'aarch64'
            or os.uname().release != spec['kernel'] or os.environ.get('SUDO_USER') != 'ama'
            or os.environ.get('SUDO_UID') != '1000' or os.environ.get('SUDO_GID') != '1000'
            or initial and boot_id() != spec['boot_id']):
        raise ValueError('approved isolated root target/caller/boot required')


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def load_module(root, name, digest, helper):
    data = helper.read(root/name, limit=2*1024**2)
    if helper.sha(data) != digest:
        raise ValueError('sealed configuration helper drift')
    spec = importlib.util.spec_from_file_location('host_'+name.replace('-', '_'),root/name)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def pps_checker():
    # Standalone checker is a verified member of new host bundles.
    spec = importlib.util.spec_from_file_location('gpio_pps_checker', Path(__file__).with_name('check-pps.py'))
    checker = importlib.util.module_from_spec(spec); spec.loader.exec_module(checker)
    return checker


def gpio_pps_metadata(sysroot=Path('/sys'), devroot=Path('/dev'), observation=None):
    return pps_checker().gpio_pps_metadata(sysroot, devroot, observation)


def uart_ancestry(tty, sysroot=Path('/sys'), chain=None):
    node = tty.resolve(strict=True)
    if not node.is_relative_to(sysroot/'devices'):
        raise ValueError('UART must resolve within sysfs devices')
    if chain is None:
        chain = []
    while node != sysroot/'devices':
        if len(chain) >= 16:
            raise ValueError('bounded UART ancestry required')
        item = {'path': str(node), 'driver': None, 'subsystem': None, 'of_node': None, 'compatible': []}
        chain.append(item)
        for name, parent in [('driver', sysroot/'bus'), ('subsystem', sysroot/'bus'),
                             ('of_node', sysroot/'firmware/devicetree/base')]:
            link = node/name
            if link.is_symlink():
                resolved = link.resolve(strict=True)
                item[name] = str(resolved)
                allowed = resolved.is_relative_to(parent) and (resolved != parent or name == 'of_node')
                if name == 'subsystem' and resolved == sysroot/'class/tty':
                    allowed = True
                if not allowed:
                    raise ValueError(f'UART metadata link escaped sysfs tree: {link} -> {resolved}')
        if item['of_node']:
            prop = Path(item['of_node'])/'compatible'
            if prop.exists():
                if prop.is_symlink() or not prop.is_file():
                    raise ValueError('regular UART compatibility property required')
                with prop.open('rb') as stream:
                    raw = stream.read(4097)
                if len(raw) > 4096:
                    raise ValueError('bounded UART compatibility required')
                item['compatible'] = raw.rstrip(b'\0').decode('ascii').split('\0')
        node = node.parent
    return chain


def pl011_parent(chain, driver, sysroot=Path('/sys')):
    matches = [item for item in chain
               if item['driver'] == str(sysroot/'bus/amba/drivers'/driver)
               and item['subsystem'] == str(sysroot/'bus/amba')
               and 'arm,pl011' in item['compatible']]
    if len(matches) != 1:
        raise ValueError('one PL011 AMBA ancestor required')
    item = matches[0]
    if (sysroot/'bus/amba/devices'/Path(item['path']).name).resolve(strict=True) != Path(item['path']):
        raise ValueError('PL011 AMBA registry identity mismatch')
    return item


class Transaction:
    def __init__(self, spec, code_root=None, code_members=None):
        self.spec = spec; self.root = Path(spec['stage']); self.recipe = spec['host_recipe']
        code_root = self.root if code_root is None else Path(code_root)
        code_members = spec['members'] if code_members is None else code_members
        self.code_root = code_root; self.code_members = code_members
        import hashlib
        if hashlib.sha256((code_root/'foundation-install.py').read_bytes()).hexdigest() != code_members['foundation-install.py']:
            raise ValueError('maintained helper digest mismatch')
        # Bootstrap executes this helper from sealed bytes; later entry verifies it before import.
        helper_spec = importlib.util.spec_from_file_location('host_guard',code_root/'foundation-install.py')
        self.h = importlib.util.module_from_spec(helper_spec); helper_spec.loader.exec_module(self.h)
        self.net = load_module(code_root,'host-network-stage.py',code_members['host-network-stage.py'],self.h)
        self.core = self.net.Transaction.__new__(self.net.Transaction)
        self.core.spec = spec; self.core.root = self.root; self.core.r = spec['recipe']; self.core.h = self.h
        self.core.i = load_module(code_root,'inspect-source-destinations.py',code_members['inspect-source-destinations.py'],self.h)
        self.core.cm = load_module(code_root,'clockmaker.py',code_members['clockmaker.py'],self.h)
        self.core.baseline = json.loads(self.h.read(self.root/'baseline.json'))
        self.core.original = self.net.properties(self.core.baseline['queries']['ethernet_profiles'][spec['original_uuid']]['stdout'])
        self.core.continuity = self.continuity
        self.run = self.core.run; self.write = self.core.write; self.state = self.core.state
        self.baseline = self.core.baseline

    def verify(self, files):
        self.h.ancestors(self.root)
        if stat.S_IMODE(self.root.stat().st_mode) != 0o700:
            raise ValueError('private root configuration stage required')
        expected = set(self.spec['members']) | {'spec.json','manifest.json','state.json','before.json',
                    '.lock','commands.jsonl','state.json.new','before.json.new','timeservice-candidate.json','timeservice.service'}
        if not {p.name for p in self.root.iterdir()} <= expected:
            raise ValueError('unknown configuration stage entry; preserve evidence')
        if self.h.read(self.root/'spec.json') != encoded(self.spec) or json.loads(self.h.read(self.root/'manifest.json')) != self.spec['members']:
            raise ValueError('configuration specification drift')
        for path in self.root.iterdir():
            if stat.S_IMODE(path.lstat().st_mode) != 0o600:
                raise ValueError('root configuration evidence modes must be 0600')
            self.h.read(path,limit=8*1024**2)
        for name,digest in self.spec['members'].items():
            data = self.h.read(self.root/name,limit=2*1024**2)
            if self.h.sha(data) != digest or data != files[name]:
                raise ValueError('sealed configuration input drift')

    def continuity(self):
        state = self.state()
        if not observation_equal(self.core.i.observation(), self.baseline['observation'], new_boot=boot_id()!=self.spec['boot_id']):
            raise ValueError('package/service/Python/process drift')
        if self.core.cm.inspect_install(self.root/'release.json',self.spec['members']['release.json']) != self.baseline['installed_state']:
            raise ValueError('native release drift')
        expected=unit_states(self.baseline['queries']['time_units']['stdout'])
        actual=self.run(['/usr/bin/systemctl','show','--no-pager',
            '--property=Id,LoadState,ActiveState,SubState,UnitFileState,FragmentPath,DropInPaths,User,Group',*expected])
        if unit_states(actual)!=expected:
            raise ValueError('time/bootstrap/Avahi/serial unit state drift')
        edited = self.spec['operation'] == 'hardware' and state['phase'] not in ('staged','recovered','recovery_files_restored','recovery_reboot_submitted')
        for name,record in self.baseline['protected_files'].items():
            desired = record
            if edited and name in BOOT_PATHS:
                candidate = 'config-candidate.txt' if name == BOOT_PATHS[0] else 'cmdline-candidate.txt'
                desired = {'sha256': self.spec['members'][candidate]}
            elif self.spec['operation'] == 'runtime' and name in BOOT_PATHS:
                desired = {'sha256':self.spec['hardware_prerequisite']['boot_hashes'][name]}
            try: data = self.h.read(Path(name),limit=256*1024)
            except FileNotFoundError: data = None
            if (data is None)!=(desired is None) or data is not None and self.h.sha(data)!=desired['sha256']:
                raise ValueError('protected configuration input drift: '+name)
        for directory,pattern in (('/etc/ld.so.conf.d','*.conf'),('/etc/systemd/system/timeservice.service.d','*.conf')):
            if {str(p) for p in Path(directory).glob(pattern)}!={p for p in self.baseline['protected_files'] if Path(p).parent==Path(directory)}:
                raise ValueError('loader/service drop-in membership drift')

    def network_checks(self):
        # Reuse the accepted networking contract, without changing any profiles.
        result = self.core.checks({'candidate_uuid':self.spec['network_candidate_uuid']}, allow_loopback_uuid_change=True)
        if set(result) != self.net.LABELS or any(v is not True for v in result.values()):
            raise ValueError('complete retained dual-stack network checks required')

    def before(self):
        return json.loads(self.h.read(self.root/'before.json'))

    def snapshot_file(self, path):
        data = self.h.read(path,limit=2*1024**2); info = path.lstat()
        return {'sha256':self.h.sha(data),'base64':base64.b64encode(data).decode(),
                'mode':stat.S_IMODE(info.st_mode),'uid':info.st_uid,'gid':info.st_gid}

    def preflight(self):
        self.network_checks()
        before = self.before()
        if self.spec['operation'] == 'hardware':
            model = Path('/proc/device-tree/model').read_bytes().rstrip(b'\0').decode()
            if not model.startswith(self.recipe['model_prefix']):
                raise ValueError('Raspberry Pi 4 model required')
            before['model'] = model
            for unit in ('serial-getty@serial0.service','serial-getty@ttyAMA0.service','hciuart.service'):
                active = self.run(['/usr/bin/systemctl','is-active',unit],allowed=(0,3,4)).strip()
                enabled = self.run(['/usr/bin/systemctl','is-enabled',unit],allowed=(0,1,3,4)).strip()
                if active not in ('inactive','failed','unknown') or enabled not in ('disabled','masked','not-found'):
                    raise ValueError('serial/Bluetooth ownership changed: '+unit)
            before['boot_files'] = {p:self.snapshot_file(Path(p)) for p in BOOT_PATHS}
            for p,v in before['boot_files'].items():
                if v['sha256'] != self.baseline['protected_files'][p]['sha256']:
                    raise ValueError('original boot-file drift')
        else:
            before['hardware'] = self.hardware_gate()
            before['accounts'] = self.accounts()
            if 'ntp' in before['accounts']['users'] or 'ntp' in before['accounts']['groups']:
                raise ValueError('NTP name already exists; fresh account review required')
            before['cache'] = self.snapshot_file(Path(self.recipe['cache_path']))
            for name,record in self.baseline['protected_files'].items():
                if name.startswith('/etc/ld'):
                    data = self.h.read(Path(name),limit=256*1024)
                    if record is None or self.h.sha(data)!=record['sha256']:
                        raise ValueError('loader configuration drift')
        self.write('before.json',before)

    def apply(self):
        with self.core.lock():
            if self.state()['phase'] != 'staged':
                raise ValueError('configuration apply already consumed')
            try:
                if not self.spec['prepared_epoch']-300 <= time.time() < self.spec['expires_epoch']:
                    raise ValueError('configuration apply window expired')
                self.preflight()
                self.write('state.json',{'phase':'applying','boot_id':boot_id()})
                if self.spec['operation'] == 'hardware':
                    for path,name in zip(BOOT_PATHS,('config-candidate.txt','cmdline-candidate.txt')):
                        before=self.before()['boot_files'][path]
                        if self.h.sha(self.h.read(Path(path))) != before['sha256']:
                            raise ValueError('boot file changed before replacement')
                        self.h.replace(Path(path),self.h.read(self.root/name),before['mode'])
                    state=self.state(); state['phase']='boot_files_prepared';self.write('state.json',state)
                    self.continuity()
                else:
                    self.apply_runtime()
                return self.state()
            except BaseException as error:
                state=self.state();state.update(phase='apply_held',error=str(error)[:500]);self.write('state.json',state);raise

    def schedule_reboot(self, console_ready, recovery=False):
        if console_ready is not True:
            raise ValueError('operator console readiness declaration required')
        with self.core.lock():
            state=self.state()
            expected = 'recovery_files_restored' if recovery else 'boot_files_prepared'
            if self.spec['operation']!='hardware' or state['phase']!=expected:
                raise ValueError('one eligible boot reboot required')
            self.network_checks()
            state.update(phase='recovery_reboot_submitted' if recovery else 'reboot_submitted',
                         reboot_from_boot=boot_id(),console_ready=True)
            self.write('state.json',state)  # Never retry after an uncertain systemd submission.
            self.run(['/usr/bin/systemd-run','--unit=ntp-host-reboot-'+self.spec['operation_id']+('-recovery' if recovery else ''),
                      '--on-active=5s','--timer-property=AccuracySec=1s','/usr/bin/systemctl','reboot'])
            return self.state()

    def hardware_metadata(self, expected_pps=None):
        alias=Path(self.recipe['uart_alias'])
        observation={'boot_id':boot_id(),'alias':str(alias),'uart':None,'ancestors':[]}
        try:
            if not alias.is_symlink() or alias.lstat().st_uid!=0:
                raise ValueError('protected serial0 alias required')
            uart=alias.resolve(strict=True);observation['uart']=str(uart)
            if not re.fullmatch('/dev/ttyAMA[0-9]+',str(uart)) or not stat.S_ISCHR(uart.stat().st_mode):
                raise ValueError('PL011 character UART required')
            uart_ancestry(Path('/sys/class/tty')/uart.name,chain=observation['ancestors'])
            parent=pl011_parent(observation['ancestors'],self.recipe['uart_driver'])
        except (OSError, ValueError) as error:
            observation['error']=str(error)[:500]
            raise
        finally:
            state=self.state();state['uart_observation']=observation;self.write('state.json',state)
        driver=self.recipe['uart_driver']
        uinfo=uart.stat()
        # Metadata only: no stty, GNSS polling, PPS ioctls or RTC read/write.
        observation={'boot_id':boot_id()}
        try:
            pps=gpio_pps_metadata(observation=observation)
            if expected_pps is not None and pps != expected_pps:
                observation['expected']=expected_pps
                raise ValueError('accepted GPIO PPS mapping drift')
        except (OSError, ValueError) as error:
            observation['error']=str(error)[:500]
            raise
        finally:
            state=self.state();state['pps_observation']=observation;self.write('state.json',state)
        rtc=[]
        for path in sorted(Path('/sys/class/rtc').glob('rtc[0-9]*')):
            node=path/'device/of_node'
            compatible=(node/'compatible').read_bytes() if (node/'compatible').exists() else b''
            if self.recipe['rtc_compatible'].encode() not in compatible.split(b'\0'):continue
            address=(path/'device').resolve(strict=True).name
            if not re.fullmatch('[0-9]+-0052',address):raise ValueError('RTC I2C 0x52 required')
            dev=Path('/dev')/path.name
            if not stat.S_ISCHR(dev.stat().st_mode):raise ValueError('RTC character node required')
            rtc.append({'device':str(dev),'of_node':str(node.resolve()),'address':address,'name':(path/'name').read_text().strip()})
        if len(rtc)!=1:
            raise ValueError('one observed BCM18 PPS and RV3028 RTC required')
        return {'uart':str(uart),'uart_alias':str(alias),'uart_driver':driver,'uart_parent':parent['path'],
                'uart_of_node':parent['of_node'],'uart_uid':uinfo.st_uid,
                'uart_gid':uinfo.st_gid,'uart_mode':stat.S_IMODE(uinfo.st_mode),'pps':pps,'rtc':rtc[0]}

    def hardware_gate(self):
        gate=self.spec['hardware_prerequisite']; root=Path(gate['stage'])
        raw=self.h.read(root/'spec.json',limit=2*1024**2)
        state=json.loads(self.h.read(root/'state.json'))
        if (self.h.sha(raw)!=gate['spec_sha256'] or state['phase']!='accepted'
                or state['accepted_boot_id']!=boot_id() or not time.time()-86400<=state['accepted_epoch']<=time.time()+300
                or state['checks'].keys()!=HARDWARE_LABELS
                or any(v is not True for v in state['checks'].values())):
            raise ValueError('accepted bound hardware/reboot gate required')
        receipt_path=self.root/'hardware-acceptance.json'
        if receipt_path.exists():
            receipt=json.loads(self.h.read(receipt_path))
            if receipt is not None and (receipt['spec_sha256']!=gate['spec_sha256']
                    or receipt['bundle_sha256']!=gate['bundle_sha256']
                    or receipt['boot_id']!=state['accepted_boot_id']
                    or receipt['checks']!=state['checks'] or receipt['hardware']!=state['hardware']):
                raise ValueError('sealed hardware acceptance receipt drift')
        previous=self.recipe;self.recipe=json.loads(raw)['host_recipe']
        try:actual=self.hardware_metadata()
        finally:self.recipe=previous
        if actual!=state['hardware']:
            raise ValueError('accepted hardware mapping/permission drift')
        return state

    def accounts(self):
        # Parse protected local databases, returning only reviewed identity fields.
        users={};groups={}
        for line in self.h.read(Path('/etc/passwd'),limit=1024*1024).decode().splitlines():
            f=line.split(':')
            if f[0] not in ('nobody','ntp'): continue
            if len(f)!=7 or f[0] in users:raise ValueError('malformed account identity')
            users[f[0]]={'uid':int(f[2]),'gid':int(f[3]),'home':f[5],'shell':f[6]}
        for line in self.h.read(Path('/etc/group'),limit=1024*1024).decode().splitlines():
            f=line.split(':')
            if f[0] not in ('dialout','ntp'): continue
            if len(f)!=4 or f[0] in groups:raise ValueError('malformed group identity')
            groups[f[0]]={'gid':int(f[2]),'members':f[3].split(',') if f[3] else []}
        expected_users=self.baseline['queries']['accounts']['entries']
        expected_groups=self.baseline['queries']['groups']['entries']
        if users.get('nobody')!=expected_users['nobody'] or groups.get('dialout')!=expected_groups['dialout']:
            raise ValueError('GPSD nobody/dialout identity drift')
        return {'users':users,'groups':groups}

    def apply_runtime(self):
        self.run(['/usr/sbin/useradd','--system','--user-group','--no-create-home',
                  '--home-dir','/nonexistent','--shell','/usr/sbin/nologin','ntp'])
        accounts=self.accounts();u=accounts['users'].get('ntp');g=accounts['groups'].get('ntp')
        if not u or not g or not 0<u['uid']<1000 or u['gid']!=g['gid'] or u['home']!='/nonexistent' or u['shell']!='/usr/sbin/nologin' or g['members']:
            raise ValueError('dedicated NTP system account required')
        state=self.state();state['created_account']=accounts;self.write('state.json',state)
        self.run(self.recipe['cache_refresh'])
        state=self.state();state['cache_after']=self.snapshot_file(Path(self.recipe['cache_path']))
        self.write('state.json',state)
        # Render from the accepted observed UART, without copying global service/config files.
        hardware=self.hardware_gate();template=json.loads(self.h.read(self.root/'timeservice-template.json'))
        raw=json.dumps(template).replace('@UART_DEVICE@',hardware['hardware']['uart_alias']).replace('@NTP_USER@','ntp').replace('@NTP_GROUP@','ntp')
        candidate=json.loads(raw)
        validator=load_module(self.code_root,'timeservice.py',self.code_members['timeservice.py'],self.h)
        validator.validate(candidate)
        self.h.create(self.root/'timeservice-candidate.json',encoded(candidate))
        self.h.create(self.root/'timeservice.service',self.h.read(self.root/'timeservice-template.service'))
        self.runtime_validation()
        state=self.state();state['phase']='runtime_prepared';self.write('state.json',state)

    def runtime_validation(self):
        state=self.state();accounts=self.accounts()
        if accounts!=state['created_account']:raise ValueError('created NTP account or GPSD identities drift')
        hardware=self.hardware_gate()['hardware']
        if (hardware['uart_uid']!=0 or hardware['uart_gid']!=accounts['groups']['dialout']['gid']
                or hardware['uart_mode'] & 0o060 != 0o060 or hardware['uart_mode'] & 0o002):
            raise ValueError('observed UART dialout access required')
        if self.snapshot_file(Path(self.recipe['cache_path']))!=state['cache_after']:
            raise ValueError('post-refresh library cache drift')
        cache=self.run(['/usr/sbin/ldconfig','-p'])
        if not any('libgps.so.32' in l and '/usr/local/lib/libgps.so.32' in l for l in cache.splitlines()):
            raise ValueError('native libgps cache entry required')
        for binary in ('gpsd','ntpd'):
            self.run(['/usr/local/sbin/'+binary,'--version'])
        root=self.recipe['python_modules_root']
        code=('import importlib,json,pathlib,sys\nroot=pathlib.Path('+repr(root)+')\n'
              'result={}\nfor name in sys.argv[1:]:\n m=importlib.import_module(name)\n'
              ' p=pathlib.Path(m.__file__).resolve()\n assert p.is_relative_to(root),(name,str(p))\n'
              ' result[name]=str(p)\nprint(json.dumps(result,sort_keys=True))\n')
        # GPSD/client files remain root-only in the accepted release; no chmod broadening.
        self.run(['/usr/bin/python3','-I','-B','-c',code,'gps','gps.client','ntp.packet','ntp.ntpc'])
        account=accounts['users']['ntp']
        identity_code=('import os\nassert (os.getuid(),os.getgid())=='+repr((account['uid'],account['gid']))+'\n')
        self.run(['/usr/sbin/runuser','--user','ntp','--','/usr/bin/python3','-I','-B','-c',identity_code+code,'ntp.packet','ntp.ntpc'])
        self.run(['/usr/bin/systemd-analyze','verify',str(self.root/'timeservice.service')])
        validator=load_module(self.code_root,'timeservice.py',self.code_members['timeservice.py'],self.h)
        validator.validate(json.loads(self.h.read(self.root/'timeservice-candidate.json')))
        if self.h.read(self.root/'timeservice.service')!=self.h.read(self.root/'timeservice-template.service'):
            raise ValueError('rendered service candidate drift')

    def probe(self, recovery=False):
        state=self.state()
        if recovery:
            if state['phase'] not in ('recovery_reboot_submitted','recovered'):
                raise ValueError('recovery reboot required')
            if state['phase']=='recovery_reboot_submitted' and boot_id()==state['reboot_from_boot']:
                raise ValueError('recovery reboot not observed')
            self.network_checks()
            state.update(phase='recovered',recovered_boot_id=boot_id());self.write('state.json',state)
            return {'phase':'recovered','boot_id':boot_id()}
        if self.spec.get('schema')==3 and boot_id()!=self.spec['continuation']['candidate_boot_id']:
            raise ValueError('continuation candidate boot changed')
        allowed = ('acceptance_pending','accepted') if self.spec.get('schema')==3 else ('reboot_submitted','accepted') if self.spec['operation']=='hardware' else ('runtime_prepared','accepted')
        if state['phase'] not in allowed:raise ValueError('prepared configuration required')
        self.network_checks()
        if self.spec['operation']=='hardware':
            if boot_id()==self.spec['boot_id']:raise ValueError('new boot required')
            hardware=self.hardware_metadata();labels=HARDWARE_LABELS
        else:
            self.runtime_validation();hardware=self.hardware_gate()['hardware'];labels=RUNTIME_LABELS
        return {'phase':'ready','hostname':self.spec['hostname'],'boot_id':boot_id(),
                'spec_sha256':self.h.sha(encoded(self.spec)),'checks':dict.fromkeys(sorted(labels),True),'hardware':hardware}

    def accept(self, proofs):
        with self.core.lock():
            if self.state()['phase']=='accepted':raise ValueError('acceptance already consumed')
            endpoints={self.spec['recipe'][k].split('/')[0] for k in ('ipv4_address','ipv6_address')}
            current=self.probe()
            if (set(proofs)!=endpoints or any(p!=current or p['checks'].keys()!=current['checks'].keys()
                    or any(v is not True for v in p['checks'].values()) for p in proofs.values())):
                raise ValueError('matching bound dual-endpoint configuration proofs required')
            state=self.state();state.update(phase='accepted',accepted_boot_id=boot_id(),accepted_epoch=int(time.time()),checks=current['checks'],
                                           hardware=current['hardware'],ssh_proofs=proofs)
            self.write('state.json',state);return state

    def restore_file(self, path, before, allowed):
        current=self.snapshot_file(path)
        if current['uid']!=before['uid'] or current['gid']!=before['gid'] or current['mode']!=before['mode'] or current['sha256'] not in allowed:
            raise ValueError('unrelated file drift; recovery held: '+str(path))
        if current['sha256']!=before['sha256']:
            self.h.replace(path,base64.b64decode(before['base64'],validate=True),before['mode'])

    def recover(self):
        with self.core.lock():
            state=self.state()
            if state['phase']=='accepted':raise ValueError('accepted stage recovery needs a new review')
            if state['phase'] in ('recovered','recovery_files_restored','recovery_reboot_submitted'):
                return state
            before=self.before()
            if self.spec['operation']=='hardware':
                if 'boot_files' not in before:raise ValueError('no captured mutation before-state; inspect only')
                # Check BOTH files before restoring either, allowing a interrupted two-file update.
                for path,name in zip(BOOT_PATHS,('config-candidate.txt','cmdline-candidate.txt')):
                    actual=self.snapshot_file(Path(path));original=before['boot_files'][path]
                    if any(actual[k]!=original[k] for k in ('uid','gid','mode')) or actual['sha256'] not in (original['sha256'],self.spec['members'][name]):
                        raise ValueError('unrelated boot drift; recovery held')
                for path,name in zip(BOOT_PATHS,('config-candidate.txt','cmdline-candidate.txt')):
                    original=before['boot_files'][path]
                    self.restore_file(Path(path),original,{original['sha256'],self.spec['members'][name]})
                state.update(phase='recovered' if boot_id()==self.spec['boot_id'] else 'recovery_files_restored')
            else:
                accounts=self.accounts();created=state.get('created_account')
                if created is None and ('ntp' in accounts['users'] or 'ntp' in accounts['groups']):
                    raise ValueError('unrecorded account creation; preserve for inspection')
                if created is not None and accounts!=created:raise ValueError('account drift; recovery held')
                original=before['cache'];after=state.get('cache_after')
                if after is None and self.snapshot_file(Path(self.recipe['cache_path']))!=original:
                    raise ValueError('unrecorded cache refresh; preserve for inspection')
                if after is not None:
                    self.restore_file(Path(self.recipe['cache_path']),original,{original['sha256'],after['sha256']})
                if created is not None:
                    uid=created['users']['ntp']['uid']
                    for process in Path('/proc').glob('[0-9]*'):
                        try:owner=process.stat().st_uid
                        except FileNotFoundError:continue
                        if owner==uid:raise ValueError('NTP account has processes; recovery held')
                    self.run(['/usr/sbin/userdel','ntp'])
                    remaining=self.accounts()
                    if 'ntp' in remaining['groups']:self.run(['/usr/sbin/groupdel','ntp'])
                if self.accounts()!=before['accounts']:raise ValueError('account recovery incomplete')
                state['phase']='recovered'
            self.write('state.json',state);return state

    def cleanup(self):
        with self.core.lock():
            state=self.state()
            if state['phase'] not in ('accepted','recovered'):raise ValueError('terminal stage required')
            for suffix in ('','-recovery'):
                for kind in ('.timer','.service'):
                    unit='ntp-host-reboot-'+self.spec['operation_id']+suffix+kind
                    if self.run(['/usr/bin/systemctl','show','--property=LoadState','--value',unit]).strip()=='loaded':
                        self.run(['/usr/bin/systemctl','stop',unit]);self.run(['/usr/bin/systemctl','reset-failed',unit])
            state['transient_units_cleaned']=True;self.write('state.json',state);return state


@contextmanager
def source_guard(spec, files, helper):
    """Read the immutable source under its existing lock; never create or write it."""
    source=json.loads(files['source-spec.json']);root=Path(source['stage'])
    gate=spec['continuation']
    if (source['stage']!=gate['source_stage'] or root==Path(spec['stage'])
            or helper.sha(files['source-spec.json'])!=gate['source_spec_sha256']
            or not re.fullmatch('/var/lib/ntp-host-[a-z][a-z0-9-]{0,47}',str(root))):
        raise ValueError('bound original hardware stage required')
    helper.ancestors(root)
    if stat.S_IMODE(root.stat().st_mode)!=0o700:raise ValueError('private original stage required')
    fd=os.open(root/'.lock',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=helper.OWNER or info.st_gid!=helper.OWNER
                or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600):
            raise ValueError('protected original lock required')
        fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
        expected=set(source['members'])|{'spec.json','manifest.json','state.json','before.json','commands.jsonl','.lock'}
        if {p.name for p in root.iterdir()}!=expected:
            raise ValueError('original stage membership drift')
        for path in root.iterdir():
            if stat.S_IMODE(path.lstat().st_mode)!=0o600:raise ValueError('private original evidence required')
            helper.read(path,limit=8*1024**2)
        if (helper.read(root/'spec.json')!=files['source-spec.json']
                or json.loads(helper.read(root/'manifest.json'))!=source['members']):
            raise ValueError('original specification drift')
        for name,digest in source['members'].items():
            if helper.sha(helper.read(root/name,limit=2*1024**2))!=digest:
                raise ValueError('original member drift')
        report=json.loads(files['timing-result.json'])['report']
        for name,value in report['retained'].items():
            if helper.read(root/name,limit=8*1024**2)!=base64.b64decode(value,validate=True):
                raise ValueError('original retained state drift: '+name)
        if boot_id()!=gate['candidate_boot_id']:raise ValueError('continuation candidate boot changed')
        before=json.loads(base64.b64decode(report['retained']['before.json'],validate=True))
        for path,name in zip(BOOT_PATHS,('config-candidate.txt','cmdline-candidate.txt')):
            info=Path(path).lstat();original=before['boot_files'][path]
            if (helper.sha(helper.read(Path(path),limit=256*1024))!=source['members'][name]
                    or info.st_uid!=original['uid'] or info.st_gid!=original['gid']
                    or stat.S_IMODE(info.st_mode)!=original['mode']):
                raise ValueError('candidate boot file content/ownership drift')
        yield before
    finally:
        os.close(fd)


def acceptance_entry(spec, files, mode, proofs, helper):
    if mode not in ACCEPTANCE_MODES:raise ValueError('acceptance-only worker mode required')
    root=Path(spec['stage'])
    if mode in ('readback','cleanup'):
        if helper.read(root/'foundation-install.py')!=files['foundation-install.py']:
            raise ValueError('protected helper drift before import')
        tx=Transaction(spec);tx.verify(files)
        if mode=='readback':return tx.state()
        with tx.core.lock():
            state=tx.state()
            state['evidence_closed']=True;tx.write('state.json',state);return state
    with source_guard(spec,files,helper) as before:
        if mode=='start':
            if not spec['prepared_epoch']-300<=time.time()<spec['expires_epoch']:
                raise ValueError('continuation execution window expired')
            helper.ancestors(root.parent);root.mkdir(mode=0o700);helper.sync(root.parent)
            initial={'phase':'acceptance_pending','boot_id':boot_id(),'source_stage':spec['continuation']['source_stage']}
            for name,data in {**files,'spec.json':encoded(spec),'manifest.json':encoded(spec['members']),
                              'state.json':encoded(initial),'before.json':encoded(before)}.items():
                if not re.fullmatch('[a-z][a-z0-9.-]+',name):raise ValueError('flat stage entries required')
                helper.create(root/name,data)
        elif helper.read(root/'foundation-install.py')!=files['foundation-install.py']:
            raise ValueError('protected helper drift before import')
        tx=Transaction(spec);tx.verify(files)
        if tx.state().get('evidence_closed'):raise ValueError('continuation evidence already closed')
        if mode=='start':return tx.state()
        if mode=='probe':return tx.probe()
        return tx.accept(proofs)


def entry(spec, files, mode, proofs=None, console_ready=False):
    if spec.get('schema')==3 and mode not in ACCEPTANCE_MODES:
        raise ValueError('acceptance-only worker mode required')
    identity(spec,initial=mode=='start' and spec['operation']=='hardware' and spec.get('schema')!=3)
    validate_recipe(spec['operation'],spec['host_recipe'])
    namespace={'__name__':'host_helper'}
    exec(compile(files['foundation-install.py'],'sealed-host-helper','exec'),namespace)
    helper=type('Helper',(),namespace)
    root=Path(spec['stage'])
    if set(files)!=set(spec['members']) or any(helper.sha(data)!=spec['members'][name] for name,data in files.items()):
        raise ValueError('sealed host configuration inputs required')
    if spec.get('schema')==3:
        return acceptance_entry(spec,files,mode,proofs,helper)
    if mode=='start':
        helper.ancestors(root.parent);root.mkdir(mode=0o700);helper.sync(root.parent)
        initial={'phase':'staged','boot_id':boot_id()}
        registry=dict(l.split(':',1) for l in json.loads(files['baseline.json'])['queries']['profile_registry']['stdout'].splitlines())
        for name,data in {**files,'spec.json':encoded(spec),'manifest.json':encoded(spec['members']),
                          'state.json':encoded(initial),'before.json':encoded({'registry':registry})}.items():
            if not re.fullmatch('[a-z][a-z0-9.-]+',name):raise ValueError('flat stage entries required')
            helper.create(root/name,data)
    else:
        if helper.read(root/'foundation-install.py')!=files['foundation-install.py']:
            raise ValueError('protected helper drift before import')
    tx=Transaction(spec);tx.verify(files)
    if spec['operation']=='runtime' and mode!='start' and tx.state()['boot_id']!=boot_id():
        raise ValueError('runtime prerequisite boot changed; inspect before continuing')
    if mode=='start':return tx.apply()
    if mode=='reboot':return tx.schedule_reboot(console_ready)
    if mode=='recovery-reboot':return tx.schedule_reboot(console_ready,recovery=True)
    if mode=='probe':return tx.probe()
    if mode=='verify-recovery':return tx.probe(recovery=True)
    if mode=='accept':return tx.accept(proofs)
    if mode=='readback':return tx.state()
    if mode=='recover':return tx.recover()
    if mode=='cleanup':return tx.cleanup()
    raise ValueError('closed host configuration mode required')


def console_inputs(root):
    """Use only the retained protected stage; this entry cannot stage or apply."""
    if not re.fullmatch('/var/lib/ntp-host-[a-z][a-z0-9-]{0,47}',str(root)):
        raise ValueError('exact retained root stage required')
    for parent in (root,*root.parents):
        info=parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid or info.st_gid or info.st_mode & 0o022:
            raise ValueError('protected console-stage ancestry required')
    if stat.S_IMODE(root.stat().st_mode)!=0o700:
        raise ValueError('private console root stage required')
    def read(name):
        if not re.fullmatch('[a-z][a-z0-9.-]+',name):raise ValueError('flat console inputs required')
        fd=os.open(root/name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            info=os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid or info.st_gid or info.st_nlink!=1
                    or stat.S_IMODE(info.st_mode)!=0o600 or info.st_size>2*1024**2):
                raise ValueError('protected bounded console input required')
            with os.fdopen(fd,'rb',closefd=False) as stream:data=stream.read(2*1024**2+1)
            if len(data)>2*1024**2:raise ValueError('console input exceeded bound')
            return data
        finally:os.close(fd)
    spec=json.loads(read('spec.json'))
    if spec['stage']!=str(root):raise ValueError('console root/spec mismatch')
    return spec,{name:read(name) for name in spec['members']}


def main():
    os.umask(0o077);parser=argparse.ArgumentParser(description='Console readback/recovery of an approved retained stage')
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--mode',choices=('readback','recover','recovery-reboot','verify-recovery','cleanup'),required=True)
    parser.add_argument('--console-ready',action='store_true')
    args=parser.parse_args();spec,files=console_inputs(args.root)
    if Path(__file__).absolute()!=args.root/'host-configuration-stage.py' or Path(__file__).read_bytes()!=files['host-configuration-stage.py']:
        raise ValueError('invoke only the exact sealed retained console worker')
    result=entry(spec,files,args.mode,console_ready=args.console_ready)
    print(json.dumps({'mode':args.mode,'phase':result['phase'],'target':spec['hostname'],
                      'state':str(args.root/'state.json')},sort_keys=True))


if __name__=='__main__':main()
