#!/usr/bin/python3
"""Bounded localhost control queries using the accepted native NTPsec client."""
import json
import sys
import ntp.packet

COUNTERS=['nts_client_send','nts_client_recv_good','nts_client_recv_bad',
          'ss_received','ss_badformat','ss_badauth','ss_declined','ss_restricted','ss_processed']


def measure(diagnostic=False):
    session=ntp.packet.ControlSession()
    session.primary_timeout=2000;session.secondary_timeout=1000
    session.openhost('127.0.0.1')
    system=dict(session.readvar(0,['leap','stratum','refid','offset','rootdelay','rootdisp','frequency']))
    associations=session.readstat()
    if len(associations)>8:raise ValueError('association bound exceeded')
    peers=[]
    for peer in associations:
        names=['srcadr','srchost','reach','offset','jitter','ntscookies','refid']
        if diagnostic:names+=['dstadr','flash','sent','received']
        values=dict(session.readvar(peer.associd,names))
        if diagnostic and not {'dstadr','flash','sent','received'}.issubset(values):
            raise ValueError('complete peer diagnostic fields required')
        peers.append({'associd':peer.associd,'status':peer.status,'variables':values})
    result={'system':system,'peers':peers}
    if diagnostic:
        counters=dict(session.readvar(0,COUNTERS))
        if set(counters)!=set(COUNTERS) or any(not isinstance(v,int) or v<0 for v in counters.values()):
            raise ValueError('complete nonnegative diagnostic counters required')
        result['counters']=counters
    return result


if __name__=='__main__':
    if sys.argv[1:] not in ([],['--diagnostic']):raise SystemExit('closed measurement arguments')
    print(json.dumps(measure(bool(sys.argv[1:])),sort_keys=True))
