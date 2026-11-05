"""Kat contract regressions. Test SOURCE only in this change; NOT executed.

In-memory bounded transport fixtures, no SSH/Telegram/Manager/kernel/network.
These are protocol fixtures, never presented as live fleet evidence.
"""
import ast
import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import kat_proxy as k


def frame(items):
    return k.HEAD + ''.join('KAT_RECORD '+typ+' '+name.encode().hex()+'\n'+data.hex()+'\nKAT_END\n'
                           for (typ,name),data in items.items()) + k.TAIL


def encode(value):
    return json.dumps(value,separators=(',',':')).encode()


def inbound(kind, port=443):
    if kind=='ss':
        return {'protocol':'shadowsocks','listen':'0.0.0.0:'+str(port),
                'ss':{'method':'2022-blake3-aes-128-gcm','key':base64.b64encode(b'x'*16).decode()}}
    return {'protocol':'anytls','listen':'[::]:'+str(port),'anytls':{'password':'test/@secret'}}


def fixture(kind='anytls', state='active', extra=False):
    digest='a'*64
    core={'version':'0.7.1','sha256':digest,'source':'release'}
    notfound=b'Id=none.service\nLoadState=not-found\nActiveState=inactive\nMainPID=0\nUnitFileState=\n'
    r={('binary','kat'):digest.encode(),('kernel','kat'):encode(core)}
    for old in k.KINDS:
        r['legacy',old]=notfound;r['legacy_trace',old]=b'0'
    names=['kat-'+kind+'.service']+(['kat-'+kind+'-taipei101.service'] if extra else [])
    configs={}
    for i,name in enumerate(names):
        path='/etc/kat/'+kind+('' if i==0 else '-second')+'.json'
        argv='/usr/local/bin/kat run '+path
        props={'Id':name,'LoadState':'loaded','ActiveState':state,'SubState':'running' if state=='active' else 'dead',
               'MainPID':str(101+i) if state=='active' else '0','FragmentPath':'/etc/systemd/system/'+name,
               'DropInPaths':'','NeedDaemonReload':'no','UnitFileState':'enabled',
               'ExecStart':'{ path=/usr/local/bin/kat ; argv[]='+argv+' ; ignore_errors=no ; pid=0 }'}
        r['unit',name]='\n'.join(key+'='+value for key,value in props.items()).encode()
        marks='# KatManagerSHA256='+digest+'\n'
        if kind=='anytls':marks+='# KatManagerTLS=random-insecure\n'
        r['unitfile',name]=(marks+'[Service]\nExecStart='+argv+'\n').encode()
        if state=='active':
            r['cmdline',name]=b'\0'.join(v.encode() for v in argv.split())+b'\0'
            r['cgroup',name]=('0::/system.slice/'+name+'\n').encode().hex().encode()
        r['configpath',path]=path.encode()
        configs[path]={'inbounds':[inbound(kind,443+i)],'limits':{}}
    raw=frame(r);plan=k.discovery(raw)
    packet=dict(r)
    packet.update({('config',path):encode(data) for path,data in configs.items()})
    return plan,packet,configs


class KatContractTests(unittest.TestCase):
    def test_all_same_protocol_inbounds_and_second_service_are_independent(self):
        plan,packet,configs=fixture(extra=True)
        path=next(iter(configs));configs[path]['inbounds'].append(inbound('anytls',8443))
        packet['config',path]=encode(configs[path])
        nodes=k.parse_nodes('anytls',plan,frame(packet))
        self.assertEqual(len(nodes),3)
        self.assertEqual({n['port'] for n in nodes},{443,444,8443})
        text,complete=k.render('anytls','2001:db8::1',nodes)
        self.assertTrue(complete);self.assertEqual(text.count('Surge:'),3)
        self.assertIn('taipei101',text)
        self.assertIn('test%2F%40secret@',text)
        self.assertIn('"udp":true',text)
        self.assertIn('未验证连接/当前生效凭据',text)

    def test_ss2022_exact_key_and_2017_password_not_mixed(self):
        plan,packet,configs=fixture('ss')
        nodes=k.parse_nodes('ss',plan,frame(packet))
        output,_=k.render('ss','example.invalid',nodes)
        self.assertIn('ss://2022-blake3-aes-128-gcm:',output)
        self.assertEqual(nodes[0]['password'],base64.b64encode(b'x'*16).decode())
        path=next(iter(configs));configs[path]['inbounds'][0]['ss']['password']='wrong'
        packet['config',path]=encode(configs[path])
        with self.assertRaises(k.KatError):k.parse_nodes('ss',plan,frame(packet))

    def test_nonempty_users_and_malformed_credentials_fail_closed(self):
        for kind in k.KINDS:
            plan,packet,configs=fixture(kind);path=next(iter(configs))
            configs[path]['inbounds'][0]['users']=[{'password':'do-not-leak'}]
            packet['config',path]=encode(configs[path])
            with self.assertRaises(k.KatError) as result:k.parse_nodes(kind,plan,frame(packet))
            self.assertNotIn('do-not-leak',str(result.exception))
        plan,packet,configs=fixture('ss');path=next(iter(configs))
        configs[path]['inbounds'][0]['ss']['key']='invalid-key'
        packet['config',path]=encode(configs[path])
        with self.assertRaises(k.KatError):k.parse_nodes('ss',plan,frame(packet))

    def test_tls_missing_is_not_null_and_unknown_tls_is_not_forced_insecure(self):
        plan,packet,configs=fixture();path=next(iter(configs))
        configs[path]['inbounds'][0]['tls']=None;packet['config',path]=encode(configs[path])
        with self.assertRaises(k.KatError):k.parse_nodes('anytls',plan,frame(packet))
        plan,packet,configs=fixture();path=next(iter(configs))
        owner=plan['instances'][0];owner['markers'].pop('TLS')
        configs[path]['inbounds'][0]['tls']={'acme':{'domains':['example.invalid']}}
        packet['config',path]=encode(configs[path])
        nodes=k.parse_nodes('anytls',plan,frame(packet));out,complete=k.render('anytls','example.invalid',nodes)
        self.assertFalse(complete);self.assertIn('unsupported',out)
        self.assertNotIn('Surge:',out);self.assertNotIn('insecure=1',out)

    def test_old_inactive_residue_does_not_replace_kat_but_active_old_refuses(self):
        plan,packet,_=fixture();plan['legacy']['anytls']['trace']=True
        self.assertEqual(len(k.parse_nodes('anytls',plan,frame(packet))),1)
        plan['legacy']['anytls']['conflict']=True
        with self.assertRaises(k.KatError):k.parse_nodes('anytls',plan,frame(packet))

    def test_orphan_target_config_is_not_absent(self):
        plan,packet,configs=fixture()
        plan['instances']=[]
        with self.assertRaises(k.KatError):k.parse_nodes('anytls',plan,frame(packet))

    def test_inactive_is_installed_not_started(self):
        plan,packet,_=fixture(state='inactive')
        nodes=k.parse_nodes('anytls',plan,frame(packet))
        self.assertEqual(nodes[0]['state'],'inactive')
        self.assertNotIn('enable',k.collector_command())

    def test_snapshot_schema_truncation_extra_record_duplicate_json_and_controls(self):
        plan,packet,configs=fixture();path=next(iter(configs))
        for raw in (frame(packet)[:-4],frame(packet)+'extra',k.HEAD+'KAT_RECORD config 61\nff\nKAT_END\n'+k.TAIL):
            with self.assertRaises(k.KatError):k.parse_nodes('anytls',plan,raw)
        for raw in (b'{"inbounds":[],"inbounds":[]}', b'{"inbounds":NaN}',b'\xff'):
            with self.assertRaises(k.KatError):k.loads(raw)
        packet['extra','bad']=b'do-not-leak'
        with self.assertRaises(k.KatError) as result:k.parse_nodes('anytls',plan,frame(packet))
        self.assertNotIn('do-not-leak',str(result.exception))

    def test_collector_no_remote_python_manager_api_write_or_unbounded_file(self):
        command=k.collector_command()
        for forbidden in ('python3','jq ', 'curl ', 'mktemp ', 'chmod ', 'daemon-reload', ' restart ', 'kat check','kat.sh','eval ','source '):
            self.assertNotIn(forbidden,command)
        for required in ('/proc/', 'cgroup','MainPID','NeedDaemonReload','DropInPaths','od -An -v -tx1 -N 1048577','-le 8192'):
            self.assertIn(required,command)

    def test_install_only_frozen_set_reuses_core_never_updates_or_bootstraps(self):
        plan,packet,_=fixture();k.parse_nodes('anytls',plan,frame(packet))
        source={'files':{name:{'url':'https://raw.githubusercontent.com/shui1iao/Kat-Manager/'+'b'*40+'/'+name,'sha256':'c'*64}
                         for name in ('kat.sh','kat_manager.py','kat_config.py')},
                'server':{'mode':'reuse','version':'0.7.1','sha256':'a'*64}}
        command=k.install_command('ss','example.invalid','12345',plan,source)
        self.assertIn('install ss --host example.invalid --port 12345 --binary /usr/local/bin/kat --sha256 '+('a'*64)+' --version 0.7.1',command)
        self.assertIn('--help',command)
        self.assertIn(plan['digest'],command)
        self.assertIn('python3',k.preflight_command())
        for forbidden in ('apt-get','apk add',' update ', '/usr/local/bin/kat run'):
            # The final install command has no direct Kat execution; Manager
            # alone performs its authorized new-install self-check/start.
            self.assertNotIn(forbidden,command)

    def test_vless_live_surface_removed_history_retained(self):
        source=(ROOT/'telegram-bot/bot.py').read_text();tree=ast.parse(source)
        assignment=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PROXY_TOOLS' for t in n.targets))
        self.assertEqual(set(ast.literal_eval(assignment.value)),{'ss','anytls','snell'})
        self.assertIn('VLESS入口已移除',source)
        self.assertIn("'vless': 'VLESS（历史）'",source)
        start=source.index("    elif data.startswith(('proxy:vless:'")
        end=source.index("    elif data.startswith('katinstall:')",start)
        for forbidden in ('launch_job','ssh_args','resolve_tool'):
            self.assertNotIn(forbidden,source[start:end])
        from proxy_nodes import render_snapshot,ProxyReadError
        with self.assertRaises(ProxyReadError):render_snapshot('vless','example.invalid',{})


if __name__=='__main__':unittest.main()
