from __future__ import annotations
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .core import dumps
from .telegram import TelegramError, UncertainDelivery

class FakeTelegram:
    """Deterministic, Telegram-shaped API. Never connects to Telegram."""
    def __init__(self):
        self.calls=[]; self.messages=[]; self.documents={};self.user_events=[]; self.updates=[]; self.failures=[]; self.sequence=0
        self.lock=threading.RLock(); self.message_id=0
        self.admins={( -1007,1),(-1007,2)}

    def call(self,method,payload=None,timeout=30):
        payload=payload or {}
        with self.lock:
            self.calls.append({'method':method,'payload':payload})
            if self.failures and method in ('sendMessage','editMessageText','sendDocument'):
                failure=self.failures.pop(0)
                if failure=='timeout': raise UncertainDelivery('Simulated timeout')
                raise TelegramError(failure,'Simulated rejection',3 if failure==429 else None)
            if method=='getUpdates': return [u for u in self.updates if u['update_id']>=payload.get('offset',0)]
            if method=='getMe': return {'id':900000,'is_bot':True,'username':'OwnershipDemoBot'}
            if method=='getWebhookInfo': return {'url':''}
            if method=='getChatMember': return {'status':'administrator' if (payload['chat_id'],payload['user_id']) in self.admins else 'member'}
            if method=='getChatAdministrators':return [{'status':'administrator','user':{'id':uid,'is_bot':False,'first_name':'Demo admin'}} for chat,uid in self.admins if chat==payload['chat_id']]
            if method in ('answerCallbackQuery','setMyCommands','setMyName','setMyDescription','setMyShortDescription','setChatMenuButton'): return True
            if method in ('sendMessage','editMessageText','sendDocument'):
                if method=='editMessageText':
                    message_id=payload['message_id']
                    old=next((m for m in self.messages if m['chat']['id']==payload['chat_id'] and m['message_id']==message_id),None)
                    sequence=old['sequence'] if old else self.sequence+1
                    self.messages=[m for m in self.messages if not (m['chat']['id']==payload['chat_id'] and m['message_id']==message_id)]
                else:
                    self.message_id+=1; message_id=self.message_id
                    self.sequence+=1;sequence=self.sequence
                result={'message_id':message_id,'chat':{'id':payload['chat_id'],'type':'private' if payload['chat_id']>0 else 'supergroup'},'text':payload.get('text',payload.get('caption','')),
                        'reply_markup':payload.get('reply_markup',{}),'sequence':sequence}
                if method=='sendDocument':
                    self.documents[message_id]=payload['_file']
                    result['document']={'file_name':payload['_file']['name'],'file_size':len(payload['_file']['data']),'file_id':'simulated-document'}
                    result['document_url']='/demo/document?message='+str(message_id)
                self.messages.append(result)
                return result
            raise TelegramError(400,'Unsupported simulated method')

    def chat(self,chat_id):
        with self.lock: return [dict(m) for m in self.messages if m['chat']['id']==chat_id]

    def record_user(self,chat_id,uid,text):
        with self.lock:
            self.sequence+=1
            self.user_events.append({'sequence':self.sequence,'chat':{'id':chat_id},'from':uid,'text':text,'mine':True})

    def transcript(self,chat_id):
        with self.lock:
            return sorted([dict(m) for m in self.messages+self.user_events if m['chat']['id']==chat_id],key=lambda m:m['sequence'])

class FakeAPIServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,fake,port=0):
        self.fake=fake
        super().__init__(('127.0.0.1',port),FakeAPIHandler)

class FakeAPIHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            raw=self.rfile.read(int(self.headers['Content-Length']))
            if self.headers.get('Content-Type','').startswith('multipart/form-data'):
                from email.parser import BytesParser
                from email.policy import default
                message=BytesParser(policy=default).parsebytes(('Content-Type: '+self.headers['Content-Type']+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+raw);payload={}
                for part in message.iter_parts():
                    key=part.get_param('name',header='content-disposition')
                    if key=='document':payload['_file']={'name':part.get_filename(),'mime':part.get_content_type(),'data':part.get_payload(decode=True)}
                    else:
                        value=part.get_payload(decode=True).decode()
                        try:payload[key]=json.loads(value)
                        except ValueError:payload[key]=value
            else:payload=json.loads(raw)
            method=self.path.rsplit('/',1)[1]
            result=self.server.fake.call(method,payload)
            body={'ok':True,'result':result}; code=200
        except TelegramError as e:
            body={'ok':False,'error_code':e.code,'description':str(e),'parameters':{'retry_after':e.retry_after}}; code=e.code
        except UncertainDelivery:
            self.connection.shutdown(2); self.connection.close(); return
        data=dumps(body).encode()
        self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self,*args): pass

def message_update(update_id,uid,text,chat_id=None,group=False):
    chat_id=uid if chat_id is None else chat_id
    return {'update_id':update_id,'message':{'message_id':update_id,'from':{'id':uid,'first_name':f'User {uid}'},
            'chat':{'id':chat_id,'type':'supergroup' if group else 'private','title':'Demo team group'} ,'text':text}}

def callback_update(update_id,uid,data,message_id=1):
    return {'update_id':update_id,'callback_query':{'id':str(update_id),'from':{'id':uid,'first_name':f'User {uid}'},
            'message':{'message_id':message_id,'chat':{'id':uid,'type':'private'}},'data':data}}
