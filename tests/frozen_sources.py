"""Test-only source injection for legacy UI/transport tests, never production.
These contract fixtures stand in for metadata resolution, not live identities.
Actual resolver/hash/network failure cases are exercised in test_tool_sources.
"""
import copy
import hashlib
from functools import wraps
COMMIT='a'*40

def script(kind='ipq', body=b'#!/bin/sh\n# OFFLINE TEST ONLY\n'):
    repos={'ipq':('xykt/IPQuality','ip.sh'),'nq':('LloydAsp/NodeQuality','NodeQuality.sh'),
           'snell':('shui1iao/Snell-Manager','snell.sh')}
    repo,file=repos[kind]
    return {'repository':repo,'version':'offline-fixture','commit':COMMIT,
            'url':f'https://raw.githubusercontent.com/{repo}/{COMMIT}/{file}',
            'sha256':hashlib.sha256(body).hexdigest(),'source_offer':f'https://github.com/{repo}/tree/{COMMIT}'}

def tcp():
    base=f'https://raw.githubusercontent.com/ibsgss/TcpQuality/{COMMIT}'
    return {'repository':'ibsgss/TcpQuality','version':'offline-fixture','commit':COMMIT,
            'raw_base':base,'files':{n:{'url':base+'/'+n,'sha256':'b'*64} for n in ('runTcpQuality.sh','runTcpQuality-core.sh')}}

def gb():
    return {'version':'5.9.9','url':'https://cdn.geekbench.com/Geekbench-5.9.9-Linux.tar.gz','sha256':'b'*64}

def install(bot):
    """Only alter this independently imported test bot, not tool_sources globals."""
    if getattr(bot,'_offline_sources_injected',False):return
    bot._offline_sources_injected=True
    async def resolve(jid,resolver,*args):
        name=resolver.__name__
        value=tcp() if name=='tcp_source' else gb() if name=='gb5_source' else script(*args)
        bot.JOBS[jid]['tool_source']=copy.deepcopy(value)
        return value
    bot.resolve_tool=resolve
    for name, factory in [('tcpquality_remote_command',tcp),('ipquality_remote_command',lambda:script('ipq')),
                          ('nodequality_remote_command',lambda:script('nq')),('gb5_remote_command',gb)]:
        original=getattr(bot,name)
        def wrap(original=original,name=name,factory=factory):
            @wraps(original)
            def call(*args,**kwargs):
                positional=(name=='tcpquality_remote_command' and len(args)>=2 or name=='gb5_remote_command' and len(args)>=1)
                if not positional:kwargs.setdefault('source',factory())
                return original(*args,**kwargs)
            return call
        setattr(bot,name,wrap())
