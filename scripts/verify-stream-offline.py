#!/usr/bin/env python3
"""Actual bot pipeline/PNG engine with mocked SSH/TG; run with --network none.
Never calls polling, inventory APIs, managed servers, or Telegram. Artifacts are
explicit OFFLINE MOCK; a marker is added outside the measured frame for preview.
"""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--app-root',default=str(ROOT));args=p.parse_args()
APP=Path(args.app_root);OUT=Path(args.output);OUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(APP))
os.environ.setdefault('BOT_TOKEN','123456:test-token');os.environ.setdefault('ALLOWED_USERS','1')
import stream_unified as u
spec=importlib.util.spec_from_file_location('guko_offline_preview',APP/('bot.py' if (APP/'bot.py').exists() else 'telegram-bot/bot.py'))
bot=importlib.util.module_from_spec(spec);spec.loader.exec_module(bot)

async def main():
    metadata=[];original_render=bot.render_ansi_png;original_process=bot.run_ansi_subprocess
    for name,total in [('jp',67),('global-failed',41),('sea',52),('eu',71),('na',78),('jp-denied',67)]:
        raw=(ROOT/'tests/fixtures/unified'/(name+'.json')).read_text();report,terminal,unknown=u.validate_output(raw,1)
        assert sum(len(report[k]) for k in ('results','services','ai_endpoints','extra_checks'))==total
        folder=OUT/name;folder.mkdir(exist_ok=True)
        metrics=[]
        async def capture_process(*a,**kw):
            code,text=await original_process(*a,**kw)
            if code==0:
                m=json.loads(text);assert m['networkRequests']==0 and m['contentsPreserved'];metrics.append(m)
            return code,text
        async def render(text,dest,kind):
            assert text==terminal and kind=='stream'
            await original_render('OFFLINE MOCK - NOT REAL MEASUREMENT\n'+text,dest,kind=kind)
        api=SimpleNamespace(send_photo=AsyncMock(),send_message=AsyncMock())
        server={'id':'offline-'+name,'name':'OFFLINE MOCK '+name,'host':'not-a-real-server.invalid','country':'us'}
        job={'kind':'stream','status':'running','server':server['name'],'server_id':server['id'],'started_at':bot.iso_now()}
        with patch.dict(bot.JOBS,{'offline':job},clear=True),patch.object(bot,'kind_result_dir',return_value=folder),patch.object(bot,'HISTORY_JSON',folder/'history.json'),patch.object(u,'remote_run',new=AsyncMock(return_value=(1,raw,'OFFLINE MOCK stderr',None))) as remote,patch.object(bot,'render_ansi_png',side_effect=render),patch.object(bot,'run_ansi_subprocess',side_effect=capture_process):
            await bot.run_stream_task(api,1,server,'offline')
            remote.assert_awaited_once();assert remote.call_args.kwargs=={'family':'auto'}
            api.send_photo.assert_awaited_once();api.send_message.assert_not_awaited()
            result=bot.JOBS['offline'];assert result['status']=='inconclusive' and result['exit_code']==1
            assert len(result['media_paths'])==1 and 'supplement' not in result
            assert json.loads(Path(result['json_path']).read_text())==report
            assert Path(result['raw_path']).read_text()==terminal
            assert len(bot.load_history())==1
            image=Path(result['media_paths'][0]);assert image.is_file() and metrics
            m=metrics[0];assert m['width']+m['height']<=10000 and max(m['width']/m['height'],m['height']/m['width'])<=20 and m['bytes']<10000000
            assert hashlib.sha256(image.read_bytes()).hexdigest()==m['sha256']
            entry={'fixture':name,'rows':total,'unknowns':unknown,'resolved_region':report['selection']['region'],'detected_country':report['selection'].get('detected_country'),'one_photo':True,'same_report_json_ansi':True,'history_single_path':True,'remote_mock_calls':1,'actual_ssh_or_tg_calls':0,'png':str(image.relative_to(OUT)),'metrics':m,'caption':api.send_photo.call_args.kwargs['caption']}
            metadata.append(entry)
            (folder/'machine.json').write_text(raw)
            (folder/'preview.ansi.txt').write_text('OFFLINE MOCK - NOT REAL MEASUREMENT\n'+terminal)
    (OUT/'offline-integration.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
    print(json.dumps([{'fixture':m['fixture'],'rows':m['rows'],'png':m['png'],'networkRequests':m['metrics']['networkRequests'],'contentsPreserved':m['metrics']['contentsPreserved']} for m in metadata],indent=2))
asyncio.run(main())
