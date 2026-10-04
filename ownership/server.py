from __future__ import annotations
import hashlib
import hmac
import json
import logging
import re
import time
from collections import defaultdict, deque
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from .core import AppError, dumps, tg_auth
from .simulator import message_update, callback_update
from .management import Management
from .health import Health
from .exports import Exports

STATIC=Path(__file__).parent/'static'
log=logging.getLogger('ownership.http')

class AppServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,store,service,engine,origin,bot_token='',demo=False):
        if demo and address[0] not in ('127.0.0.1','localhost','::1'): raise ValueError('Demo must bind to loopback only')
        self.store=store; self.service=service; self.engine=engine; self.origin=origin.rstrip('/')
        self.bot_token=bot_token; self.demo=demo; self.demo_id=int(time.time()*1000); self.limits=defaultdict(deque)
        super().__init__(address,Handler)

    def limited(self,key,maximum=120):
        now=time.monotonic(); queue=self.limits[key]
        while queue and queue[0]<now-60: queue.popleft()
        if len(queue)>=maximum: raise AppError('Too many requests. Try again in one minute.',429)
        queue.append(now)
        if len(self.limits)>5000:
            for k in list(self.limits):
                if not self.limits[k] or self.limits[k][-1]<now-60: del self.limits[k]

class Handler(BaseHTTPRequestHandler):
    server_version='FUTARCHIST'
    protocol_version='HTTP/1.1'

    def setup(self):
        self.request.settimeout(15)
        super().setup()

    def log_message(self,fmt,*args):
        # Never log login URLs, cookies, body, Telegram tokens, or personal answers.
        log.info('%s %s %s',self.command,urlsplit(self.path).path,str(args[1]) if len(args)>1 else '')

    def send_data(self,body,status=200,content_type='application/json; charset=utf-8',extra=None):
        if isinstance(body,(dict,list)): body=dumps(body).encode()
        elif isinstance(body,str): body=body.encode()
        self.send_response(status)
        self.send_header('Content-Type',content_type); self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' https://telegram.org; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors https://web.telegram.org https://*.telegram.org")
        if self.server.origin.startswith('https:'): self.send_header('Strict-Transport-Security','max-age=31536000')
        for key,value in (extra or {}).items(): self.send_header(key,value)
        self.end_headers(); self.wfile.write(body)

    def body(self):
        try: length=int(self.headers.get('Content-Length','0'))
        except ValueError: raise AppError('Invalid request size.') from None
        if length<0 or length>65536: self.close_connection=True; raise AppError('The request is too large.',413)
        if self.headers.get('Content-Type','').split(';')[0]!='application/json': raise AppError('Use application/json for this request.',415)
        try:
            value=json.loads(self.rfile.read(length))
            if not isinstance(value,dict): raise ValueError()
            return value
        except (ValueError,UnicodeError): raise AppError('Request JSON is invalid.') from None

    def origin_check(self):
        origin=self.headers.get('Origin')
        if origin and origin!=self.server.origin: raise AppError('Request origin is not allowed.',403)
        if self.headers.get('Sec-Fetch-Site')=='cross-site': raise AppError('Request origin is not allowed.',403)

    def identity(self,mutating=False):
        cookie=SimpleCookie()
        try: cookie.load(self.headers.get('Cookie',''))
        except Exception: raise AppError('Invalid login.',401) from None
        authorization=self.headers.get('Authorization','')
        if authorization:
            if not authorization.startswith('Bearer ') or len(authorization)>128:raise AppError('Invalid login.',401)
            token=authorization[7:]
        else:token=cookie['ownership_session'].value if 'ownership_session' in cookie else ''
        session=self.server.store.session(token)
        if mutating:
            self.origin_check()
            if not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),session['csrf']): raise AppError('Request not verified. Refresh the page.',403)
        self.server.limited('session:'+session['token_hash'],180)
        return session['user_id'],session

    def auth_response(self,result,mini_app=False):
        token,csrf=result
        secure='; Secure' if self.server.origin.startswith('https:') else ''
        cookie=f'ownership_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200'+secure
        data={'ok':True,'csrf':csrf}
        # Telegram Web embeds Mini Apps cross-site. Never rely on third-party cookies.
        # This token lives only in the Mini App's memory, not localStorage or a URL.
        if mini_app:data['session_token']=token
        self.send_data(data,extra={'Set-Cookie':cookie})

    def do_GET(self): self.handle_request(False)
    def do_POST(self): self.handle_request(True)
    def do_DELETE(self): self.handle_request(True)

    def handle_request(self,mutating):
        try:
            parsed=urlsplit(self.path); path=parsed.path; qs=parse_qs(parsed.query)
            if not mutating and path=='/health': self.send_data({'ok':True,'mode':'demo' if self.server.demo else 'live'}); return
            if not mutating and path=='/ready':
                try:
                    with self.server.store.tx():
                        self.server.store.one('SELECT id FROM users LIMIT 1')
                        if self.server.store.one('PRAGMA user_version')['user_version']!=2:raise RuntimeError('Schema is not ready')
                    self.send_data({'ok':True})
                except Exception:self.send_data({'ok':False,'fallback':'native Telegram management'},503)
                return
            if not mutating and path=='/api/config': self.send_data({'demo':self.server.demo,'bot_name':self.server.service.name}); return
            if not mutating and path.startswith('/assets/'):
                asset=path.removeprefix('/assets/')
                allowed={'metadao-wordmark.jpeg':'image/jpeg','metadao.png':'image/png','futardio.png':'image/png','ownership.jpeg':'image/jpeg','futarchist-banner.jpeg':'image/jpeg','futarchist-logo.jpeg':'image/jpeg'}
                if asset not in allowed:raise AppError('File not found.',404)
                self.send_data((STATIC/'assets'/asset).read_bytes(),content_type=allowed[asset]);return
            if not mutating and path in ('/','/emulator','/guide','/app.js','/operations.js','/style.css','/guidance.css','/branding.css','/emulator.js'):
                if path=='/emulator' and not self.server.demo: raise AppError('The simulator is available only in demo mode.',404)
                name={'/':'index.html','/emulator':'emulator.html','/guide':'guide.html'}.get(path,path.lstrip('/'))
                file=STATIC/name
                if not file.is_file(): raise AppError('File not found.',404)
                ctype='text/html; charset=utf-8' if file.suffix=='.html' else ('text/css; charset=utf-8' if file.suffix=='.css' else 'text/javascript; charset=utf-8')
                content=file.read_bytes()
                if self.server.demo and path=='/':
                    content=content.replace(b'<script src="https://telegram.org/js/telegram-web-app.js" defer></script>',b'')
                self.send_data(content,content_type=ctype); return
            if mutating and path in ('/api/auth/telegram','/api/auth/link','/api/auth/demo'):
                self.origin_check(); data=self.body()
                with self.server.store.tx():
                    self.server.limited('login:'+self.client_address[0],60)
                    if path.endswith('/demo'):
                        if not self.server.demo: raise AppError('Demo login is unavailable in live mode.',404)
                        result=self.server.store.login(int(data['user_id']))
                    elif path.endswith('/link'):
                        result=self.server.store.consume_link(str(data.get('token',''))[:200])
                    else:
                        uid,name=tg_auth(str(data.get('init_data','')),self.server.bot_token,self.server.store.clock())
                        # Never create or promote an admin from client-supplied fields.
                        self.server.store.actor(uid)
                        result=self.server.store.login(uid)
                self.auth_response(result,path.endswith('/telegram')); return
            if path.startswith('/demo/'):
                if not self.server.demo: raise AppError('Demo mode is disabled.',404)
                self.origin_check()
                with self.server.store.tx(): uid,session=self.identity(mutating)
                data=self.body() if mutating else {}
                if not mutating and path=='/demo/chat':
                    chat=int(qs.get('chat',[101])[0]); self.send_data(self.server.engine.client.transcript(chat)); return
                if not mutating and path=='/demo/document':
                    doc=self.server.engine.client.documents.get(int(qs.get('message',['0'])[0]))
                    if not doc:raise AppError('Demo file not found.',404)
                    self.send_data(doc['data'],content_type=doc['mime'],extra={'Content-Disposition':'attachment; filename="'+doc['name']+'"'});return
                if mutating and path in ('/demo/message','/demo/callback'):
                    actor=int(data.get('user_id',101))
                    if actor not in (1,2,3,4,101,102): raise AppError('Invalid demo user.')
                    with self.server.store.tx(): self.server.demo_id+=1; update_id=self.server.demo_id
                    if path.endswith('/message'):
                        chat=int(data.get('chat_id',actor))
                        if chat not in (actor,-1007): raise AppError('Invalid demo chat.')
                        update=message_update(update_id,actor,str(data.get('text',''))[:4096],chat,chat<0)
                        self.server.engine.client.record_user(chat,actor,update['message']['text'])
                    else: update=callback_update(update_id,actor,str(data.get('data',''))[:64],int(data.get('message_id',1)))
                    self.server.engine.ingest([update]); self.server.engine.drain()
                    self.send_data({'ok':True}); return
                raise AppError('Demo route not found.',404)
            data=self.body() if mutating else {}
            with self.server.store.tx():
                uid,session=self.identity(mutating)
                result=self.api(uid,path,qs,data,mutating,session)
            if isinstance(result,tuple): self.send_data(*result)
            else: self.send_data(result)
        except AppError as exc: self.send_data({'error':str(exc)},exc.status)
        except (ValueError,KeyError,TypeError,OverflowError): self.send_data({'error':'Invalid request input.'},400)
        except Exception:
            log.error('Request failed on %s',urlsplit(self.path).path)
            incident=None
            try:
                with self.server.store.tx():incident=Health(self.server.store).incident('web','request_error','A web request was rolled back; native management remains available')
            except Exception:pass
            self.send_data({'error':'The request was not saved. Try again or open /manage first.','incident':incident,'fallback':'/manage'},500)

    def api(self,uid,path,qs,data,mutating,session):
        s=self.server.store; service=self.server.service;m=Management(s,service)
        sid=int(qs.get('space',[data.get('space_id',0)])[0])
        if path=='/api/me' and not mutating: return {**service.me(uid),'csrf':session['csrf']}
        if path=='/api/logout' and mutating:
            s.db.execute('DELETE FROM sessions WHERE token_hash=?',(session['token_hash'],)); return {'ok':True}
        if path=='/api/spaces' and mutating: return {'id':s.team(uid,data['name'])}
        if path=='/api/spaces' and not mutating:
            s.owner(uid);return s.rows('SELECT * FROM spaces ORDER BY id')
        match=re.fullmatch(r'/api/spaces/(\d+)/rename',path)
        if match and mutating:Management(s).rename_space(uid,int(match[1]),data['name']);return {'ok':True}
        if path=='/api/members':
            if not mutating: return service.members(uid,sid)
            s.membership(uid,sid,int(data['user_id']),data['permissions']); return {'ok':True}
        if path=='/api/admins':
            if not mutating: return service.admins(uid)
            s.add_admin(uid,int(data['user_id']),data['name']); return {'ok':True}
        if path=='/api/admin-status' and mutating:
            if not isinstance(data['active'],bool): raise AppError('Invalid status.')
            s.deactivate(uid,int(data['user_id']),data['active']); return {'ok':True}
        if path=='/api/projects' and not mutating:
            filters=json.loads(qs.get('filters',['{}'])[0]); return s.projects(uid,sid,filters)
        m=re.fullmatch(r'/api/projects/(\d+)',path)
        if m and not mutating:
            pid=int(m[1]);archived=s.actor(uid)['role']=='owner'
            p=s.project(uid,pid,include_archived=archived)
            group=s.one('SELECT * FROM groups WHERE project_id=?',(pid,))
            return {**p,**s.history(uid,pid,include_archived=archived),'group':dict(group) if group else None}
        m=re.fullmatch(r'/api/cases/(\d+)',path)
        if m and mutating:
            s.update_case(uid,int(m[1]),int(data['version']),data.get('status'),int(data['assignee']) if data.get('assignee') is not None else None); return {'ok':True}
        if path=='/api/notes' and mutating:
            if not isinstance(data.get('guest',False),bool): raise AppError('Invalid message type.')
            return {'id':s.note(uid,int(data['project_id']),data['purpose'],data['text'],data.get('guest',False),service.name)}
        if path=='/api/bindings' and mutating: return service.binding(uid,int(data['project_id']))
        if path=='/api/group-disconnect' and mutating: return {'group':service.group(uid,int(data['project_id']),True)}
        if path=='/api/routes':
            if not mutating: return service.routes(uid,sid)
            return s.route(uid,sid,data['name'],data['purpose'],int(data['assignee']))
        if path=='/api/route-status' and mutating:
            if not isinstance(data['active'],bool): raise AppError('Invalid status.')
            service.route_status(uid,int(data['route_id']),data['active']); return {'ok':True}
        if path=='/api/views':
            if not mutating: return service.views(uid,sid)
            return {'id':service.save_view(uid,sid,data['name'],data['filters'])}
        m=re.fullmatch(r'/api/views/(\d+)',path)
        if m and self.command=='DELETE': service.delete_view(uid,int(m[1])); return {'ok':True}
        if path=='/api/export' and not mutating:
            if qs.get('format') or qs.get('dataset'):
                body,name,mime=Exports(s,service).build(uid,sid,qs.get('dataset',['projects'])[0],qs.get('format',['csv'])[0],json.loads(qs.get('filters',['{}'])[0]))
                return body,200,mime,{'Content-Disposition':f'attachment; filename="{name}"'}
            content=s.csv_export(uid,sid,json.loads(qs.get('filters',['{}'])[0]))
            return content,200,'text/csv; charset=utf-8',{'Content-Disposition':'attachment; filename="futarchist-projects.csv"'}
        if path=='/api/campaigns':
            if not mutating: return service.campaigns(uid,sid)
            return service.campaign(uid,sid,data['topic'],data['when'],data['template'],data.get('filters',{}))
        m=re.fullmatch(r'/api/campaigns/(\d+)(?:/(confirm|cancel))?',path)
        if m:
            cid=int(m[1]); action=m[2]
            if not mutating and not action: return service.campaign_detail(uid,cid)
            if mutating and action=='confirm': return service.confirm(uid,cid)
            if mutating and action=='cancel': service.cancel(uid,cid); return {'ok':True}
        if path=='/api/audit' and not mutating: return service.audit(uid,sid or None)
        if path=='/api/deliveries' and not mutating: return service.deliveries(uid,sid)
        if path=='/api/operations' and not mutating:
            return Health(s).snapshot(uid)
        management=Management(s,service)
        if path=='/api/events':
            if not mutating:return management.events(uid,sid,qs.get('archived',[''])[0]=='only')
            return management.save_event(uid,sid,data)
        match=re.fullmatch(r'/api/events/(\d+)(?:/(projects))?',path)
        if match:
            eid=int(match[1])
            if not mutating and not match[2]:return management.event(uid,eid,qs.get('archived',[''])[0]=='only')
            if mutating and match[2]:management.link_event(uid,eid,int(data['project_id']),data['participation']);return {'ok':True}
            if mutating:return management.save_event(uid,sid,data,eid)
        if path=='/api/tasks':
            if not mutating:return management.tasks(uid,sid,qs.get('archived',[''])[0]=='only')
            return management.save_task(uid,sid,data)
        match=re.fullmatch(r'/api/tasks/(\d+)',path)
        if match and mutating:return management.save_task(uid,sid,data,int(match[1]))
        if path=='/api/texts':
            if not mutating:return management.texts(uid)
            return management.set_text(uid,data['key'],data['value'],int(data['version']))
        match=re.fullmatch(r'/api/projects/(\d+)/edit',path)
        if match and mutating:return management.edit_project(uid,int(match[1]),int(data['version']),data['changes'],data.get('purpose','general'))
        match=re.fullmatch(r'/api/notes/(\d+)/edit',path)
        if match and mutating:management.edit_note(uid,int(match[1]),int(data['version']),data['text']);return {'ok':True}
        match=re.fullmatch(r'/api/routes/(\d+)/config',path)
        if match and mutating:return management.configure_route(uid,int(match[1]),data['changes'])
        match=re.fullmatch(r'/api/routes/(\d+)/rotate',path)
        if match and mutating:return management.rotate_route(uid,int(match[1]))
        if path=='/api/grants':
            if not mutating:return management.grants(uid,int(qs.get('route_id',['0'])[0]))
            if type(data.get('active')) is not bool:raise AppError('Invalid status.')
            management.revoke_grant(uid,int(data['route_id']),int(data['user_id']),data['active']);return {'ok':True}
        if path=='/api/prepare' and mutating:return management.prepare(uid,data['action'],data['data'])
        if path=='/api/confirm' and mutating:return management.confirm(uid,data['token'])
        if path=='/api/repair' and mutating:return Health(s).repair(uid)
        if path=='/api/backup' and mutating:return Health(s).backup(uid)
        if path=='/api/retry-update' and mutating:Health(s).retry_update(uid,int(data['update_id']));return {'ok':True}
        if path=='/api/incident-ack' and mutating:Health(s).resolve(uid,int(data['incident_id']));return {'ok':True}
        raise AppError('Route not found.',404)
