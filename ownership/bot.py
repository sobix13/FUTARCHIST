from __future__ import annotations
import json
import secrets
from .core import AppError, dumps, text_units, is_financial_filter
from .forms import FIELDS, questions, validate, label, split_answers
from .management import Management, SUPPORT

class Bot:
    def __init__(self,store,bot_name='FutarchistBot',app_url=''):
        self.s=store; self.name=bot_name; self.app_url=app_url; self.management=Management(store)
        from .native import NativeAdmin
        self.native=NativeAdmin(self)

    def send(self,chat,text,buttons=None,edit=None):
        # Never silently truncate a guest's review before the Submit button.
        chunks=[];chunk='';units=0
        for c in text:
            n=text_units(c)
            if units+n>3800:chunks.append(chunk);chunk='';units=0
            chunk+=c;units+=n
        chunks.append(chunk)
        for chunk in chunks[:-1]: self.s.queue('sendMessage',{'chat_id':chat,'text':chunk})
        payload={'chat_id':chat,'text':chunks[-1]}
        if buttons: payload['reply_markup']={'inline_keyboard':buttons}
        if edit:
            payload['message_id']=edit
        return self.s.queue('editMessageText' if edit else 'sendMessage',payload)

    def flow(self,uid):
        row=self.s.one('SELECT data FROM flows WHERE user_id=?',(uid,))
        return json.loads(row['data']) if row else None

    def save(self,uid,f):
        self.s.db.execute('INSERT INTO flows VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at',(uid,dumps(f),self.s.clock()))

    def nonce(self,uid,f):
        f['nonce']=secrets.token_hex(4); self.save(uid,f)
        return 'f:'+f['nonce']+':'

    def home(self,uid):
        f=self.flow(uid)
        text=self.management.text('welcome')
        rows=[]
        if f: rows.append([{'text':'Resume draft','callback_data':'resume'}])
        if not self.s.gated or self.s.guest_routes(uid):rows += [[{'text':'Submit information','callback_data':'new'}]]
        rows.append([{'text':'My projects','callback_data':'projects'}])
        if self.s.actor(uid)['role'] in ('owner','admin'):
            rows.append([{'text':'Manage in Telegram','callback_data':'admin'}])
            if self.app_url.startswith('https://'):rows.append([{'text':'Admin panel','web_app':{'url':self.app_url}}])
        rows.append([{'text':'Support','callback_data':'support'}])
        self.send(uid,text+'\n\nBuilt by Ownership',rows)

    def start(self,uid,token):
        route=self.s.activate(uid,token) if self.s.gated else self.s.active_route(token)
        old=self.flow(uid)
        if old:
            old['switch_route']=token; prefix=self.nonce(uid,old)
            self.send(uid,'You have a saved draft. Resume it or start a new form?',
                      [[{'text':'Resume','callback_data':prefix+'resume'}],
                       [{'text':'Replace draft','callback_data':prefix+'switch'}]])
            return
        f={'route':token,'purpose':route['purpose'],'phase':'consent','answers':{},'index':0}
        self.save(uid,f); self.prompt(uid,f)

    def prompt(self,uid,f,edit=None):
        if f['phase'] not in ('reply','optin'):self.s.guest_route(uid,f['route'])
        prefix=self.nonce(uid,f)
        phase=f['phase']
        if phase=='consent':
            route=self.s.active_route(f['route'])
            text=f"Information is stored in '{route['space_name']}' for the assigned reviewer and authorized members. Route: {route['name']}. Share only contacts you want us to use. Continue?"
            rows=[[{'text':'Agree and continue','callback_data':prefix+'consent'}]]
        elif phase=='choose':
            text='What are you submitting information for?'
            rows=[[{'text':title,'callback_data':prefix+'purpose:'+purpose}] for purpose,title in [('general','General information'),('raise','Raise review'),('both','Both')]]
        elif phase=='form':
            qs=questions(f['purpose'],f['answers'])
            if f['index']>=len(qs):
                f['phase']='review'; return self.prompt(uid,f)
            field=qs[f['index']]; prompts,kind,required=FIELDS[field]
            custom=self.management.text('question:'+field)
            text=f"{f['index']+1} / {len(qs)}\n"+(custom or prompts)
            old=f['answers'].get(field)
            if old is not None: text+='\n'+'Current answer: '+(', '.join(old) if isinstance(old,list) else str(old))
            rows=[]
            if isinstance(kind,list):
                for i in range(0,len(kind),2):
                    rows.append([{'text':('+ ' if field=='categories' and v in (old or []) else '')+label(v),'callback_data':prefix+'answer:'+v} for v in kind[i:i+2]])
                if field=='categories': rows.append([{'text':'Done selecting','callback_data':prefix+'done'}])
            if not required: rows.append([{'text':'Skip for now','callback_data':prefix+'skip'}])
            if f['index']>0: rows.append([{'text':'Back','callback_data':prefix+'back'}])
        elif phase=='review':
            g,fund=split_answers(f['purpose'],f['answers'],self.s.actor(uid)['name'])
            lines=['Review before submitting:']
            for k,v in {**g,**fund}.items():
                if k=='contact': continue
                field_name=FIELDS.get(k,(k,None,None))[0]
                rendered=', '.join(label(x) for x in v) if isinstance(v,list) else (label(str(v)) if v is not None else 'Not provided')
                lines.append(field_name+'\n'+rendered)
            text='\n\n'.join(lines)
            rows=[[{'text':'Submit','callback_data':prefix+'submit'}],
                  [{'text':'Back and edit','callback_data':prefix+'back'}]]
        elif phase=='optin':
            text='Information saved. Would you like relevant invitations in this bot? Case-related follow-up questions are separate from this choice.'
            rows=[[{'text':'Yes','callback_data':prefix+'opt:yes'}, {'text':'No','callback_data':prefix+'opt:no'}]]
        elif phase=='reply':
            text='Write your reply in one message. It is saved for authorized reviewers of this case.'
            rows=[]
        else: raise AppError('Invalid form step.')
        if phase!='optin': rows.append([{'text':'Save and leave','callback_data':prefix+'pause'}])
        self.send(uid,text,rows,edit=edit)

    def owned_projects(self,uid):
        rows=self.s.rows('SELECT p.id,p.general,s.name space_name FROM projects p JOIN spaces s ON s.id=p.space_id WHERE p.submitter=? AND p.archived_at IS NULL AND s.active=1 ORDER BY p.id DESC LIMIT 50',(uid,))
        buttons=[]
        for row in rows:
            buttons.append([{'text':json.loads(row['general'])['name']+' | '+row['space_name'],'callback_data':'edit:'+str(row['id'])}])
        self.send(uid,'Your submissions. Select one to edit.' if rows else 'No projects submitted yet.',buttons)

    def begin_edit(self,uid,pid):
        p=self.s.one('SELECT * FROM projects WHERE id=? AND submitter=? AND archived_at IS NULL',(pid,uid))
        if not p: raise AppError('This project does not belong to your account.',403)
        cases=self.s.rows('SELECT c.*,r.token FROM cases c JOIN routes r ON r.id=c.route_id WHERE c.project_id=?',(pid,))
        if not cases: raise AppError('Case intake route not found.')
        if self.flow(uid): raise AppError('Finish your current form or use /cancel to discard it.')
        purpose='both' if len(cases)>1 else cases[0]['purpose']
        # Prefer the existing compatible route, without changing case provenance.
        candidates=self.s.rows('SELECT token FROM routes WHERE space_id=? AND active=1 AND purpose IN (?,\'both\') ORDER BY CASE WHEN token=? THEN 0 ELSE 1 END,id',
                               (p['space_id'],purpose,cases[0]['token']))
        route=None
        for candidate in candidates:
            try: route=self.s.guest_route(uid,candidate['token']); break
            except AppError: continue
        if not route: raise AppError('The editing route is inactive. Ask your reviewer for a new link.')
        data={**json.loads(p['general']),**json.loads(p['fundraising'])}
        if data.get('currency') not in ('USD','USDC','SOL','ETH','EUR','unknown',None):
            data['currency_code']=data['currency']; data['currency']='OTHER'
        f={'route':route['token'],'purpose':purpose,'phase':'form','answers':data,'index':0,'pid':pid,'version':p['version'],'consent':True}
        self.save(uid,f); self.prompt(uid,f)

    def message(self,msg,verified_group_admin=False):
        uid=int(msg['from']['id']); chat=msg['chat']; text=msg.get('text','')
        # Commands addressed to this bot have the same semantics as bare commands.
        if text.startswith('/'):
            command,sep,rest=text.partition(' ')
            if '@' in command:
                bare,address=command.split('@',1)
                if address.lower()!=self.name.lower(): return
                text=bare+(sep+rest if sep else '')
        if chat['type']!='private' and not (text.startswith(('/bind ','/start','/help'))): return
        self.s.register(uid,msg['from'].get('first_name','User'),chat['type']=='private')
        self.s.actor(uid)
        if chat['type']!='private':
            if text.startswith('/bind '): self.bind(uid,chat,text.split(' ',1)[1],verified_group_admin)
            elif text.startswith('/start') or text.startswith('/help'):
                self.send(chat['id'],'Submit project and raise information in a private chat with this bot.',[[{'text':'Open bot','url':f'https://t.me/{self.name}'}]])
            return
        if text.startswith('/activate '):self.start(uid,text.partition(' ')[2].strip());return
        if text in ('/support','/about'):
            self.support(uid);return
        if self.native.message(uid,text):return
        if text.startswith('/start'):
            arg=text.split(' ',1)[1].strip() if ' ' in text else ''
            if arg.startswith('intake_'): self.start(uid,arg[7:])
            elif arg.startswith('invite_'): self.invite_menu(uid,arg[7:])
            elif arg.startswith('reply_'): self.begin_reply(uid,arg[6:])
            else: self.home(uid)
            return
        if text=='/stop':
            self.s.db.execute('UPDATE users SET invites=0 WHERE id=?',(uid,))
            self.send(uid,'DM invitations stopped. Your case and reply access remain available.'); return
        if text=='/cancel':
            self.s.db.execute('DELETE FROM flows WHERE user_id=?',(uid,))
            self.send(uid,'Draft discarded. Submitted cases were not changed.'); self.home(uid); return
        if text=='/resume':
            f=self.flow(uid)
            if f: self.prompt(uid,f)
            else: self.home(uid)
            return
        if text in ('/projects','/myprojects'): self.owned_projects(uid); return
        if text=='/id': self.send(uid,'Telegram ID: '+str(uid)); return
        if text in ('/panel','/admin') and self.s.actor(uid)['role'] in ('owner','admin') and self.app_url.startswith('https://'):
            token=self.s.login_link(uid)
            self.send(uid,'Open your dashboard with this personal, single-use link. It expires in 5 minutes. Keep it private.',
                      [[{'text':'Open browser dashboard','url':self.app_url.rstrip('/')+'/?login='+token}]])
            return
        if text in ('/admin','/help'):
            self.send(uid,self.management.text('help'))
            self.home(uid); return
        f=self.flow(uid)
        if not f:
            if self.s.gated and not text.startswith('/'):
                self.start(uid,text.strip());return
            self.home(uid);return
        if text=='/back' and f['phase'] in ('form','review'):
            self.back(uid,f); return
        if f['phase']=='reply':
            r=self.s.one('SELECT * FROM reply_tokens WHERE token=? AND guest_id=? AND used=0 AND expires>?',(f['reply'],uid,self.s.clock()))
            if not r: raise AppError('This reply was already saved, or its link has expired.')
            from .core import bounded
            reply=bounded(text,3000,True)
            p=self.s.one('SELECT space_id FROM projects WHERE id=?',(r['project_id'],))
            self.s.db.execute('INSERT INTO threads(project_id,purpose,actor,text,visibility,created_at) VALUES(?,?,?,?,?,?)',(r['project_id'],r['purpose'],uid,reply,'guest',self.s.clock()))
            self.s.db.execute('UPDATE reply_tokens SET used=1 WHERE token=?',(f['reply'],))
            self.s.audit(uid,'guest_replied',p['space_id'],r['project_id'],r['purpose'])
            self.s.db.execute('DELETE FROM flows WHERE user_id=?',(uid,)); self.send(uid,'Reply saved.'); return
        if f['phase']!='form': raise AppError('Select a button from the current step to continue.')
        field=questions(f['purpose'],f['answers'])[f['index']]
        if isinstance(FIELDS[field][1],list): raise AppError('Use the buttons for this step.')
        f['answers'][field]=validate(field,text); f['index']+=1
        self.prompt(uid,f)

    def back(self,uid,f):
        qs=questions(f['purpose'],f['answers'])
        f['index']=max(0,min(len(qs),f['index'])-1); f['phase']='form'; self.prompt(uid,f)

    def callback(self,cb):
        uid=int(cb['from']['id']); chat=cb.get('message',{}).get('chat',{})
        self.s.register(uid,cb['from'].get('first_name','User'),chat.get('type')=='private')
        self.s.actor(uid)
        data=cb.get('data','')
        self.s.queue('answerCallbackQuery',{'callback_query_id':cb['id']})
        if chat.get('type')!='private': return
        if data=='support':self.support(uid);return
        if data=='admin' or data.startswith('a:'):
            self.native.callback(uid,data,cb);return
        if data.startswith('rsvp:'):
            _,token,response=data.split(':',2); self.rsvp(uid,token,response); return
        if data=='projects': self.owned_projects(uid); return
        if data.startswith('edit:'): self.begin_edit(uid,int(data[5:])); return
        if data=='resume':
            f=self.flow(uid)
            if f: self.prompt(uid,f)
            else: self.home(uid)
            return
        if data=='new':
            if not self.s.gated:self.start(uid,'public');return
            routes=self.s.guest_routes(uid)
            if not routes:self.send(uid,'Enter the access code supplied by your contact.');return
            if len(routes)==1:self.start(uid,routes[0]['token']);return
            self.send(uid,'Select an intake route.',[[{'text':r['name'],'callback_data':'grant:'+str(r['id'])}] for r in routes]);return
        if data.startswith('grant:'):
            routes=self.s.guest_routes(uid);route=next((r for r in routes if str(r['id'])==data[6:]),None)
            if not route:raise AppError('This route is not active for your account.',403)
            self.start(uid,route['token']);return
        f=self.flow(uid)
        if not f or not data.startswith('f:'+f.get('nonce','')+':'):
            self.send(uid,'This button belongs to an older step. Use the latest message or /resume.'); return
        action=data.split(':',2)[2]
        if action=='pause':
            self.nonce(uid,f)
            self.send(uid,'Draft saved. Use /resume when ready.'); return
        if action=='resume': f.pop('switch_route',None); self.prompt(uid,f); return
        if action=='switch':
            token=f.get('switch_route','public'); self.s.db.execute('DELETE FROM flows WHERE user_id=?',(uid,)); self.start(uid,token); return
        if action=='consent' and f['phase']=='consent':
            f['consent']=True; f['phase']='choose' if f['purpose']=='both' else 'form'; self.prompt(uid,f); return
        if action.startswith('purpose:') and f['phase']=='choose':
            purpose=action[8:]
            if purpose not in ('general','raise','both'): raise AppError('Invalid form type.')
            f['purpose']=purpose; f['phase']='form'; self.prompt(uid,f); return
        if action=='back' and f['phase'] in ('form','review'): self.back(uid,f); return
        if f['phase']=='form':
            field=questions(f['purpose'],f['answers'])[f['index']]
            if action=='skip': f['answers'][field]=validate(field,None)
            elif action=='done' and field=='categories': validate(field,f['answers'].get(field))
            elif action.startswith('answer:'):
                value=action[7:]
                if field=='categories':
                    if value not in FIELDS[field][1]: raise AppError('Invalid option.')
                    selected=f['answers'].setdefault(field,[])
                    if value in selected: selected.remove(value)
                    else: selected.append(value)
                    self.prompt(uid,f,edit=cb['message']['message_id']); return
                f['answers'][field]=validate(field,value)
            else: raise AppError('Invalid answer for this step.')
            f['index']+=1; self.prompt(uid,f); return
        if action=='submit' and f['phase']=='review':
            if not f.get('consent'): raise AppError('Confirm the submission first.')
            general,fund=split_answers(f['purpose'],f['answers'],self.s.actor(uid)['name'])
            pid=self.s.save_project(uid,f['route'],general,fund,f['purpose'],f.get('pid'),f.get('version'))
            f['pid']=pid; f['phase']='optin'; self.prompt(uid,f); return
        if action.startswith('opt:') and f['phase']=='optin':
            value=action[4:]
            if value not in ('yes','no'): raise AppError('Invalid option.')
            self.s.db.execute('UPDATE users SET invites=? WHERE id=?',(int(value=='yes'),uid))
            self.s.db.execute('DELETE FROM flows WHERE user_id=?',(uid,))
            self.send(uid,'Done. Use My projects to edit your information.'); self.home(uid); return
        raise AppError('This button does not match the current step.')

    def begin_reply(self,uid,token):
        r=self.s.one('SELECT * FROM reply_tokens WHERE token=? AND guest_id=? AND used=0 AND expires>?',(token,uid,self.s.clock()))
        if not r: raise AppError('This link is not active for your account.')
        if self.flow(uid): raise AppError('Finish your current form or use /cancel first.')
        self.prompt(uid,{'phase':'reply','reply':token})

    def support(self,uid):
        self.send(uid,'FUTARCHIST\nProject information, teams, programs and raise management.\nSupport: @sobix13 and @SrMessiSOL\n\nBuilt by Ownership',[[{'text':'Sobix','url':'https://t.me/sobix13'},{'text':'SrMessi','url':'https://t.me/SrMessiSOL'}]])

    def invite_menu(self,uid,token):
        r=self.s.one('SELECT r.*,p.submitter,c.topic,c.when_text FROM recipients r JOIN projects p ON p.id=r.project_id JOIN campaigns c ON c.id=r.campaign_id WHERE r.token=? AND c.state=\'queued\'',(token,))
        if not r or r['submitter']!=uid: raise AppError('This invitation is assigned to the project\'s representative.',403)
        self.send(uid,r['topic']+'\n'+r['when_text'],[[{'text':label(v),'callback_data':f'rsvp:{token}:{v}'} for v in ('yes','no','later')]])

    def rsvp(self,uid,token,response):
        if response not in ('yes','no','later'): raise AppError('Invalid response.')
        r=self.s.one('SELECT r.*,p.submitter,p.space_id,c.state,c.filters FROM recipients r JOIN projects p ON p.id=r.project_id JOIN campaigns c ON c.id=r.campaign_id WHERE r.token=?',(token,))
        if not r or r['submitter']!=uid or r['state']!='queued': raise AppError('This invitation is not active for your account.',403)
        self.s.db.execute('UPDATE recipients SET response=?,responder=?,responded_at=? WHERE id=?',(response,uid,self.s.clock(),r['id']))
        self.s.audit(uid,'invitation_response',r['space_id'],r['project_id'],purpose='raise' if is_financial_filter(json.loads(r['filters'])) else 'general',details={'campaign':r['campaign_id'],'response':response})
        self.send(uid,'Invitation response saved.')

    def bind(self,uid,chat,token,verified):
        if not verified: raise AppError('A group admin must connect this group.',403)
        binding=self.s.one('SELECT b.*,p.submitter FROM bindings b JOIN projects p ON p.id=b.project_id WHERE b.token=? AND b.used=0 AND b.expires>?',(token,self.s.clock()))
        if not binding: raise AppError('The group connection code is invalid or expired.')
        if uid not in (binding['actor'],binding['submitter']):raise AppError('Only the project\'s representative or the admin who created this code has access.',403)
        p=self.s.project(binding['actor'],binding['project_id'],'send')
        existing=self.s.one('SELECT * FROM groups WHERE chat_id=? OR project_id=?',(chat['id'],p['id']))
        if existing and (existing['project_id']!=p['id'] or existing['chat_id']!=chat['id']): raise AppError('This group or project is already connected elsewhere.')
        self.s.db.execute('INSERT INTO groups VALUES(?,?,?,?,?) ON CONFLICT(chat_id) DO UPDATE SET active=1,name=excluded.name,consent_actor=excluded.consent_actor',(chat['id'],p['id'],chat.get('title','Group'),1,uid))
        self.s.db.execute('UPDATE bindings SET used=1 WHERE token=?',(token,))
        self.s.audit(uid,'group_connected',p['space_id'],p['id'],details={'chat_id':chat['id']})
        self.send(chat['id'],'This group is connected for approved invitations to '+p['general']['name']+'. Regular group messages are not collected.')

    def process(self,update,verified_group_admin=False):
        if 'message' in update:
            m=update['message']
            if m.get('migrate_to_chat_id'):
                old,new=m['chat']['id'],m['migrate_to_chat_id']
                collision=self.s.one('SELECT * FROM groups WHERE chat_id=?',(new,))
                if collision:raise AppError('The new group destination is already connected. Check the dashboard.')
                self.s.db.execute('UPDATE groups SET chat_id=? WHERE chat_id=?',(new,old))
                pending=self.s.rows("SELECT r.id,r.outbox_id,o.payload FROM recipients r JOIN campaigns c ON c.id=r.campaign_id LEFT JOIN outbox o ON o.id=r.outbox_id WHERE r.chat_id=? AND r.kind='group' AND (o.state='pending' OR c.state='draft')",(old,))
                for recipient in pending:
                    self.s.db.execute('UPDATE recipients SET chat_id=? WHERE id=?',(new,recipient['id']))
                    if recipient['outbox_id']:
                        payload=json.loads(recipient['payload']);payload['chat_id']=new
                        self.s.db.execute("UPDATE outbox SET payload=? WHERE id=? AND state='pending'",(dumps(payload),recipient['outbox_id']))
                return
            if 'from' in m: self.message(m,verified_group_admin)
        elif 'callback_query' in update: self.callback(update['callback_query'])
        elif 'my_chat_member' in update:
            m=update['my_chat_member']; status=m['new_chat_member']['status']
            if status in ('left','kicked','restricted'):
                self.s.db.execute('UPDATE groups SET active=0 WHERE chat_id=?',(m['chat']['id'],))
