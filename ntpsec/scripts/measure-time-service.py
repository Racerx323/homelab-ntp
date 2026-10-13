#!/usr/bin/python3
"""Bounded localhost control queries using the accepted native NTPsec client."""
import json
import ntp.packet


def measure():
    session=ntp.packet.ControlSession()
    session.primary_timeout=2000;session.secondary_timeout=1000
    session.openhost('127.0.0.1')
    system=dict(session.readvar(0,['leap','stratum','refid','offset','rootdelay','rootdisp','frequency']))
    associations=session.readstat()
    if len(associations)>8:raise ValueError('association bound exceeded')
    peers=[]
    for peer in associations:
        values=dict(session.readvar(peer.associd,['srcadr','srchost','reach','offset','jitter','ntscookies','refid']))
        peers.append({'associd':peer.associd,'status':peer.status,'variables':values})
    return {'system':system,'peers':peers}


if __name__=='__main__':print(json.dumps(measure(),sort_keys=True))
