#!/usr/bin/env python3
"""Read-only identity check. Optional short, real worker lifecycle smoke test."""
from __future__ import annotations
import argparse
import datetime
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ownership.__main__ import load_env
from ownership.telegram import TelegramClient, TelegramError, UncertainDelivery
from ownership.core import Store
from ownership.health import Health

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--env',default='.env');p.add_argument('--worker-smoke',action='store_true');a=p.parse_args()
    load_env(a.env);client=TelegramClient(os.environ['BOT_TOKEN']);owners=tuple(int(x) for x in os.environ['SUPER_ADMIN_IDS'].split(','));owner=int(os.environ['OWNER_TG_ID'])
    report={'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'failed','kind':'Live Telegram Bot API identity and metadata check','human_client_flows':'not_run'}
    try:
        me=client.call('getMe');hook=client.call('getWebhookInfo');commands=client.call('getMyCommands');name=client.call('getMyName')
        report.update(id=me['id'],username=me['username'],name=name['name'],privacy_enabled=not me.get('can_read_all_group_messages',False),can_join_groups=bool(me.get('can_join_groups')),webhook_present=bool(hook.get('url')),pending_updates=hook.get('pending_update_count'),commands=[c['command'] for c in commands],command_descriptions={c['command']:c['description'] for c in commands},configured_superadmins=list(owners))
        assert commands and not re.search(r'[\u0600-\u06ff]',json.dumps(commands,ensure_ascii=False)),'Non-English command menu'
        report['command_menu_language']='en'
        expected=os.environ.get('BOT_USERNAME','FutarchistBot');assert report['username'].lower()==expected.lower(),'Bot identity mismatch'
        report['scope_menus']={}
        for uid in owners:
            try:
                menu=client.call('getMyCommands',{'scope':{'type':'chat','chat_id':uid}});report['scope_menus'][str(uid)]='configured' if any(c['command']=='manage' for c in menu) else 'configure_after_first_start'
            except TelegramError as e:
                if e.code!=400:raise
                report['scope_menus'][str(uid)]='configure_after_first_start'
        report['status']='passed'
        if a.worker_smoke:
            if hook.get('url') or hook.get('pending_update_count',0):raise ValueError('Worker smoke requires no webhook and no pending updates')
            # Normal bot operation for a bounded interval. No synthetic live messages.
            # A person who voluntarily starts the bot during this window gets its normal reply.
            with tempfile.TemporaryDirectory(prefix='futarchist-live-smoke-') as temp:
                path=Path(temp)/'smoke.sqlite3'
                process=subprocess.Popen([sys.executable,'-m','futarchist','--env',str(Path(a.env).resolve()),'--mode','bot','--database',str(path)],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                time.sleep(32)
                try:
                    if process.poll() is not None:raise ValueError('Worker exited during smoke test')
                    store=Store(path,owner,super_admin_ids=owners)
                    try:
                        with store.tx():
                            snap=Health(store).snapshot(owner);delivered=store.one("SELECT COUNT(*) n FROM outbox WHERE state='sent'")['n'];pending=store.one('SELECT COUNT(*) n FROM inbox')['n']
                        components={key:value['state'] for key,value in snap['checks'].items() if key in ('poller','inbox','outbox','maintenance','database','references')}
                        report['worker_smoke']={'seconds':32,'components':components,'received_updates':pending,'delivered_messages':delivered,'status':'passed' if all(v=='ok' for v in components.values()) and 'poller' in components else 'failed'}
                    finally:store.close()
                finally:
                    process.terminate()
                    try:process.communicate(timeout=35)
                    except subprocess.TimeoutExpired:process.kill();process.communicate()
                if report['worker_smoke']['status']!='passed':report['status']='failed'
    except (TelegramError,UncertainDelivery,ValueError,AssertionError):report['status']='failed';report['error']='Live check incomplete. Token and network error details are intentionally omitted.'
    directory=ROOT/'reports';directory.mkdir(exist_ok=True);(directory/'live-telegram.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False));return int(report['status']!='passed')

if __name__=='__main__':raise SystemExit(main())
