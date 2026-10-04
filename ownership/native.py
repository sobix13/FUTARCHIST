"""Native Telegram admin screens. No browser is required for these operations."""
from __future__ import annotations
import json
import secrets
from datetime import datetime, timezone
from .core import AppError, PERMISSIONS, PRESETS, dumps
from .forms import FIELDS, label, validate, questions
from .management import Management, GENERAL_FIELDS, RAISE_FIELDS, EVENT_KINDS, parse_time
from .service import Service
from .health import Health
from .exports import DATASETS

TITLES={'projects':'Cases','cases':'Branches and assignments','raise':'Raise','notes':'Notes','events':'Programs','tasks':'Tasks','campaigns':'Invitations','activity':'Activity','routes':'Access codes','groups':'Groups','all':'All permitted datasets'}
OPTIONS={'purpose':['general','raise','both'],'status':['new','reviewing','followup','accepted','closed'],'participation':['planned','invited','confirmed','attended','declined','remove']}
PERMISSION_NAMES={'read_general':'Read general information','write_general':'Edit general information','read_raise':'Read raise information','write_raise':'Edit raise information','send':'Send questions and invitations','assign':'Assign reviewers','export':'Download exports','routes':'Create access codes'}
FILTER_NAMES={'search':'Search','categories':'Areas','stage':'Product stage','network':'Network environment','purpose':'Branch','status':'Review status','assignee':'Assignee','source_admin':'Source admin','raise_status':'Raise status','retry':'Retry plan','metadao':'MetaDAO','platform':'Platform','currency':'Currency','min_target':'Minimum target','max_target':'Maximum target','min_raised':'Minimum raised','max_raised':'Maximum raised'}

class NativeAdmin:
    def __init__(self,bot):self.bot=bot;self.s=bot.s;self.svc=Service(self.s,bot.name);self.m=Management(self.s,self.svc);self.health=Health(self.s)

    def flow(self,uid):
        r=self.s.one('SELECT data FROM native_flows WHERE user_id=?',(uid,))
        return json.loads(r['data']) if r else {}

    def save(self,uid,f):
        self.s.db.execute('INSERT INTO native_flows VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at',(uid,dumps(f),self.s.clock()))

    def screen(self,uid,text,rows,f=None):
        f=self.flow(uid) if f is None else f;f['nonce']=secrets.token_hex(4);self.save(uid,f)
        buttons=[[{'text':title,'callback_data':'a:'+f['nonce']+':'+action} for title,action in row] for row in rows]
        buttons.append([{'text':'Guide','callback_data':'guide'}])
        self.bot.send(uid,text,buttons)

    def actor(self,uid):
        if self.s.actor(uid)['role'] not in ('owner','admin'):raise AppError('Management is restricted to approved admins.',403)

    def permission(self,uid,key):return key in self.s.permissions(uid,self.flow(uid).get('space',0))

    def listing(self,uid,menu,text,rows,tail):
        f=self.flow(uid);offset=f.get('pages',{}).get(menu,0);offset=max(0,min(offset,max(0,((len(rows)-1)//20)*20)))
        navigation=[]
        if offset:navigation.append(('Previous page','page:'+menu+':'+str(offset-20)))
        if offset+20<len(rows):navigation.append(('Next page','page:'+menu+':'+str(offset+20)))
        self.screen(uid,text+f'\n{len(rows)} items · Page {offset//20+1}',rows[offset:offset+20]+([navigation] if navigation else [])+tail,f)

    def open(self,uid,sid=None):
        self.actor(uid);spaces=self.s.spaces(uid);f=self.flow(uid);f.pop('form',None)
        sid=sid or f.get('space')
        if not any(s['id']==sid for s in spaces):sid=spaces[0]['id'] if spaces else None
        f.update(space=sid,page='home');self.save(uid,f)
        if not sid:
            self.screen(uid,'No active workspace. Workspace access must be enabled.',[[('Manage workspaces','workspaces'),('Create team','newteam')],[('Health','health')]] if self.s.actor(uid)['role']=='owner' else [],f);return
        space=next(s for s in spaces if s['id']==sid);projects=self.s.projects(uid,sid)
        text=f"FUTARCHIST\n{space['name']}\n{len(projects)} Project · {len(self.m.tasks(uid,sid))} Task\nEach action records the person and their Telegram ID."
        rows=[[('Cases','projects'),('Programs','events')],[('Tasks','tasks'),('Switch workspace','spaces')],[('Filters','filters')]]
        for perm,title,action in [('routes','Access codes','routes'),('send','Invitations','campaigns'),('export','Export Excel / CSV','exports')]:
            if perm in space['permissions']:rows.append([(title,action)])
        if self.s.actor(uid)['role']=='owner':rows += [[('Admins','admins'),('Create team','newteam')],[('Membership and permissions','membership'),('Bot text','texts')],[('Manage workspaces','workspaces'),('Health and troubleshooting','health')]]
        if self.bot.app_url.startswith('https://'):rows.insert(0,[('Open dashboard','panel')])
        self.screen(uid,text+'\n\nBuilt by Ownership',rows,f)

    def message(self,uid,text):
        if text in ('/manage','/admin','/panel','/health','/repair','/code','/export'):
            self.actor(uid)
            if text in ('/manage','/admin'):self.open(uid)
            else:
                if not self.flow(uid).get('space'):self.open(uid)
                if text=='/panel' and not self.bot.app_url.startswith('https://'):self.open(uid)
                else:self.handle(uid,{'/panel':'panel','/health':'health','/repair':'repair','/code':'routes','/export':'exports'}[text])
            return True
        f=self.flow(uid)
        if text.startswith('/') and text not in ('/back','/cancel'):
            if text in ('/start','/projects','/resume') or text.startswith('/start '):
                f.pop('form',None);f['nonce']=secrets.token_hex(4);self.save(uid,f)
            return False
        if not f.get('form'):return False
        self.actor(uid)
        if text=='/cancel':f.pop('form',None);self.save(uid,f);self.open(uid);return True
        if text=='/back':f['form']['index']=max(0,f['form']['index']-1);self.save(uid,f);self.prompt(uid);return True
        spec=f['form']['fields'][f['form']['index']]
        if spec.get('options') or spec.get('multi'):raise AppError('Use the options in the latest message.')
        self.consume(uid,text);return True

    def callback(self,uid,data,cb):
        self.actor(uid)
        if data=='admin':self.open(uid);return
        f=self.flow(uid)
        if not data.startswith('a:'+f.get('nonce','')+':'):
            self.bot.send(uid,'This option is old. Open /manage again.');return
        action=data.split(':',2)[2]
        if action=='cancel':self.open(uid);return
        if f.get('form'):
            spec=f['form']['fields'][f['form']['index']]
            if action.startswith('val:'):
                values=spec.get('options',[])
                try:idx=int(action[4:])
                except ValueError:raise AppError('Invalid option.') from None
                if not 0<=idx<len(values):raise AppError('Invalid option.')
                self.consume(uid,values[idx]);return
            if action.startswith('multi:'):
                values=spec.get('multi',[])
                try:idx=int(action[6:])
                except ValueError:raise AppError('Invalid option.') from None
                if not 0<=idx<len(values):raise AppError('Invalid option.')
                value=values[idx];selected=f['form'].setdefault('selected',[])
                if value in selected:selected.remove(value)
                else:selected.append(value)
                if spec['key']=='permissions':
                    if value=='read_general' and value not in selected:selected.clear()
                    elif value=='read_raise' and value not in selected:
                        if 'write_raise' in selected:selected.remove('write_raise')
                    else:
                        if selected and 'read_general' not in selected:selected.append('read_general')
                        if 'write_raise' in selected and 'read_raise' not in selected:selected.append('read_raise')
                self.save(uid,f);self.prompt(uid);return
            if action=='done':self.consume(uid,f['form'].get('selected',[]));return
            if action=='skip':self.consume(uid,spec.get('default'));return
            if action=='clear' and spec.get('clear'):self.consume(uid,None);return
            if action=='back':f['form']['index']=max(0,f['form']['index']-1);self.save(uid,f);self.prompt(uid);return
            raise AppError('This option does not match the current step.')
        try:self.handle(uid,action)
        except (ValueError,IndexError,OverflowError):raise AppError('Invalid option. Open /manage again.') from None

    def begin(self,uid,kind,fields,context=None):
        f=self.flow(uid);f['form']={'kind':kind,'fields':fields,'context':context or {},'index':0,'answers':{}}
        self.save(uid,f);self.prompt(uid)

    def prompt(self,uid):
        f=self.flow(uid);form=f['form'];spec=form['fields'][form['index']]
        rows=[];text=f"{form['index']+1} / {len(form['fields'])}\n{spec['title']}"
        values=spec.get('options') or spec.get('multi')
        if values:
            names=spec.get('names',{})
            for i in range(0,len(values),2):
                rows.append([(('+ ' if value in form.get('selected',[]) else '')+str(names.get(str(value),label(str(value)))) ,('multi:' if spec.get('multi') else 'val:')+str(n)) for n,value in enumerate(values[i:i+2],i)])
            if spec.get('multi'):rows.append([('Confirm selections','done')])
        if 'default' in spec:
            text+='\nCurrent value: '+str(spec['default'] if spec['default'] is not None else 'Empty')
            rows.append([('Keep current value / skip','skip')])
        if spec.get('clear') and spec.get('default') is not None:rows.append([('Clear this value','clear')])
        if form['index']:rows.append([('Back','back')])
        rows.append([('Cancel','cancel')]);self.screen(uid,text,rows,f)

    def consume(self,uid,value):
        f=self.flow(uid);form=f['form'];spec=form['fields'][form['index']];key=spec['key']
        if value is None and 'default' not in spec:raise AppError('This value is required.')
        if spec.get('type')=='int' and value is not None:
            try:
                value=int(str(value).translate(str.maketrans(''.join(chr(i) for i in range(0x06f0,0x06fa)),'0123456789')))
                if not 0<value<=9_223_372_036_854_775_807:raise ValueError()
            except ValueError:raise AppError('Enter a positive ID or number.') from None
        if spec.get('validate') in FIELDS:value=validate(spec['validate'],value)
        if key=='template' and value is not None:self.svc.validate_template(value)
        form['answers'][key]=value;form.pop('selected',None);form['index']+=1
        if key=='currency' and value!='OTHER':form['fields']=[s for s in form['fields'] if s['key']!='currency_code']
        if form['index']<len(form['fields']):self.save(uid,f);self.prompt(uid);return
        self.finish(uid,form);f=self.flow(uid);f.pop('form',None);self.save(uid,f)

    def finish(self,uid,form):
        d=form['answers'];ctx=form['context'];kind=form['kind'];sid=self.flow(uid)['space']
        destination='home'
        if kind=='admin':
            self.s.add_admin(uid,d['user_id'],d['name']);personal=self.s.one("SELECT id FROM spaces WHERE creator=? AND kind='personal'",(d['user_id'],));r=self.s.default_route(d['user_id'],personal['id'])
            self.bot.send(uid,'Admin added. Their personal code:\n'+r['token']+'\nhttps://t.me/'+self.bot.name+'?start=intake_'+r['token']);destination='admins'
        elif kind=='team':self.s.team(uid,d['name']);destination='spaces'
        elif kind=='space_name':self.m.rename_space(uid,ctx['id'],d['name']);destination='workspaces'
        elif kind=='member':self.s.membership(uid,sid,d['user_id'],d['permissions']);destination='home'
        elif kind=='route':self.s.route(uid,sid,d['name'],d['purpose'],d['assignee']);destination='routes'
        elif kind=='route_config':
            if d.get('expires'):d['expires']=parse_time(d['expires'],'UTC')
            self.m.configure_route(uid,ctx['id'],d);destination='routes'
        elif kind=='project':self.m.edit_project(uid,ctx['id'],ctx['version'],d,ctx['purpose']);destination='project:'+str(ctx['id'])
        elif kind=='note':self.s.note(uid,ctx['id'],d['purpose'],d['text'],d['visibility']=='guest',self.bot.name);destination='project:'+str(ctx['id'])
        elif kind=='edit_note':self.m.edit_note(uid,ctx['id'],ctx['version'],d['text']);destination='project:'+str(ctx['pid'])
        elif kind=='case':self.s.update_case(uid,ctx['id'],ctx['version'],**d);destination='project:'+str(ctx['pid'])
        elif kind=='filter':
            f=self.flow(uid);filters=f.get('filters',{}).copy()
            for key,value in d.items():
                if value in (None,'',[]):filters.pop(key,None)
                else:filters[key]=value
            self.s.projects(uid,sid,filters);f['filters']=filters;self.save(uid,f);destination='filters'
        elif kind=='view':self.svc.save_view(uid,sid,d['name'],self.flow(uid).get('filters',{}));destination='views'
        elif kind=='campaign':
            campaign=self.svc.campaign(uid,sid,d['topic'],d['when'],d['template'],self.flow(uid).get('filters',{}));destination='campaign:'+str(campaign['id'])
        elif kind=='event':self.m.save_event(uid,sid,d);destination='events'
        elif kind=='event_edit':self.m.save_event(uid,sid,{**d,'version':ctx['version']},ctx['id']);destination='event:'+str(ctx['id'])
        elif kind=='event_project':self.m.link_event(uid,ctx['id'],d['project_id'],d['participation']);destination='event:'+str(ctx['id'])
        elif kind=='task':self.m.save_task(uid,sid,d);destination='tasks'
        elif kind=='task_edit':self.m.save_task(uid,sid,{**d,'version':ctx['version']},ctx['id']);destination='tasks'
        elif kind=='text':self.m.set_text(uid,ctx['key'],d['text'],ctx['version']);destination='texts'
        elif kind=='retry':self.health.retry_update(uid,d['update_id']);destination='health'
        else:raise AppError('Invalid admin form.')
        f=self.flow(uid);f.pop('form',None);self.save(uid,f);self.handle(uid,destination)

    def field(self,key,title=None,options=None,default=...):
        s={'key':key,'title':title or key}
        if key in FIELDS:s.update(title=title or FIELDS[key][0],validate=key,clear=not FIELDS[key][2])
        if key in FIELDS and isinstance(FIELDS[key][1],list):options=FIELDS[key][1]
        if options:s['multi' if key in ('categories','permissions') else 'options']=options
        if default is not ...:s['default']=default
        if key in ('max_uses','bound_user','expires','due_at','project_id','event_id','topic','description','outcome'):s['clear']=True
        if key=='permissions':s['names']=PERMISSION_NAMES
        if key in ('user_id','assignee','project_id','event_id','max_uses','bound_user','update_id'):s['type']='int'
        return s

    def handle(self,uid,action):
        self.actor(uid);f=self.flow(uid);sid=f.get('space');owner=self.s.actor(uid)['role']=='owner'
        if action=='home':self.open(uid);return
        if action.startswith('page:'):
            menu,offset=action[5:].rsplit(':',1);offset=int(offset)
            if offset<0 or offset>1_000_000:raise AppError('Invalid page.')
            f.setdefault('pages',{})[menu]=offset;self.save(uid,f);self.handle(uid,menu);return
        if action=='panel':
            if not self.bot.app_url.startswith('https://'):raise AppError('The web panel has no HTTPS address yet. Telegram management is available.')
            token=self.s.login_link(uid);self.bot.send(uid,'Personal login link, valid for 5 minutes:\n'+self.bot.app_url+'/?login='+token);return
        if action=='spaces':
            spaces=self.s.spaces(uid);self.listing(uid,'spaces','Select a personal or team workspace.',[[(s['name'],'space:'+str(s['id']))] for s in spaces],[[('Back','home')]]);return
        if action=='workspaces':
            self.s.owner(uid);spaces=self.s.rows('SELECT * FROM spaces ORDER BY id')
            self.listing(uid,'workspaces','Active and inactive workspaces. Disabling a workspace keeps its data.',[[(s['name']+' · '+('Active' if s['active'] else 'Inactive'),'workspace:'+str(s['id']))] for s in spaces],[[('Create team','newteam')],[('Back','home')]]);return
        if action.startswith('workspace:'):
            self.s.owner(uid);space=self.s.one('SELECT * FROM spaces WHERE id=?',(int(action[10:]),))
            if not space:raise AppError('Workspace not found.',404)
            self.screen(uid,space['name']+' · '+str(space['id']),[[('Rename','space_name:'+str(space['id']))],[('Disable' if space['active'] else 'Activate','prepare:'+('disable_space' if space['active'] else 'enable_space')+':'+str(space['id']))],[('Back','workspaces')]]);return
        if action.startswith('space_name:'):
            self.s.owner(uid);space=self.s.one('SELECT * FROM spaces WHERE id=?',(int(action[11:]),))
            if not space:raise AppError('Workspace not found.',404)
            self.begin(uid,'space_name',[self.field('name','Workspace name',default=space['name'])],{'id':space['id']});return
        if action.startswith('prepare:') and action.split(':')[1] in ('enable_space','disable_space'):
            self.s.owner(uid);_,operation,identifier=action.split(':');space=self.s.one('SELECT * FROM spaces WHERE id=?',(int(identifier),))
            if not space:raise AppError('Workspace not found.',404)
            c=self.m.prepare(uid,operation,{'id':space['id'],'active':space['active']});self.screen(uid,'Confirm the status change for '+space['name']+'.',[[('Confirm action','confirm:'+c['token'])],[('Cancel','workspaces')]]);return
        if action.startswith('space:'):
            self.s.check(uid,int(action[6:]),'read_general');f.update(space=int(action[6:]),filters={});self.save(uid,f);self.open(uid);return
        globals={'admins','newadmin','newteam','texts','health','repair','backup','retry','confirm'}
        if action.split(':')[0] in globals:self.s.owner(uid)
        else:
            if not sid:raise AppError('Select a workspace.')
            self.s.check(uid,sid,'read_general')
        if action in ('projects','archived'):
            filters={**f.get('filters',{})}
            if action=='archived':self.s.owner(uid);filters['archived']='only'
            projects=self.s.projects(uid,sid,filters)
            rows=[[(p['general']['name']+' · '+str(p['id']),'project:'+str(p['id']))] for p in projects]
            self.listing(uid,action,'Cases matching the current filters.',rows,[[('Filters','filters')]]+([[('Archive','archived')]] if owner and action!='archived' else [])+[[('Back','home')]]);return
        if action.startswith('project:'):
            pid=int(action[8:]);p=self.s.project(uid,pid,include_archived=owner);g=p['general'];text=f"{g['name']} · Case {pid}\nRepresentative: {g.get('contact','')} · {p['submitter']}\nAreas: {', '.join(label(x) for x in g['categories'])}\nStage: {label(g['stage'])} · {g['network']}\nProduct: {g.get('website') or 'Not provided'}\nReason for building: {g.get('motivation') or 'Not provided'}\nSocial links: {g.get('socials') or 'Not provided'}"
            for c in p['cases']:text+=f"\n{label(c['purpose'])}: {c['status']} · Intake {c['source_name']} / {c['source_admin']} · Assignee {c['assignee_name']} / {c['assignee']}"
            if p['fundraising']:text+='\n\nRaise:\n'+'\n'.join(str(k)+': '+str(v) for k,v in p['fundraising'].items())
            rows=[]
            if not p['archived_at']:
                for purpose in ('general','raise'):
                    if self.permission(uid,'write_'+purpose) and any(c['purpose']==purpose for c in p['cases']):rows.append([('Edit '+label(purpose),'pedit:'+str(pid)+':'+purpose)])
                for c in p['cases']:
                    if self.permission(uid,'write_'+c['purpose']):rows.append([('Status '+label(c['purpose']),'case:'+str(c['id']))]+([('Assignee '+label(c['purpose']),'assign:'+str(c['id']))] if self.permission(uid,'assign') else []))
                if any(self.permission(uid,'write_'+c['purpose']) for c in p['cases']):rows.append([('Note / question','note:'+str(pid))])
                if self.permission(uid,'send'):rows.append([('Connect group','bind:'+str(pid)),('Disconnect group','unbind:'+str(pid))])
            rows.append([('History and notes','history:'+str(pid))])
            if owner:rows.append([('Restore' if p['archived_at'] else 'Archive','prepare:'+('restore_project' if p['archived_at'] else 'archive_project')+':'+str(pid))])
            if owner and p['archived_at']:rows.append([('Permanently delete data','prepare:purge_project:'+str(pid))])
            self.screen(uid,text,rows+[[('Back','projects')]]);return
        if action.startswith('pedit:'):
            _,p,purpose=action.split(':');pid=int(p);project=self.s.project(uid,pid,'write_'+purpose)
            fields=GENERAL_FIELDS if purpose=='general' else RAISE_FIELDS
            if purpose=='raise':
                answers={**project['general'],**(project['fundraising'] or {})}
                if answers.get('currency') not in FIELDS['currency'][1] and answers.get('currency') is not None:answers['currency']='OTHER'
                fields=[k for k in fields if k in questions('raise',answers)]
            self.screen(uid,'Select a field to edit.',[[(key,'pf:'+str(pid)+':'+purpose+':'+key)] for key in fields]+[[('Back','project:'+p)]]);return
        if action.startswith('pf:'):
            _,p,purpose,key=action.split(':');project=self.s.project(uid,int(p),'write_'+purpose)
            current=(project['general'] if purpose=='general' else project['fundraising']).get(key)
            if key=='currency_code':current=project['fundraising'].get('currency') if project['fundraising'].get('currency') not in FIELDS['currency'][1] else None
            if key not in (GENERAL_FIELDS if purpose=='general' else RAISE_FIELDS):raise AppError('Invalid field.')
            custom=key=='currency' and current not in FIELDS['currency'][1] and current is not None
            spec=self.field(key,default='OTHER' if custom else current);fields=[spec]
            if key=='currency':fields.append(self.field('currency_code',default=current if custom else 'GBP'))
            self.begin(uid,'project',fields,{'id':int(p),'version':project['version'],'purpose':purpose});return
        if action.startswith(('case:','assign:')):
            kind,cid=action.split(':');case=self.s.one('SELECT * FROM cases WHERE id=?',(int(cid),))
            if not case:raise AppError('Branch not found.',404)
            p=self.s.project(uid,case['project_id'],'write_'+case['purpose'])
            field=self.field('status','Branch status',OPTIONS['status'],case['status']) if kind=='case' else self.field('assignee','Authorized assignee ID',default=case['assignee'])
            self.begin(uid,'case',[field],{'id':case['id'],'pid':p['id'],'version':case['version']});return
        if action.startswith('note:'):
            p=self.s.project(uid,int(action[5:]));purposes=[c['purpose'] for c in p['cases'] if self.permission(uid,'write_'+c['purpose'])]
            fields=[self.field('purpose','Note branch',purposes),self.field('visibility','Note type',['internal','guest'] if self.permission(uid,'send') else ['internal']),self.field('text','Note or question text')]
            self.begin(uid,'note',fields,{'id':p['id']});return
        if action.startswith('history:'):
            pid=int(action[8:]);history=self.s.history(uid,pid,include_archived=owner)
            rows=[[(str(t['id'])+' · '+t['actor_name']+' · '+t['text'][:50],'thread:'+str(t['id']))] for t in reversed(history['threads'])]
            self.listing(uid,action,'Questions, replies and notes for case '+str(pid),rows,[[('Action history','audit:'+str(pid))],[('Back','project:'+str(pid))]]);return
        if action.startswith('thread:'):
            t=self.s.one('SELECT * FROM threads WHERE id=? AND deleted_at IS NULL',(int(action[7:]),))
            if not t:raise AppError('Note not found.',404)
            p=self.s.project(uid,t['project_id'],include_archived=owner);self.s.check(uid,p['space_id'],'read_'+t['purpose']);rows=[]
            if not p['archived_at'] and t['visibility']=='internal' and self.permission(uid,'write_'+t['purpose']) and (owner or t['actor']==uid):rows.append([('Edit','nedit:'+str(t['id']))]+([('Delete','prepare:delete_note:'+str(t['id']))] if owner else []))
            author=self.s.one('SELECT name FROM users WHERE id=?',(t['actor'],))
            self.screen(uid,str(t['id'])+' · '+label(t['purpose'])+' · '+t['visibility']+'\nRecorded by: '+author['name']+' / '+str(t['actor'])+'\n\n'+t['text'],rows+[[('Back','history:'+str(p['id']))]]);return
        if action.startswith('audit:'):
            pid=int(action[6:]);p=self.s.project(uid,pid,include_archived=owner);audit=[a for a in self.svc.audit(uid,p['space_id'],limit=None) if a['project_id']==pid]
            self.listing(uid,action,'Action history for case '+str(pid),[[(a['actor_name']+' / '+str(a['actor'])+' · '+a['action'],'log:'+str(a['id']))] for a in audit],[[('Back','history:'+str(pid))]]);return
        if action.startswith('log:'):
            row=self.s.one('SELECT a.*,u.name actor_name FROM activity a JOIN users u ON u.id=a.actor WHERE a.id=?',(int(action[4:]),))
            if not row or not row['project_id']:raise AppError('Activity not found.',404)
            self.s.project(uid,row['project_id'],include_archived=owner);self.s.check(uid,row['space_id'],'read_'+row['purpose'])
            self.screen(uid,row['actor_name']+' / '+str(row['actor'])+'\n'+row['action']+' · '+label(row['purpose'])+'\n'+datetime.fromtimestamp(row['created_at'],timezone.utc).isoformat()+'\n'+row['details'],[[('Back','audit:'+str(row['project_id']))]]);return
        if action.startswith('nedit:'):
            t=self.s.one('SELECT * FROM threads WHERE id=?',(int(action[6:]),))
            if not t:raise AppError('Note not found.',404)
            self.s.project(uid,t['project_id'],'write_'+t['purpose']);self.begin(uid,'edit_note',[self.field('text','Note text',default=t['text'])],{'id':t['id'],'pid':t['project_id'],'version':t['version']});return
        if action.startswith(('bind:','unbind:')):
            kind,pid=action.split(':')
            if kind=='bind':r=self.svc.binding(uid,int(pid));self.bot.send(uid,r['command']+'\n'+r['instruction'])
            else:self.svc.group(uid,int(pid),True);self.bot.send(uid,'Group disconnected.')
            return
        if action=='routes':
            routes=self.svc.routes(uid,sid);self.listing(uid,'routes','Workspace codes. A code or link opens the form for its assigned route.',[[(r['name']+' · '+('Active' if r['active'] else 'Inactive'),'route:'+str(r['id']))] for r in routes if r['token']!='public'],[[('Create code','newroute')],[('Back','home')]]);return
        if action=='newroute':self.begin(uid,'route',[self.field('name','Route name'),self.field('purpose','Form type',OPTIONS['purpose'] if self.permission(uid,'read_raise') else ['general']),self.field('assignee','Assigned admin ID',default=uid)]);return
        if action.startswith('route:'):
            rid=int(action[6:]);route=next((r for r in self.svc.routes(uid,sid) if r['id']==rid),None)
            if not route:raise AppError('This code is not in this workspace.',403)
            text=f"{route['name']}\nAccess code: {route['token']}\n{route['url']}\nSource: {route['source_name']} / {route['creator']}\nActivations: {route['uses']} · Limit: {route['max_uses'] or 'Unlimited'}\nRestricted to ID: {route['bound_user'] or 'Not set'}\nExpiry UTC: {datetime.fromtimestamp(route['expires'],timezone.utc).isoformat() if route['expires'] else 'No expiry'}"
            self.screen(uid,text,[[('Edit name and limits','rconfig:'+str(rid)),('Disable / enable','rtoggle:'+str(rid))],[('Manage code access','grants:'+str(rid)),('Rotate code','rrotate:'+str(rid))],[('Back','routes')]]);return
        if action.startswith('rrotate:'):
            new=self.m.rotate_route(uid,int(action[8:]));self.handle(uid,'route:'+str(new['id']));return
        if action.startswith('grants:'):
            rid=int(action[7:]);grants=self.m.grants(uid,rid)
            self.listing(uid,action,'Select a person to close or restore access.',[[(g['name']+' · '+str(g['user_id'])+' · '+('Active' if g['active'] else 'Closed'),'grant_toggle:'+str(rid)+':'+str(g['user_id']))] for g in grants],[[('Back','route:'+str(rid))]]);return
        if action.startswith('grant_toggle:'):
            _,rid,guest=action.split(':');grant=next((g for g in self.m.grants(uid,int(rid)) if g['user_id']==int(guest)),None)
            if not grant:raise AppError('Activation not found.',404)
            self.m.revoke_grant(uid,int(rid),int(guest),not grant['active']);self.handle(uid,'grants:'+rid);return
        if action.startswith('rtoggle:'):
            r=self.s.one('SELECT * FROM routes WHERE id=?',(int(action[8:]),));self.m.configure_route(uid,r['id'],{'active':not r['active']});self.handle(uid,'routes');return
        if action.startswith('rconfig:'):
            r=self.s.one('SELECT * FROM routes WHERE id=?',(int(action[8:]),))
            if not r:raise AppError('Access code not found.',404)
            self.s.check(uid,r['space_id'],'routes')
            self.begin(uid,'route_config',[self.field('name','Code name',default=r['name']),self.field('max_uses','Activation limit. Skip for unlimited.',default=r['max_uses']),self.field('bound_user','Specific Telegram ID. Skip to leave it unrestricted.',default=r['bound_user']),self.field('expires','Expiry UTC, e.g. 2026-10-10 18:00',default=None)],{'id':r['id']});return
        if action=='filters':
            keys=['search','categories','stage','network','purpose','status','assignee','source_admin']
            if self.permission(uid,'read_raise'):keys+=['raise_status','retry','metadao','platform','currency','min_target','max_target','min_raised','max_raised']
            self.screen(uid,'Current filters:\n'+dumps(f.get('filters',{}))+'\nFor amount filters, set the currency first. Different criteria apply together.',[[(FILTER_NAMES[key],'filter:'+key)] for key in keys]+[[('Clear filters','clearfilters'),('Show results','projects')],[('Save filter','saveview'),('Saved filters','views')],[('Back','home')]]);return
        if action=='saveview':self.begin(uid,'view',[self.field('name','Filter name')]);return
        if action=='views':self.listing(uid,'views','Your saved filters in this workspace.',[[(v['name'],'view:'+str(v['id']))] for v in self.svc.views(uid,sid)],[[('Back','filters')]]);return
        if action.startswith('view:'):
            v=next((v for v in self.svc.views(uid,sid) if v['id']==int(action[5:])),None)
            if not v:raise AppError('Filter not found.',404)
            self.screen(uid,v['name']+'\n'+dumps(v['filters']),[[('Apply filters','useview:'+str(v['id'])),('Delete filter','delview:'+str(v['id']))],[('Back','views')]]);return
        if action.startswith('useview:'):
            v=next((v for v in self.svc.views(uid,sid) if v['id']==int(action[8:])),None)
            if not v:raise AppError('Filter not found.',404)
            f['filters']=v['filters'];self.save(uid,f);self.handle(uid,'projects');return
        if action.startswith('delview:'):self.svc.delete_view(uid,int(action[8:]));self.handle(uid,'views');return
        if action=='clearfilters':f['filters']={};self.save(uid,f);self.handle(uid,'filters');return
        if action.startswith('filter:'):
            key=action[7:];opts=OPTIONS.get(key)
            spec=self.field(key,'Value '+key,opts,default=None)
            if key=='purpose':spec['options']=['general','raise'] if self.permission(uid,'read_raise') else ['general']
            if key in ('raise_status','retry','metadao','categories','stage','network'):spec.pop('validate',None)
            self.begin(uid,'filter',[spec]);return
        if action=='campaigns':self.screen(uid,'Invitations are sent after preview confirmation.',[[(c['topic'],'campaign:'+str(c['id']))] for c in self.svc.campaigns(uid,sid)[:20]]+[[('New invitation with current filters','newcampaign')],[('Back','home')]]);return
        if action=='newcampaign':
            self.s.check(uid,sid,'send');self.begin(uid,'campaign',[self.field('topic','Invitation topic'),self.field('when','Date and time, including timezone'),self.field('template','Text. Variables: {project} {topic} {when} {sector}',default=self.m.text('invite_template'))]);return
        if action.startswith('campaign:'):
            c=self.svc.campaign_detail(uid,int(action[9:]));text=f"{c['topic']}\n{c['when_text']}\nStatus: {c['state']} · {len(c['recipients'])} destinations\n"
            for r in c['recipients'][:8]:text+='\n'+r['project_name']+' · '+r['kind']+'\n'+r['text']+'\n'
            rows=[]
            if c['state']=='draft' and c['recipients']:rows.append([('Confirm and send to '+str(len(c['recipients']))+' destinations','csend:'+str(c['id']))])
            if c['state']!='cancelled':rows.append([('Cancel invitation / remaining deliveries','ccancel:'+str(c['id']))])
            self.screen(uid,text,rows+[[('Back','campaigns')]]);return
        if action.startswith('csend:'):self.svc.confirm(uid,int(action[6:]));self.handle(uid,'campaign:'+action[6:]);return
        if action.startswith('ccancel:'):self.svc.cancel(uid,int(action[8:]));self.handle(uid,'campaigns');return
        if action in ('events','archived_events'):
            self.listing(uid,action,'Past and upcoming programs in this workspace.',[[(e['title']+' · '+e['status'],'event:'+str(e['id']))] for e in self.m.events(uid,sid,action=='archived_events')],([[('Create program','newevent')]] if self.permission(uid,'write_general') or self.permission(uid,'write_raise') else [])+([[('Archived programs','archived_events')]] if owner and action=='events' else [])+[[('Back','home')]]);return
        if action=='newevent':
            self.begin(uid,'event',[self.field('title','Program name'),self.field('kind','Program type',[k for k in EVENT_KINDS if self.permission(uid,'write_raise' if k=='raise' else 'write_general')]),self.field('topic','Topic',default=''),self.field('timezone','Timezone',default='UTC'),self.field('starts_at','Time, e.g. 2026-10-10 18:00'),self.field('description','Description',default='')]);return
        if action.startswith('event:'):
            e=self.m.event(uid,int(action[6:]),include_archived=owner);rows=[]
            if not e['archived_at'] and self.permission(uid,'write_raise' if e['kind']=='raise' else 'write_general'):rows.append([('Edit program','eedit:'+str(e['id'])),('Record project participation','elink:'+str(e['id']))])
            if owner:rows.append([('Restore' if e['archived_at'] else 'Archive','prepare:'+('restore_event' if e['archived_at'] else 'archive_event')+':'+str(e['id']))])
            self.screen(uid,f"{e['title']}\n{e['kind']} · {e['status']}\n{datetime.fromtimestamp(e['starts_at'],timezone.utc).isoformat()}\nTimezone: {e['timezone']}\n{e['description']}\nOutcome: {e['outcome']}\n"+'\n'.join(p['name']+' · '+p['participation'] for p in e['projects']),rows+[[('Back','events')]]);return
        if action.startswith('eedit:'):
            e=self.m.event(uid,int(action[6:]));fields=[self.field('title','Program name',default=e['title']),self.field('status','Status',['planned','confirmed','completed','cancelled'],e['status']),self.field('timezone','Timezone',default=e['timezone']),self.field('starts_at','Date ISO with offset, or keep the current value',default=e['starts_at']),self.field('description','Description',default=e['description']),self.field('outcome','Program outcome',default=e['outcome'])];self.begin(uid,'event_edit',fields,{'id':e['id'],'version':e['version']});return
        if action.startswith('elink:'):self.m.event(uid,int(action[6:]));self.begin(uid,'event_project',[self.field('project_id','Case ID in this workspace'),self.field('participation','Participation status',OPTIONS['participation'])],{'id':int(action[6:])});return
        if action in ('tasks','archived_tasks'):
            self.listing(uid,action,'Tasks and their assignees.',[[(t['title']+' · '+t['assignee_name']+' · '+t['status'],'task:'+str(t['id']))] for t in self.m.tasks(uid,sid,action=='archived_tasks')],([[('New task','newtask')]] if self.permission(uid,'write_general') or self.permission(uid,'write_raise') else [])+([[('Archived tasks','archived_tasks')]] if owner and action=='tasks' else [])+[[('Back','home')]]);return
        if action=='newtask':self.begin(uid,'task',[self.field('title','Task title'),self.field('purpose','Branch',[p for p in ('general','raise') if self.permission(uid,'write_'+p)]),self.field('assignee','Assignee ID',default=uid),self.field('timezone','Timezone',default='UTC'),self.field('due_at','Due time, e.g. 2026-10-10 18:00',default=None),self.field('project_id','Linked project ID, optional',default=None),self.field('event_id','Linked program ID, optional',default=None)]);return
        if action.startswith('task:'):
            tid=int(action[5:]);t=next((t for t in self.m.tasks(uid,sid)+ (self.m.tasks(uid,sid,True) if owner else []) if t['id']==tid),None)
            if not t:raise AppError('Task not found.',404)
            rows=[]
            if not t['archived_at'] and self.permission(uid,'write_'+t['purpose']):rows.append([('Edit task','tedit:'+str(tid))])
            if owner:rows.append([('Restore' if t['archived_at'] else 'Archive','prepare:'+('restore_task' if t['archived_at'] else 'archive_task')+':'+str(tid))])
            self.screen(uid,t['title']+'\nAssignee: '+t['assignee_name']+' / '+str(t['assignee'])+'\nStatus: '+t['status']+'\nProject: '+str(t['project_id'] or 'Not provided'),rows+[[('Back','tasks')]]);return
        if action.startswith('tedit:'):
            tid=int(action[6:]);t=next((t for t in self.m.tasks(uid,sid) if t['id']==tid),None)
            if not t:raise AppError('Task not found.',404)
            self.begin(uid,'task_edit',[self.field('title','Title',default=t['title']),self.field('status','Status',['open','doing','done','cancelled'],t['status']),self.field('assignee','Assignee',default=t['assignee']),self.field('due_at','Due ISO, or keep the current value',default=t['due_at'])],{'id':tid,'version':t['version']});return
        if action=='exports':
            self.s.check(uid,sid,'export');datasets=[d for d in DATASETS+('all',) if (d!='raise' or self.permission(uid,'read_raise')) and (d!='routes' or self.permission(uid,'routes')) and (d!='campaigns' or self.permission(uid,'send'))]
            self.screen(uid,'Which dataset do you want to export with the current filters?',[[(TITLES[d],'export:'+d)] for d in datasets]+[[('Back','home')]]);return
        if action.startswith('export:'):
            dataset=action[7:]
            if dataset not in DATASETS+('all',):raise AppError('Invalid export type.')
            self.screen(uid,'Select a file format. Excel includes separate worksheets for all datasets. CSV for all datasets is delivered in one ZIP file.',[[('Excel','file:'+dataset+':xlsx'),('CSV','file:'+dataset+':csv')],[('Back','exports')]]);return
        if action.startswith('file:'):
            _,dataset,format=action.split(':');from .exports import Exports
            Exports(self.s,self.svc).tables(uid,sid,dataset,f.get('filters',{}))
            self.s.queue('sendDocument',{'chat_id':uid,'caption':'FUTARCHIST · '+TITLES[dataset],'_export':{'uid':uid,'sid':sid,'dataset':dataset,'format':format,'filters':f.get('filters',{})}},sid=sid,actor=uid,permission='export'+('|read_raise' if dataset=='raise' else ''))
            self.bot.send(uid,'Export queued. Permissions are checked again when the file is generated.');return
        if action=='admins':self.s.owner(uid);self.listing(uid,'admins','Active and suspended admins.',[[(a['name']+' · '+str(a['id'])+' · '+('Active' if a['active'] else 'Suspended'),'admin:'+str(a['id']))] for a in self.svc.admins(uid)],[[('Add admin','newadmin')],[('Back','home')]]);return
        if action=='newadmin':self.s.owner(uid);self.begin(uid,'admin',[self.field('user_id','Numeric Telegram ID. Ask the person to send /id to get their ID.'),self.field('name','Admin display name')]);return
        if action.startswith('admin:'):
            self.s.owner(uid);a=self.s.one("SELECT * FROM users WHERE id=? AND role='admin'",(int(action[6:]),))
            if not a:raise AppError('Admin not found.',404)
            personal=self.s.one("SELECT id FROM spaces WHERE creator=? AND kind='personal'",(a['id'],));route=self.s.one("SELECT * FROM routes WHERE creator=? AND space_id=? AND token<>'public' AND active=1 ORDER BY id LIMIT 1",(a['id'],personal['id']))
            text=a['name']+' · '+str(a['id'])
            if route:text+='\nPersonal code: '+route['token']+'\nhttps://t.me/'+self.bot.name+'?start=intake_'+route['token']
            self.screen(uid,text,[[('Suspend' if a['active'] else 'Activate','admintoggle:'+str(a['id']))],[('Back','admins')]]);return
        if action.startswith('admintoggle:'):
            self.s.owner(uid);a=self.s.one("SELECT * FROM users WHERE id=? AND role='admin'",(int(action[12:]),))
            if not a:raise AppError('Admin not found.',404)
            self.s.deactivate(uid,a['id'],not a['active']);self.handle(uid,'admins');return
        if action=='newteam':self.s.owner(uid);self.begin(uid,'team',[self.field('name','Internal team name')]);return
        if action=='membership':self.s.owner(uid);self.begin(uid,'member',[self.field('user_id','Admin ID to add to this workspace'),self.field('permissions','Permissions. An empty selection removes membership in this workspace.',list(PERMISSIONS))]);return
        if action=='texts':self.listing(uid,'texts','Bot text and questions. Editing wording keeps field types and validation rules.',[[(t['key'],'text:'+t['key'])] for t in self.m.texts(uid)],[[('Back','home')]]);return
        if action.startswith('text:'):
            key=action[5:];t=next((t for t in self.m.texts(uid) if t['key']==key),None)
            if not t:raise AppError('Text setting not found.',404)
            self.begin(uid,'text',[self.field('text','Replacement text',default=t['value'])],{'key':key,'version':t['version']});return
        if action.startswith('prepare:'):
            _,operation,identifier=action.split(':');self.s.owner(uid);identifier=int(identifier)
            if operation.endswith('_project'):r=self.s.project(uid,identifier,include_archived=True)
            elif operation=='delete_note':r=self.s.one('SELECT * FROM threads WHERE id=?',(identifier,))
            else:r=self.s.one('SELECT * FROM '+('events' if operation.endswith('_event') else 'tasks')+' WHERE id=?',(identifier,))
            if not r:raise AppError('Item not found.',404)
            confirmation=self.m.prepare(uid,operation,{'id':identifier,'version':r['version']})
            self.screen(uid,('Permanent deletion removes the case and its stored relationships.' if operation=='purge_project' else 'This action applies to item '+str(identifier)+'.')+'\nConfirm to continue.',[[('Confirm action','confirm:'+confirmation['token'])],[('Cancel','home')]]);return
        if action.startswith('confirm:'):self.m.confirm(uid,action[8:]);self.bot.send(uid,'Action completed.');self.open(uid);return
        if action=='health':
            snapshot=self.health.snapshot(uid);text='Health FUTARCHIST\n'+'\n'.join(k+': '+v['state'] for k,v in snapshot['checks'].items())+'\nDelivery queue: '+dumps(snapshot['outbox'])+'\nFailed updates: '+str(len(snapshot['inbox']))
            for i in snapshot['incidents'][:8]:text+=f"\n{i['id']} · {i['component']} · {i['code']} · {i['state']} · {i['count']}"
            for u in snapshot['inbox'][:8]:text+='\nupdate '+str(u['update_id'])+' · '+str(u['attempts'])+' attempts · '+str(u['error'] or 'Pending')
            self.screen(uid,text,[[('Safe recovery','repair'),('Verified backup','backup')],[('Retry a failed update','retry')]]+[[('Acknowledge incident '+str(i['id']),'ack:'+str(i['id']))] for i in snapshot['incidents'][:8] if i['state']=='open']+[[('Back','home')]]);return
        if action.startswith('ack:'):self.health.resolve(uid,int(action[4:]));self.handle(uid,'health');return
        if action=='repair':result=self.health.repair(uid);self.bot.send(uid,'Safe recovery: '+dumps(result));self.handle(uid,'health');return
        if action=='backup':result=self.health.backup(uid);self.bot.send(uid,'Local backup verified: '+result['name']+'\nDatabase files stay on the server.');return
        if action=='retry':self.s.owner(uid);self.begin(uid,'retry',[self.field('update_id','ID update of a failed update from the health screen')]);return
        raise AppError('Admin action not found.')
