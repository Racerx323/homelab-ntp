#!/usr/bin/env bash
# Read-only node health evidence. The attended review evaluates the output.
set -Eeuo pipefail
export LC_ALL=C PATH=/usr/sbin:/usr/bin:/sbin:/bin
hostname
cat /proc/sys/kernel/random/boot_id
uname -r
date -Iseconds
/usr/bin/systemctl --no-pager show --property=Id,LoadState,ActiveState,SubState,MainPID,InvocationID,NRestarts timeservice.service gpsd.service munin-node.service cron.service rpi-eeprom-update.service
/usr/bin/systemctl --no-pager status timeservice.service
/usr/local/bin/ntpq -n -c 'rv 0' -c peers
/usr/sbin/ip -j address show
/usr/sbin/ip -j route show
/usr/sbin/ip -6 -j route show
/usr/bin/ss -H -lnup
/usr/bin/ps -eo pid,ppid,comm
/usr/bin/find /proc/1/fd -maxdepth 1 -type l -lname '*watchdog*' -printf '%f %l\n'
/usr/bin/systemctl show --property=RuntimeWatchdogUSec,RebootWatchdogUSec
cat /sys/class/watchdog/watchdog0/identity /sys/class/watchdog/watchdog0/state /sys/class/watchdog/watchdog0/timeout
cat /sys/class/thermal/thermal_zone0/temp
/usr/bin/journalctl -b -p err --no-pager -n 200
/usr/bin/journalctl -b -u timeservice.service -u munin-node.service --no-pager -n 100
/usr/bin/systemctl --no-pager --all list-timers
/usr/bin/dpkg --audit
df -B1 / /boot/firmware
df -i /
