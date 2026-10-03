from __future__ import annotations
import argparse
import fcntl
import logging
import os
import re
import signal
import threading
from pathlib import Path
from urllib.parse import urlsplit
from .bot import Bot
from .core import Store, PERMISSIONS
from .forms import split_answers
from .health import Health
from .server import AppServer
from .service import Service
from .simulator import FakeTelegram
from .telegram import Engine, TelegramClient, TelegramError, UncertainDelivery

log=logging.getLogger('futarchist')

def load_env(path):
    if not Path(path).exists():return
    for line in Path(path).read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        key,sep,value=line.partition('=')
        if not sep or not re.fullmatch(r'[A-Z][A-Z0-9_]*',key):raise ValueError('Invalid .env line')
        if value.startswith(('"',"'")) and value[-1:]==value[:1]:value=value[1:-1]
        os.environ.setdefault(key,value)

def demo_seed(s):
    with s.tx():
        if s.one("SELECT value FROM settings WHERE key='demo_seeded'"):return
        s.add_admin(1,2,'Nima');s.add_admin(1,3,'Sara')
        team=s.team(1,'Programs and Raise Review')
        s.membership(1,team,2,list(PERMISSIONS));s.membership(1,team,3,['read_general'])
        s.register(101,'Mina',True);s.register(102,'Ali',True)
        s.db.execute('UPDATE users SET invites=1 WHERE id=101')
        route=s.route(2,team,'Sample team intake','both',2)
        answers={'name':'Lumen Games','categories':['gaming'],'motivation':'Games where players use the assets they own.','stage':'beta','network':'testnet','website':'https://example.com/demo','socials':'@lumen_team','raise_status':'unsuccessful','retry':'yes','platform':'MetaDAO','currency':'USDC','target_amount':'500000','raised_amount':'85000','metadao':'yes'}
        g,f=split_answers('both',answers,'Mina');s.activate(101,route['token']);pid=s.save_project(101,route['token'],g,f,'both')
        personal=s.one("SELECT id FROM spaces WHERE creator=1 AND kind='personal'")['id'];personal_route=s.default_route(1,personal)
        answers.update(name='Signal Markets',categories=['prediction','defi'],raise_status='planning',currency='USD',target_amount='200000',stage='building')
        g,f=split_answers('both',answers,'Ali');s.activate(102,personal_route['token']);s.save_project(102,personal_route['token'],g,f,'both')
        from .management import Management
        m=Management(s)
        event=m.save_event(2,team,{'title':'Team planning meeting','kind':'meeting','topic':'Gaming','timezone':'UTC','starts_at':'2026-10-10 18:00','description':'Sample test data'})
        m.link_event(2,event['id'],pid,'planned');m.save_task(2,team,{'title':'Review the beta Lumen','assignee':2,'project_id':pid,'due_at':'2026-10-09 12:00','timezone':'UTC'})
        s.db.execute("INSERT INTO settings VALUES('demo_seeded','1')")

def configure_bot(client,owners):
    base=[{'command':c,'description':d} for c,d in [('start','Start and enter your access code'),('activate','Activate your contact\'s access code'),('projects','My projects and updates'),('resume','Resume a saved form'),('support','Support'),('id','Telegram ID'),('stop','Stop DM invitations')]]
    admin=[{'command':c,'description':d} for c,d in [('manage','Manage in Telegram'),('panel','Browser dashboard'),('code','Access codes'),('export','Export Excel and CSV'),('health','Health and troubleshooting'),('repair','Safe recovery')]]
    client.call('setMyCommands',{'commands':base})
    client.call('setMyName',{'name':'FUTARCHIST'})
    client.call('setMyShortDescription',{'short_description':'Project, team, raise and program management. Built by Ownership.'})
    client.call('setMyDescription',{'description':'FUTARCHIST manages project information, fundraising reviews, team workspaces, programs and follow-ups. Enter with an access code from your contact. Built by Ownership. Support: @sobix13 / @SrMessiSOL'})
    configured=[];pending=[]
    for uid in owners:
        try:client.call('setMyCommands',{'commands':admin+base,'scope':{'type':'chat','chat_id':uid}});configured.append(uid)
        except TelegramError as exc:
            if exc.code!=400:raise
            pending.append(uid)
    return {'configured':True,'superadmin_scopes':configured,'scope_setup_after_start':pending}

def main():
    parser=argparse.ArgumentParser(description='FUTARCHIST team and project management')
    parser.add_argument('--demo',action='store_true',help='Local simulator with synthetic data')
    parser.add_argument('--mode',choices=['all','bot','web'],default='all')
    parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--database');parser.add_argument('--env',default='.env')
    parser.add_argument('--check-bot',action='store_true',help='Read-only Telegram identity and webhook check')
    parser.add_argument('--configure-bot',action='store_true',help='Set FUTARCHIST name and scoped command menus')
    args=parser.parse_args();load_env(args.env);os.umask(0o077)
    if args.host not in ('127.0.0.1','localhost','::1'):parser.error('HTTP server is loopback-only. Use a TLS reverse proxy for public access.')
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(name)s %(levelname)s %(message)s')
    if args.demo:
        if args.mode!='all' or args.check_bot or args.configure_bot:parser.error('Demo uses --mode all and no live Telegram operations')
        owner=1;owners=(1,4);token='DEMO';origin=f'http://{args.host}:{args.port}';app_url='';name='FutarchistDemoBot';client=FakeTelegram()
    else:
        token=os.environ.get('BOT_TOKEN','');app_url=os.environ.get('APP_URL','').rstrip('/');name=os.environ.get('BOT_USERNAME','FutarchistBot')
        try:
            owner=int(os.environ['OWNER_TG_ID']);owners=tuple(int(x.strip()) for x in os.environ.get('SUPER_ADMIN_IDS',str(owner)).split(','))
        except (KeyError,ValueError):parser.error('OWNER_TG_ID and SUPER_ADMIN_IDS must be positive numeric Telegram IDs')
        if owner<=0 or owner not in owners or any(u<=0 for u in owners) or not re.fullmatch(r'\d{5,}:[A-Za-z0-9_-]{20,}',token):parser.error('Set a valid BOT_TOKEN, OWNER_TG_ID and SUPER_ADMIN_IDS in .env')
        if app_url:
            parsed=urlsplit(app_url)
            if parsed.scheme!='https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:parser.error('APP_URL must be a public HTTPS origin with no path')
        if not re.fullmatch(r'[A-Za-z0-9_]{5,32}',name):parser.error('BOT_USERNAME must be the BotFather username without @')
        origin=app_url or f'http://{args.host}:{args.port}';client=TelegramClient(token)
        if args.check_bot or args.configure_bot:
            try:me=client.call('getMe');webhook=client.call('getWebhookInfo')
            except (TelegramError,UncertainDelivery):parser.exit(1,'Telegram check failed. No token is logged.\n')
            if str(me.get('username','')).lower()!=name.lower():parser.error('BOT_USERNAME does not match BOT_TOKEN')
            import json
            if args.configure_bot:
                try:result=configure_bot(client,owners)
                except (TelegramError,UncertainDelivery):parser.exit(1,'Telegram metadata configuration incomplete. Inspect command menus before repeating.\n')
                print(json.dumps(result));return
            print(json.dumps({'id':me['id'],'username':me['username'],'name':me['first_name'],'webhook_present':bool(webhook.get('url')),'privacy_enabled':not me.get('can_read_all_group_messages',False)}));return
    path=Path(args.database or ('data/futarchist-demo.sqlite3' if args.demo else os.environ.get('DATABASE_PATH','data/futarchist.sqlite3')))
    path.parent.mkdir(parents=True,exist_ok=True)
    locks=[]
    if args.mode in ('all','bot'):
        lock=open(str(path)+'.bot.lock','a');locks.append(lock)
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:parser.error('Another bot worker is using this database')
    with open(str(path)+'.schema.lock','a') as schema_lock:
        fcntl.flock(schema_lock,fcntl.LOCK_EX)
        store=Store(path,owner,super_admin_ids=owners,gated=True)
    if args.demo:demo_seed(store)
    bot=Bot(store,name,app_url);service=Service(store,name);stop=threading.Event()
    engine=Engine(store,bot,client,rate_limit=not args.demo) if args.mode in ('all','bot') else None
    server=AppServer((args.host,args.port),store,service,engine,origin,token,args.demo) if args.mode in ('all','web') else None
    threads=[]
    def terminate(*_):
        stop.set()
        if server:threading.Thread(target=server.shutdown,daemon=True).start()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,terminate)
    if engine:
        if args.demo:
            def demo_worker():
                while not stop.is_set():
                    try:engine.drain()
                    except Exception:log.error('Demo worker failed; retrying')
                    stop.wait(.1)
            work=demo_worker
        else:work=lambda:engine.run(stop)
        thread=threading.Thread(target=work,daemon=True,name='futarchist-engine');thread.start();threads.append(thread)
    if server:
        def web_beat():
            while not stop.is_set():
                try:
                    with store.tx():Health(store).beat('web')
                except Exception:log.error('Web heartbeat unavailable')
                stop.wait(10)
        thread=threading.Thread(target=web_beat,daemon=True);thread.start();threads.append(thread)
    log.info('FUTARCHIST mode=%s, demo=%s, panel=%s',args.mode,args.demo,origin if server else 'separate web process')
    try:
        if server:server.serve_forever(poll_interval=.2)
        else:stop.wait()
    finally:
        stop.set()
        if server:server.server_close()
        for thread in threads:thread.join(timeout=2)
        with store.lock:store.close()
        for lock in locks:lock.close()

if __name__=='__main__':main()
