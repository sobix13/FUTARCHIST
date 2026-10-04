from __future__ import annotations
import json
import logging
import secrets
import socket
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from .core import AppError, dumps
from .health import Health

log=logging.getLogger('ownership.telegram')

class TelegramError(Exception):
    def __init__(self,code,description='Telegram request failed',retry_after=None):
        super().__init__(description)
        self.code=code; self.retry_after=retry_after

class UncertainDelivery(Exception):
    """The request may have reached Telegram. Never blindly retry a send."""

class TelegramClient:
    def __init__(self,token,base='https://api.telegram.org',allow_local=False):
        parsed=urlsplit(base)
        if not (parsed.scheme=='https' and parsed.hostname=='api.telegram.org'):
            if not (allow_local and parsed.scheme=='http' and parsed.hostname in ('127.0.0.1','localhost','::1')):
                raise ValueError('Telegram API must be official HTTPS; local API is simulation-only.')
        self.base=base.rstrip('/')+'/bot'+token

    def call(self,method,payload=None,timeout=30):
        payload=dict(payload or {});upload=payload.pop('_file',None)
        if upload is not None:
            import re
            if method!='sendDocument' or not isinstance(upload,dict) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}',upload.get('name','')):raise AppError('Invalid export file.')
            content=upload.get('data')
            if not isinstance(content,bytes) or len(content)>20_000_000:raise AppError('Invalid export size.')
            boundary='Futarchist'+secrets.token_hex(16);parts=[]
            for key,value in payload.items():
                text=dumps(value) if isinstance(value,(dict,list,bool)) else str(value)
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{text}\r\n'.encode())
            parts += [f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{upload["name"]}"\r\nContent-Type: {upload["mime"]}\r\n\r\n'.encode(),content,f'\r\n--{boundary}--\r\n'.encode()]
            body=b''.join(parts);ctype='multipart/form-data; boundary='+boundary
        else:body=dumps(payload).encode();ctype='application/json'
        request=Request(self.base+'/'+method,data=body,headers={'Content-Type':ctype})
        try:
            try:
                with urlopen(request,timeout=timeout) as response: data=response.read(2_000_001)
            except HTTPError as exc: data=exc.read(2_000_001)
            if len(data)>2_000_000: raise ValueError('Oversized Telegram response')
            result=json.loads(data)
            if not isinstance(result,dict) or 'ok' not in result: raise ValueError('Malformed Telegram response')
            if not result['ok']:
                raise TelegramError(int(result.get('error_code',500)),str(result.get('description','Telegram request failed'))[:200],result.get('parameters',{}).get('retry_after'))
            return result.get('result')
        except TelegramError: raise
        except (URLError,TimeoutError,socket.timeout,ValueError,OSError) as exc:
            # Do not log tokens or raw request payloads.
            raise UncertainDelivery(type(exc).__name__) from None

class Engine:
    def __init__(self,store,bot,client,rate_limit=True):
        self.s=store; self.bot=bot; self.client=client; self.rate_limit=rate_limit
        self.next_global=0; self.next_chat={}; self.next_processing=0
        self.processing=threading.Lock(); self.dispatching=threading.Lock()
        self.health=Health(store)
        with self.s.tx():
            # A previous process might have died after sendMessage but before acknowledgement.
            self.s.db.execute("UPDATE outbox SET state='uncertain',error='Process restarted during delivery; manual verification required' WHERE state='sending'")

    def ingest(self,updates):
        with self.s.tx():
            highest=int((self.s.one("SELECT value FROM settings WHERE key='poll_offset'") or {'value':'0'})['value'])
            for update in updates:
                update_id=update.get('update_id')
                if isinstance(update_id,bool) or not isinstance(update_id,int) or update_id<0: continue
                # Group privacy: don't retain arbitrary group discussions at all.
                keep=True
                m=update.get('message')
                if m and m.get('chat',{}).get('type')!='private':
                    text=m.get('text','')
                    keep=bool(m.get('migrate_to_chat_id') or text.startswith(('/bind ','/bind@','/help','/guide','/start')))
                    command=text.partition(' ')[0]
                    if '@' in command and command.split('@',1)[1].lower()!=self.bot.name.lower():keep=False
                if keep:
                    self.s.db.execute('INSERT OR IGNORE INTO inbox(update_id,payload,received_at) VALUES(?,?,?)',(update_id,dumps(update),self.s.clock()))
                highest=max(highest,update_id+1)
            self.s.db.execute("INSERT INTO settings VALUES('poll_offset',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(highest),))
            return highest

    def _verify_group(self,update):
        m=update.get('message',{}); text=m.get('text','')
        if m.get('chat',{}).get('type')=='private' or not text.startswith(('/bind ','/bind@')): return False
        if not m.get('from'): return False  # anonymous group admin cannot be linked to an app identity
        uid=m['from']['id'];token=text.partition(' ')[2].strip()
        with self.s.tx():
            binding=self.s.one('SELECT b.*,p.submitter FROM bindings b JOIN projects p ON p.id=b.project_id WHERE b.token=? AND b.used=0 AND b.expires>?',(token,self.s.clock()))
            if not binding or uid not in (binding['actor'],binding['submitter']): raise AppError('The group connection code is invalid or expired.')
            self.s.project(binding['actor'],binding['project_id'],'send')
        # getChatMember is only guaranteed for other users when the bot is an admin.
        # The administrators list avoids granting the bot unnecessary moderation powers.
        try:result=self.client.call('getChatAdministrators',{'chat_id':m['chat']['id']},timeout=8)
        except TelegramError as exc:
            if exc.code in (400,403): raise AppError('Group admin verification failed. Check the bot\'s membership and send permissions.') from None
            raise
        if not isinstance(result,list): raise TelegramError(502,'Invalid administrator response')
        return any(member.get('user',{}).get('id')==uid and member.get('status') in ('creator','administrator') for member in result)

    def process_one(self):
        with self.processing:
            with self.s.tx():
                row=self.s.one('SELECT * FROM inbox WHERE done=0 AND attempts<5 AND next_at<=? ORDER BY update_id LIMIT 1',(self.s.clock(),))
                if not row: return False
                row=dict(row)
            update=json.loads(row['payload'])
            try:
                verified=self._verify_group(update)
                with self.s.tx():
                    self.bot.process(update,verified)
                    self.s.db.execute('UPDATE inbox SET done=1,attempts=attempts+1,error=NULL,payload=\'{}\' WHERE update_id=?',(row['update_id'],))
                    self.health.beat('inbox')
                return True
            except AppError as exc:
                # Rollback form/case changes before sending a friendly, non-sensitive error.
                with self.s.tx():
                    m=update.get('message') or update.get('callback_query',{}).get('message',{})
                    chat=m.get('chat',{}).get('id')
                    if chat: self.bot.send(chat,str(exc))
                    cb=update.get('callback_query')
                    if cb: self.s.queue('answerCallbackQuery',{'callback_query_id':cb['id']})
                    self.s.db.execute('UPDATE inbox SET done=1,attempts=attempts+1,error=?,payload=\'{}\' WHERE update_id=?',('Rejected: '+str(exc)[:200],row['update_id']))
                return True
            except (TelegramError,UncertainDelivery) as exc:
                with self.s.tx():
                    delay=getattr(exc,'retry_after',None) or 3
                    next_at=self.s.clock()+max(1,min(86400,int(delay)))
                    self.s.db.execute('UPDATE inbox SET attempts=attempts+1,error=?,next_at=? WHERE update_id=?',('Group verification temporarily unavailable',next_at,row['update_id']))
                    self.health.incident('inbox','group_verification','Group verification is temporarily unavailable','warning')
                return False
            except Exception:
                log.error('Update processing failed; update_id=%s',row['update_id'])
                with self.s.tx():
                    self.s.db.execute('UPDATE inbox SET attempts=attempts+1,error=?,next_at=? WHERE update_id=?',('Internal processing error',self.s.clock()+5,row['update_id']))
                    incident=self.health.incident('inbox','processing_error','An update was rolled back; other updates continue')
                    if row['attempts']==0:
                        m=update.get('message') or update.get('callback_query',{}).get('message',{})
                        if m.get('chat',{}).get('type')=='private':self.bot.send(m['chat']['id'],'The request was not saved. Reference '+str(incident)+'. Other sections remain available. /support')
                return False

    def poll_once(self):
        with self.s.tx():
            row=self.s.one("SELECT value FROM settings WHERE key='poll_offset'")
            offset=int(row['value']) if row else 0
        updates=self.client.call('getUpdates',{'offset':offset,'timeout':20,'allowed_updates':['message','callback_query','my_chat_member']},timeout=28)
        self.ingest(updates)
        with self.s.tx():self.health.beat('poller');self.health.recovered('poller','unavailable')
        return len(updates)

    def _valid_job(self,job,payload):
        if job['permission']:
            for permission in job['permission'].split('|'):
                self.s.check(job['actor'],job['space_id'],permission)
        if job['method']=='sendDocument':
            export=payload.get('_export')
            if not isinstance(export,dict) or export.get('uid')!=job['actor'] or export.get('sid')!=job['space_id'] or payload.get('chat_id')!=job['actor']:raise AppError('Invalid export destination')
            self.s.check(job['actor'],job['space_id'],'export')
        if (job['dedupe'] or '').startswith('campaign:'):
            r=self.s.one('SELECT r.*,c.state campaign_state FROM recipients r JOIN campaigns c ON c.id=r.campaign_id WHERE r.outbox_id=?',(job['id'],))
            if not r or r['campaign_state']!='queued': raise AppError('Campaign not active')
            if r['kind']=='group':
                g=self.s.one('SELECT * FROM groups WHERE chat_id=? AND project_id=? AND active=1',(r['chat_id'],r['project_id']))
                if not g: raise AppError('Group opt-in removed')
            else:
                u=self.s.actor(r['chat_id'])
                if not u['started'] or not u['invites']: raise AppError('DM opt-in removed')

    def dispatch_one(self):
        with self.dispatching:
            with self.s.tx():
                now=self.s.clock()
                jobs=self.s.rows("SELECT * FROM outbox WHERE state='pending' AND next_at<=? ORDER BY id LIMIT 100",(now,))
                job=None; payload=None
                for candidate in jobs:
                    p=json.loads(candidate['payload']); chat=p.get('chat_id')
                    if self.rate_limit and (now<self.next_global or (chat and now<self.next_chat.get(chat,0))): continue
                    try: self._valid_job(candidate,p)
                    except AppError:
                        self.s.db.execute("UPDATE outbox SET state='cancelled',error='Authorization or destination consent removed' WHERE id=?",(candidate['id'],)); continue
                    job,payload=candidate,p; break
                if not job: return False
                if job['method']=='sendDocument':
                    from .exports import Exports
                    from .service import Service
                    export=payload.pop('_export')
                    try:body,name,mime=Exports(self.s,Service(self.s,self.bot.name)).build(export['uid'],export['sid'],export['dataset'],export['format'],export.get('filters',{}))
                    except AppError:
                        self.s.db.execute("UPDATE outbox SET state='failed',error='Export permission or data validation failed' WHERE id=?",(job['id'],))
                        self.bot.send(job['actor'],'Export creation failed. Check permissions, filters and dataset size. /export');return True
                    except Exception:
                        self.s.db.execute("UPDATE outbox SET state='failed',error='Export build error' WHERE id=?",(job['id'],))
                        self.health.incident('export','BUILD_FAILED','Export generation failed. Other queue jobs continue.')
                        self.bot.send(job['actor'],'Export creation failed. The incident was recorded and other operations continue. /export');return True
                    payload['_file']={'data':body,'name':name,'mime':mime}
                self.s.db.execute("UPDATE outbox SET state='sending',attempts=attempts+1 WHERE id=?",(job['id'],))
                if self.rate_limit:
                    self.next_global=now+0.04
                    if payload.get('chat_id'): self.next_chat[payload['chat_id']]=now+(3.1 if payload['chat_id']<0 else 1.05)
            state,error,next_at,message_id='sent',None,0,None
            try:
                result=self.client.call(job['method'],payload)
                if isinstance(result,dict): message_id=result.get('message_id')
            except TelegramError as exc:
                # Bot API explicitly rejected the operation: no duplicate risk for 429.
                if exc.code==429 and job['attempts']<8:
                    state='pending'; next_at=self.s.clock()+max(1,min(86400,int(exc.retry_after or 3)))
                elif exc.code>=500:
                    state='uncertain'
                elif exc.code==400 and job['method']=='editMessageText' and 'not modified' in str(exc).lower():
                    state='sent'
                else: state='failed'
                error='Telegram error '+str(exc.code)
                if exc.code==403:
                    with self.s.tx():
                        self.s.db.execute('UPDATE users SET invites=0,started=0 WHERE id=?',(payload.get('chat_id'),))
                        self.s.db.execute('UPDATE groups SET active=0 WHERE chat_id=?',(payload.get('chat_id'),))
            except UncertainDelivery:
                state='uncertain'; error='Delivery outcome unknown; verify in Telegram before resending'
            except Exception:
                log.error('Unexpected transport failure; job_id=%s',job['id'])
                state='uncertain'; error='Internal transport failure; manual verification required'
            with self.s.tx():
                self.s.db.execute('UPDATE outbox SET state=?,error=?,next_at=?,telegram_message_id=? WHERE id=?',(state,error,next_at,message_id,job['id']))
                self.health.beat('outbox','degraded' if state in ('failed','uncertain') else 'ok')
                if state=='uncertain':self.health.incident('outbox','uncertain_delivery','A send result is unknown and will not be retried automatically','warning')
            return True

    def drain(self,limit=1000):
        count=0
        while count<limit and self.process_one(): count+=1
        while count<limit and self.dispatch_one(): count+=1
        return count

    def run(self,stop):
        def guarded(component,work,idle):
            failures=0
            while not stop.is_set():
                try:
                    worked=work();failures=0
                    with self.s.tx():self.health.beat(component);self.health.recovered(component,'worker_error')
                    if not worked:stop.wait(idle)
                except Exception:
                    failures+=1;log.warning('%s unavailable; bounded retry %s',component,failures)
                    try:
                        with self.s.tx():self.health.beat(component,'degraded');self.health.incident(component,'unavailable' if component=='poller' else 'worker_error','Component failed; independent workers continue')
                    except Exception:log.error('Health persistence unavailable')
                    stop.wait(min(60,2**min(failures,6)))
        def maintain():
            with self.s.tx():self.health.repair(automatic=True)
            return False
        specs=[('poller',self.poll_once,.1),('inbox',self.process_one,.1),('outbox',self.dispatch_one,.1),('maintenance',maintain,30)]
        workers=[threading.Thread(target=guarded,args=spec,daemon=True,name='futarchist-'+spec[0]) for spec in specs]
        for worker in workers:worker.start()
        while not stop.wait(.5):
            for i,worker in enumerate(workers):
                if not worker.is_alive():
                    with self.s.tx():self.health.incident(specs[i][0],'worker_restart','Worker exited and was restarted')
                    workers[i]=threading.Thread(target=guarded,args=specs[i],daemon=True,name='futarchist-'+specs[i][0]);workers[i].start()
