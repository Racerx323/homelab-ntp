"""Filesystem-only simulation for the real UART/PPS/RTC acceptance checkers."""
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import tempfile
from types import SimpleNamespace
from unittest.mock import patch


class HardwareTree:
    def __init__(self, stack, host):
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.host = host
        tree = self
        class VirtualPath(type(Path())):
            def real(self): return tree.root/str(self).lstrip('/')
            def open(self, *args, **kwargs): return self.real().open(*args, **kwargs)
            def stat(self, *, follow_symlinks=True):
                info = self.real().stat(follow_symlinks=follow_symlinks)
                if str(self) in tree.devices:
                    mode, major, minor = tree.devices[str(self)]
                    return SimpleNamespace(st_mode=mode, st_rdev=os.makedev(major, minor), st_uid=0, st_gid=20)
                return SimpleNamespace(st_mode=info.st_mode, st_uid=0, st_gid=info.st_gid)
            def lstat(self): return self.stat(follow_symlinks=False)
            def resolve(self, strict=False):
                return VirtualPath('/')/self.real().resolve(strict=strict).relative_to(tree.root)
            def glob(self, pattern):
                return (VirtualPath('/')/p.relative_to(tree.root) for p in self.real().glob(pattern))
            def iterdir(self):
                return (VirtualPath('/')/p.relative_to(tree.root) for p in self.real().iterdir())
        self.Path = VirtualPath
        self.devices = {'/dev/ttyAMA0': (stat.S_IFCHR|0o660, 204, 64),
                        '/dev/pps0': (stat.S_IFCHR|0o660, 249, 0),
                        '/dev/rtc0': (stat.S_IFCHR|0o660, 251, 0)}
        for path in self.devices: self.put(path, b'')
        self.link('/dev/serial0', '/dev/ttyAMA0')
        self.link('/sys/class/tty/ttyAMA0', '/sys/devices/platform/uart/tty/ttyAMA0')
        self.mkdir('/sys/devices/platform/uart/tty/ttyAMA0')
        self.mkdir('/sys/bus/amba/drivers/uart-pl011')
        self.link('/sys/devices/platform/uart/driver', '/sys/bus/amba/drivers/uart-pl011')
        self.link('/sys/devices/platform/uart/subsystem', '/sys/bus/amba')
        self.link('/sys/devices/platform/uart/of_node', '/sys/firmware/devicetree/base/uart')
        self.link('/sys/bus/amba/devices/uart', '/sys/devices/platform/uart')
        self.put('/sys/firmware/devicetree/base/uart/compatible', b'arm,pl011\0')
        self.mkdir('/sys/bus/platform/drivers/pps-gpio')
        self.link('/sys/bus/platform/drivers/pps-gpio/pps@12', '/sys/devices/platform/pps@12')
        self.link('/sys/devices/platform/pps@12/driver', '/sys/bus/platform/drivers/pps-gpio')
        self.link('/sys/devices/platform/pps@12/subsystem', '/sys/bus/platform')
        self.link('/sys/devices/platform/pps@12/of_node', '/sys/firmware/devicetree/base/pps@12')
        self.put('/sys/firmware/devicetree/base/pps@12/compatible', b'pps-gpio\0')
        self.put('/sys/firmware/devicetree/base/pps@12/gpios', struct.pack('>III', 7, 18, 0))
        gpio='/sys/firmware/devicetree/base/soc/gpio@7e200000/'
        self.put(gpio+'compatible', b'brcm,bcm2711-gpio\0'); self.put(gpio+'phandle', struct.pack('>I', 7))
        self.add_class('pps0', 'pps@12.-1', '249:0')
        self.link('/sys/class/rtc/rtc0', '/sys/devices/platform/i2c/1-0052/rtc/rtc0')
        self.put('/sys/devices/platform/i2c/1-0052/rtc/rtc0/name', b'rv3028')
        self.link('/sys/devices/platform/i2c/1-0052/rtc/rtc0/device', '/sys/devices/platform/i2c/1-0052')
        self.link('/sys/devices/platform/i2c/1-0052/of_node', '/sys/firmware/devicetree/base/rtc')
        self.put('/sys/firmware/devicetree/base/rtc/compatible', b'microcrystal,rv3028\0')
        stack.enter_context(patch.object(host, 'Path', VirtualPath))
        stack.enter_context(patch.object(host, 'boot_id', return_value='current-boot'))
        stack.enter_context(patch.object(host.uart_ancestry, '__defaults__', (VirtualPath('/sys'), None)))
        stack.enter_context(patch.object(host.pl011_parent, '__defaults__', (VirtualPath('/sys'),)))
        pps = host.gpio_pps_metadata
        stack.enter_context(patch.dict(pps.__globals__, Path=VirtualPath))
        stack.enter_context(patch.object(pps, '__defaults__', (VirtualPath('/sys'), VirtualPath('/dev'), None)))

    def mkdir(self, name): (self.root/name.lstrip('/')).mkdir(parents=True, exist_ok=True)
    def put(self, name, raw):
        p=self.root/name.lstrip('/'); p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw)
    def link(self, name, target):
        p=self.root/name.lstrip('/'); p.parent.mkdir(parents=True, exist_ok=True)
        p.symlink_to(self.root/target.lstrip('/'))
    def add_class(self, unit='pps1', name='serial PPS', device='249:1'):
        self.put('/sys/devices/virtual/pps/'+unit+'/name', name.encode())
        self.put('/sys/devices/virtual/pps/'+unit+'/dev', device.encode())
        self.link('/sys/class/pps/'+unit, '/sys/devices/virtual/pps/'+unit)
    def remove_class(self, unit='pps1'): (self.root/'sys/class/pps'/unit).unlink()

    def bind(self, tx):
        """Produce immutable accepted baseline using the actual checker, before startup."""
        state = {'created_account': {}, 'cache_after': {}}
        tx.recipe = {'uart_alias': '/dev/serial0', 'uart_driver': 'uart-pl011', 'rtc_compatible': 'microcrystal,rv3028'}
        tx.state = lambda: copy.deepcopy(state)
        tx.write = lambda name, value: state.update(copy.deepcopy(value))
        actual = self.host.Transaction.hardware_metadata(tx)
        raw = (json.dumps({'host_recipe': tx.recipe})+'\n').encode()
        sha = lambda b: hashlib.sha256(b).hexdigest()
        accepted = {'phase': 'accepted', 'accepted_boot_id': 'current-boot', 'accepted_epoch': 1,
                    'checks': dict.fromkeys(self.host.HARDWARE_LABELS, True), 'hardware': actual}
        gate = {'stage': '/hardware', 'spec_sha256': sha(raw), 'bundle_sha256': 'bound', 'boot_hashes': {}}
        tx.spec.setdefault('hardware_prerequisite', {}).update(gate)
        tx.root = Path('/runtime')
        receipt = {'spec_sha256': sha(raw), 'bundle_sha256': 'bound', 'boot_id': 'current-boot',
                   'checks': accepted['checks'], 'hardware': actual}
        data = {'/hardware/spec.json': raw, '/hardware/state.json': json.dumps(accepted).encode(),
                '/runtime/hardware-cleanup.json': json.dumps({'bundle_sha256': 'bound', 'result': accepted}).encode(),
                '/runtime/hardware-acceptance.json': json.dumps(receipt).encode()}
        tx.h = SimpleNamespace(read=lambda path, **kw: data[str(path)], sha=sha)
        return accepted, data
