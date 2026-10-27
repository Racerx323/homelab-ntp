#!/usr/bin/python3
"""Validate native busctl Conditions JSON; no service or filesystem mutation."""
import json
import sys

MARKER = '/var/lib/ntp-maintenance/eeprom-inhibit'


def validate(value, inhibited):
    if not isinstance(value, dict) or value.get('type') != 'a(sbbsi)':
        raise ValueError('native Conditions signature missing')
    rows = value.get('data')
    if not isinstance(rows, list):
        raise ValueError('native Conditions array missing')
    for row in rows:
        if not (isinstance(row, list) and len(row) == 5 and
                isinstance(row[0], str) and type(row[1]) is bool and
                type(row[2]) is bool and isinstance(row[3], str) and
                type(row[4]) is int and row[4] in (-1, 0, 1)):
            raise ValueError('malformed native condition')
    matches = [row for row in rows if row[3] == MARKER]
    if inhibited:
        if len(matches) != 1 or matches[0][:4] != ['ConditionPathExists', False, True, MARKER]:
            raise ValueError('required non-trigger negated marker condition missing/ambiguous')
    elif matches:
        raise ValueError('maintenance condition remains')
    # The fifth field is a cached evaluation, not proof of current marker presence.
    return {'condition_policy_verified': True, 'inhibited': inhibited,
            'current_marker_or_service_skip_proven': False}


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ('inhibited', 'restored'):
        raise SystemExit('usage: check-maintenance-conditions.py inhibited|restored < busctl.json')
    print(json.dumps(validate(json.load(sys.stdin), sys.argv[1] == 'inhibited')))
