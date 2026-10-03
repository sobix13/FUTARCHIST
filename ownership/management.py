"""Shared application operations for native Telegram and the web panel."""
from __future__ import annotations
import json
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .core import AppError, bounded, dumps, is_financial_filter
from .forms import FIELDS, split_answers, validate

SUPPORT = [{'username':'sobix13','id':313342234},{'username':'SrMessiSOL','id':5691137098}]
TEXT_DEFAULTS = {
    'welcome':'FUTARCHIST\nEnter the access code supplied by your contact to submit information.\nProject and raise information stays in its assigned workspace.',
    'help':'/start Start\n/activate Enter an access code\n/resume Resume your form\n/projects View or edit your submissions\n/stop Stop DM invitations\n/support Support\n/id Your Telegram ID\n\nAdmins: /manage Manage in Telegram, /panel Open the dashboard.',
    'invite_template':'Hi {project} team,\nWe are hosting {topic} at {when}. With your focus on {sector}, we would like to hear about your progress and plans. Reply using the link below.',
}
GENERAL_FIELDS=('name','categories','motivation','stage','network','website','socials')
RAISE_FIELDS=tuple(k for k in FIELDS if k not in GENERAL_FIELDS)
EVENT_KINDS=('radio','roadshow','podcast','meeting','campaign','raise','other')

def parse_time(value,timezone='UTC'):
    try:
        zone=ZoneInfo(bounded(timezone,80,True))
        if not isinstance(value,str):raise ValueError()
        dt=datetime.fromisoformat(value.strip())
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=zone)
            if datetime.fromtimestamp(dt.timestamp(),zone).replace(tzinfo=None)!=dt.replace(tzinfo=None):raise ValueError()
        return dt.timestamp()
    except (ValueError,ZoneInfoNotFoundError,OverflowError):raise AppError('Enter a valid time, such as 2026-10-10 18:00 with timezone Asia/Tehran.') from None

class Management:
    def __init__(self,store,service=None):self.s=store;self.service=service

    def text(self,key):
        row=self.s.one('SELECT value FROM text_settings WHERE key=?',(key,))
        return row['value'] if row else TEXT_DEFAULTS.get(key)

    def texts(self,uid):
        self.s.owner(uid)
        keys=list(TEXT_DEFAULTS)+['question:'+f for f in FIELDS]
        result=[]
        for key in keys:
            row=self.s.one('SELECT * FROM text_settings WHERE key=?',(key,))
            result.append(dict(row) if row else {'key':key,'value':TEXT_DEFAULTS.get(key,FIELDS.get(key.split(':')[-1],('',))[0]),'version':0})
        return result

    def set_text(self,uid,key,value,version):
        self.s.owner(uid)
        if key not in TEXT_DEFAULTS and not (key.startswith('question:') and key[9:] in FIELDS):raise AppError('This text setting is not editable.')
        value=bounded(value,2800 if key=='invite_template' else 1800,True)
        if key=='invite_template':
            from .service import Service
            Service(self.s).validate_template(value)
        row=self.s.one('SELECT version FROM text_settings WHERE key=?',(key,))
        if (row['version'] if row else 0)!=version:raise AppError('The text has changed. Reopen it.',409)
        self.s.db.execute('INSERT INTO text_settings VALUES(?,?,1,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,version=version+1,editor=excluded.editor,updated_at=excluded.updated_at',(key,value,uid,self.s.clock()))
        self.s.audit(uid,'text_changed',details={'key':key})
        return {'ok':True}

    def edit_project(self,uid,pid,version,changes,purpose='general'):
        if purpose not in ('general','raise'):raise AppError('Invalid branch.')
        p=self.s.project(uid,pid,'write_'+purpose)
        if p['version']!=version:raise AppError('The case has changed. Reopen it.',409)
        if not isinstance(changes,dict) or not changes or not set(changes)<=set(GENERAL_FIELDS if purpose=='general' else RAISE_FIELDS):raise AppError('Invalid edit fields.')
        if purpose=='raise' and not any(c['purpose']=='raise' for c in p['cases']):raise AppError('This case has no raise branch.')
        row=self.s.one('SELECT * FROM projects WHERE id=?',(pid,))
        general=json.loads(row['general']);fund=json.loads(row['fundraising'])
        current={**general,**fund}
        if current.get('currency') not in ('USD','USDC','SOL','ETH','EUR','unknown',None):current['currency_code']=current['currency'];current['currency']='OTHER'
        for key,value in changes.items():current[key]=validate(key,value)
        if purpose=='raise':
            if current.get('raise_status') not in ('not_started','unknown') and not current.get('currency'):current['currency']='unknown'
            if current.get('raise_status') in ('partial','unsuccessful') and not current.get('retry'):current['retry']='undecided'
        if purpose=='general':
            general,_=split_answers('general',current,general.get('contact',''))
        else:
            _,fund=split_answers('raise',current,general.get('contact',''))
        key=general['name'].strip().casefold()
        if self.s.one('SELECT id FROM projects WHERE space_id=? AND submitter=? AND project_key=? AND id<>?',(p['space_id'],p['submitter'],key,pid)):raise AppError('Another project uses this name.')
        self.s.db.execute('UPDATE projects SET general=?,fundraising=?,project_key=?,version=version+1,updated_at=? WHERE id=?',(dumps(general),dumps(fund),key,self.s.clock(),pid))
        self.s.audit(uid,'project_admin_edited',p['space_id'],pid,purpose,{'fields':list(changes)})
        return self.s.project(uid,pid)

    def edit_note(self,uid,tid,version,text):
        t=self.s.one('SELECT * FROM threads WHERE id=? AND deleted_at IS NULL',(tid,))
        if not t:raise AppError('Note not found.',404)
        p=self.s.project(uid,t['project_id'],'write_'+t['purpose'])
        if t['visibility']!='internal':raise AppError('Received messages and delivery history are not editable. Add a correction note.')
        if self.s.actor(uid)['role']!='owner' and t['actor']!=uid:raise AppError('Editing another person\'s note requires superadmin access.',403)
        if t['version']!=version:raise AppError('The note has changed.',409)
        self.s.db.execute('UPDATE threads SET text=?,version=version+1 WHERE id=?',(bounded(text,3000,True),tid))
        self.s.audit(uid,'note_edited',p['space_id'],p['id'],t['purpose'],{'note':tid})

    def configure_route(self,uid,rid,changes):
        r=self.s.one('SELECT * FROM routes WHERE id=?',(rid,))
        if not r:raise AppError('Access code not found.',404)
        self.s.check(uid,r['space_id'],'routes')
        if r['purpose']!='general':self.s.check(uid,r['space_id'],'read_raise')
        if self.s.actor(uid)['role']!='owner' and r['creator']!=uid:raise AppError('Editing another admin\'s code requires superadmin access.',403)
        if not isinstance(changes,dict) or not set(changes)<={'name','expires','max_uses','bound_user','active'}:raise AppError('Invalid code settings.')
        values=dict(r)
        for key,value in changes.items():
            if key=='name':value=bounded(value,100,True)
            elif key=='active':
                if type(value) is not bool:raise AppError('Invalid status.')
                value=int(value)
            elif key=='expires':
                if value is not None and (type(value) not in (int,float) or not self.s.clock()<value<self.s.clock()+5*365*86400):raise AppError('The code expiry must be in the future.')
            elif value is not None and (type(value) is not int or value<=0):raise AppError('Invalid ID or activation limit.')
            values[key]=value
        self.s.db.execute('UPDATE routes SET name=?,expires=?,max_uses=?,bound_user=?,active=? WHERE id=?',tuple(values[k] for k in ('name','expires','max_uses','bound_user','active'))+(rid,))
        self.s.audit(uid,'route_configured',r['space_id'],details={'route':rid})
        return dict(self.s.one('SELECT * FROM routes WHERE id=?',(rid,)))

    def revoke_grant(self,uid,rid,guest,active=False):
        self.grants(uid,rid)
        r=self.s.one('SELECT * FROM routes WHERE id=?',(rid,))
        if not r:raise AppError('Access code not found.',404)
        self.s.check(uid,r['space_id'],'routes')
        if self.s.actor(uid)['role']!='owner' and r['creator']!=uid:raise AppError('Managing another admin\'s code requires superadmin access.',403)
        if not self.s.one('SELECT * FROM access_grants WHERE route_id=? AND user_id=?',(rid,guest)):raise AppError('This person\'s activation was not found.',404)
        self.s.db.execute('UPDATE access_grants SET active=? WHERE route_id=? AND user_id=?',(int(active),rid,guest))
        self.s.audit(uid,'grant_changed',r['space_id'],details={'route':rid,'user':guest,'active':bool(active)})

    def grants(self,uid,rid):
        r=self.s.one('SELECT * FROM routes WHERE id=?',(rid,))
        if not r:raise AppError('Access code not found.',404)
        self.s.check(uid,r['space_id'],'routes')
        if r['purpose']!='general':self.s.check(uid,r['space_id'],'read_raise')
        if self.s.actor(uid)['role']!='owner' and r['creator']!=uid:raise AppError('Managing another admin\'s code requires superadmin access.',403)
        return self.s.rows('SELECT g.*,u.name FROM access_grants g JOIN users u ON u.id=g.user_id WHERE g.route_id=? ORDER BY g.created_at DESC',(rid,))

    def rename_space(self,uid,sid,name):
        self.s.owner(uid)
        if not self.s.one('SELECT id FROM spaces WHERE id=?',(sid,)):raise AppError('Workspace not found.',404)
        self.s.db.execute('UPDATE spaces SET name=? WHERE id=?',(bounded(name,100,True),sid))
        self.s.audit(uid,'space_renamed',sid)

    def rotate_route(self,uid,rid):
        self.grants(uid,rid)
        r=self.s.one('SELECT * FROM routes WHERE id=?',(rid,))
        if not r:raise AppError('Access code not found.',404)
        self.s.check(uid,r['space_id'],'routes')
        if self.s.actor(uid)['role']!='owner' and r['creator']!=uid:raise AppError('Rotating another admin\'s code requires superadmin access.',403)
        self.s.check(r['creator'],r['space_id'],'routes')
        new=self.s.route(r['creator'],r['space_id'],r['name'],r['purpose'],r['assignee'])
        self.s.db.execute('UPDATE routes SET active=0 WHERE id=?',(rid,))
        self.s.db.execute('UPDATE routes SET expires=?,max_uses=?,bound_user=? WHERE id=?',(r['expires'],r['max_uses'],r['bound_user'],new['id']))
        self.s.audit(uid,'route_rotated',r['space_id'],details={'old':rid,'new':new['id']})
        return dict(self.s.one('SELECT * FROM routes WHERE id=?',(new['id'],)))

    def events(self,uid,sid,archived=False):
        if archived:self.s.owner(uid)
        self.s.check(uid,sid,'read_general')
        rows=self.s.rows('SELECT e.*,u.name creator_name FROM events e JOIN users u ON u.id=e.creator WHERE e.space_id=? AND e.archived_at IS '+('NOT NULL' if archived else 'NULL')+' ORDER BY e.starts_at DESC',(sid,))
        return [r for r in rows if r['kind']!='raise' or 'read_raise' in self.s.permissions(uid,sid)]

    def event(self,uid,eid,include_archived=False):
        if include_archived:self.s.owner(uid)
        r=self.s.one('SELECT * FROM events WHERE id=?'+('' if include_archived else ' AND archived_at IS NULL'),(eid,))
        if not r:raise AppError('Program not found.',404)
        self.s.check(uid,r['space_id'],'read_raise' if r['kind']=='raise' else 'read_general')
        projects=[]
        for link in self.s.rows('SELECT * FROM event_projects WHERE event_id=?',(eid,)):
            p=self.s.project(uid,link['project_id'],include_archived=True)
            projects.append({**link,'name':p['general']['name']})
        return {**dict(r),'projects':projects}

    def save_event(self,uid,sid,data,eid=None):
        if not isinstance(data,dict):raise AppError('Invalid program details.')
        prior=self.event(uid,eid) if eid else None
        if prior and prior['space_id']!=sid:raise AppError('Invalid program workspace.',403)
        kind=data.get('kind',prior['kind'] if prior else 'meeting')
        if kind not in EVENT_KINDS:raise AppError('Invalid program type.')
        self.s.check(uid,sid,'write_raise' if kind=='raise' else 'write_general')
        if prior:
            self.s.check(uid,sid,'write_raise' if prior['kind']=='raise' else 'write_general')
            if data.get('version')!=prior['version']:raise AppError('The program has changed.',409)
        get=lambda k,default='':data.get(k,prior.get(k,default) if prior else default)
        title=bounded(get('title'),160,True);topic=bounded(get('topic'),160)
        timezone=bounded(get('timezone','UTC'),80,True)
        starts=get('starts_at')
        if isinstance(starts,str):starts=parse_time(starts,timezone)
        try:ZoneInfo(timezone)
        except ZoneInfoNotFoundError:raise AppError('Invalid timezone.') from None
        if type(starts) not in (int,float) or not 0<starts<253402300799:raise AppError('Invalid program time.')
        status=get('status','planned')
        if status not in ('planned','confirmed','completed','cancelled'):raise AppError('Invalid program status.')
        description=bounded(get('description'),3000);outcome=bounded(get('outcome'),3000)
        if prior:self.s.db.execute('UPDATE events SET title=?,kind=?,topic=?,starts_at=?,timezone=?,status=?,description=?,outcome=?,version=version+1 WHERE id=?',(title,kind,topic,starts,timezone,status,description,outcome,eid))
        else:eid=self.s.db.execute('INSERT INTO events(space_id,creator,title,kind,topic,starts_at,timezone,status,description,outcome,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(sid,uid,title,kind,topic,starts,timezone,status,description,outcome,self.s.clock())).lastrowid
        self.s.audit(uid,'event_updated' if prior else 'event_created',sid,purpose='raise' if kind=='raise' else 'general',details={'event':eid})
        return self.event(uid,eid)

    def link_event(self,uid,eid,pid,participation):
        e=self.event(uid,eid)
        self.s.check(uid,e['space_id'],'write_raise' if e['kind']=='raise' else 'write_general')
        p=self.s.project(uid,pid)
        if p['space_id']!=e['space_id']:raise AppError('The project and program must belong to the same workspace.',403)
        if participation not in ('planned','invited','confirmed','attended','declined','remove'):raise AppError('Invalid participation status.')
        if participation=='remove':self.s.db.execute('DELETE FROM event_projects WHERE event_id=? AND project_id=?',(eid,pid))
        else:self.s.db.execute('INSERT INTO event_projects VALUES(?,?,?) ON CONFLICT(event_id,project_id) DO UPDATE SET participation=excluded.participation',(eid,pid,participation))
        self.s.db.execute('UPDATE events SET version=version+1 WHERE id=?',(eid,))
        self.s.audit(uid,'event_participation',e['space_id'],pid,'raise' if e['kind']=='raise' else 'general',{'event':eid,'status':participation})

    def tasks(self,uid,sid,archived=False):
        if archived:self.s.owner(uid)
        self.s.check(uid,sid,'read_general')
        rows=self.s.rows('SELECT t.*,u.name assignee_name FROM tasks t JOIN users u ON u.id=t.assignee WHERE t.space_id=? AND t.archived_at IS '+('NOT NULL' if archived else 'NULL')+' ORDER BY t.status,t.due_at,t.id DESC',(sid,))
        return [t for t in rows if t['purpose']!='raise' or 'read_raise' in self.s.permissions(uid,sid)]

    def save_task(self,uid,sid,data,tid=None):
        prior=self.s.one('SELECT * FROM tasks WHERE id=? AND archived_at IS NULL',(tid,)) if tid else None
        if tid and not prior:raise AppError('Task not found.',404)
        purpose=data.get('purpose',prior['purpose'] if prior else 'general')
        if purpose not in ('general','raise'):raise AppError('Invalid branch.')
        self.s.check(uid,sid,'write_'+purpose)
        if prior:
            if prior['space_id']!=sid:raise AppError('Invalid workspace.',403)
            self.s.check(uid,sid,'write_'+prior['purpose'])
            if data.get('version')!=prior['version']:raise AppError('The task has changed.',409)
        get=lambda k,default=None:data.get(k,prior[k] if prior else default)
        assignee=get('assignee',uid)
        if type(assignee) is not int:raise AppError('Invalid assignee ID.')
        if (prior and assignee!=prior['assignee']) or (not prior and assignee!=uid):self.s.check(uid,sid,'assign')
        self.s.check(assignee,sid,'read_'+purpose)
        pid=get('project_id');eid=get('event_id')
        if pid and self.s.project(uid,pid,'read_'+purpose)['space_id']!=sid:raise AppError('The project is not in this workspace.',403)
        if eid:
            e=self.event(uid,eid)
            if e['space_id']!=sid or (e['kind']=='raise' and purpose!='raise'):raise AppError('The program does not match this workspace or branch.',403)
        title=bounded(get('title',''),200,True);status=get('status','open');due=get('due_at')
        if status not in ('open','doing','done','cancelled'):raise AppError('Invalid task status.')
        if isinstance(due,str):due=parse_time(due,data.get('timezone','UTC'))
        if due is not None and (type(due) not in (int,float) or not 0<due<253402300799):raise AppError('Invalid task time.')
        if prior:self.s.db.execute('UPDATE tasks SET assignee=?,project_id=?,event_id=?,purpose=?,title=?,due_at=?,status=?,version=version+1 WHERE id=?',(assignee,pid,eid,purpose,title,due,status,tid))
        else:tid=self.s.db.execute('INSERT INTO tasks(space_id,creator,assignee,project_id,event_id,purpose,title,due_at,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(sid,uid,assignee,pid,eid,purpose,title,due,status,self.s.clock())).lastrowid
        self.s.audit(uid,'task_updated' if prior else 'task_created',sid,pid,purpose,{'task':tid})
        return dict(self.s.one('SELECT * FROM tasks WHERE id=?',(tid,)))

    def prepare(self,uid,action,data):
        self.s.owner(uid)
        if action not in ('archive_project','restore_project','purge_project','archive_event','restore_event','archive_task','restore_task','delete_note','disable_space','enable_space'):raise AppError('Invalid confirmation action.')
        token=secrets.token_hex(12)
        self.s.db.execute('INSERT INTO operation_tokens VALUES(?,?,?,?,?,0)',(token,uid,action,dumps(data),self.s.clock()+300))
        return {'token':token,'action':action,'expires_in':300}

    def confirm(self,uid,token):
        self.s.owner(uid)
        row=self.s.one('SELECT * FROM operation_tokens WHERE token=? AND user_id=? AND used=0 AND expires>?',(token,uid,self.s.clock()))
        if not row:raise AppError('This confirmation has expired or was used.',409)
        data=json.loads(row['data']);action=row['action'];sid=None;pid=None;purpose='general'
        if action.endswith('_project'):
            pid=int(data['id']);p=self.s.project(uid,pid,include_archived=True);sid=p['space_id']
            if data.get('version')!=p['version']:raise AppError('The case has changed. Request a new confirmation.',409)
            if action=='purge_project':
                if not p['archived_at']:raise AppError('Archive the case before permanently deleting it.')
                self._purge_project(pid)
            else:
                self.s.db.execute('UPDATE projects SET archived_at=?,version=version+1,updated_at=? WHERE id=?',(self.s.clock() if action=='archive_project' else None,self.s.clock(),pid))
                if action=='archive_project':
                    self.s.db.execute('UPDATE groups SET active=0 WHERE project_id=?',(pid,))
                    self.s.db.execute("UPDATE outbox SET state='cancelled',error='Project archived' WHERE state='pending' AND id IN (SELECT outbox_id FROM recipients WHERE project_id=?)",(pid,))
        elif action in ('archive_event','restore_event','archive_task','restore_task'):
            table='events' if action.endswith('_event') else 'tasks'
            target=self.s.one('SELECT * FROM '+table+' WHERE id=?',(int(data['id']),))
            if not target:raise AppError('Item not found.',404)
            if target['version']!=data.get('version'):raise AppError('The item has changed.',409)
            sid=target['space_id'];purpose='raise' if (target['kind']=='raise' if table=='events' else target['purpose']=='raise') else 'general'
            self.s.db.execute('UPDATE '+table+' SET archived_at=?,version=version+1 WHERE id=?',(self.s.clock() if action.startswith('archive_') else None,target['id']))
        elif action=='delete_note':
            note=self.s.one('SELECT * FROM threads WHERE id=?',(int(data['id']),))
            if not note:raise AppError('Note not found.',404)
            if note['version']!=data.get('version'):raise AppError('The note has changed.',409)
            if note['visibility']!='internal':raise AppError('Delete the archived case to remove its conversation history.')
            p=self.s.project(uid,note['project_id']);sid=p['space_id'];pid=p['id'];purpose=note['purpose']
            self.s.db.execute('UPDATE threads SET deleted_at=?,version=version+1 WHERE id=?',(self.s.clock(),note['id']))
        else:
            sid=int(data['id']);space=self.s.one('SELECT * FROM spaces WHERE id=?',(sid,))
            if not space:raise AppError('Workspace not found.',404)
            if data.get('active') is not None and data['active']!=space['active']:raise AppError('The workspace status has changed. Request a new confirmation.',409)
            self.s.db.execute('UPDATE spaces SET active=? WHERE id=?',(int(action=='enable_space'),sid))
        self.s.db.execute('UPDATE operation_tokens SET used=1 WHERE token=?',(token,))
        self.s.audit(uid,action,sid,None if action=='purge_project' else pid,purpose,{'target':data.get('id')})
        return {'ok':True}

    def _purge_project(self,pid):
        jobs=self.s.rows("SELECT id,state FROM outbox WHERE id IN (SELECT outbox_id FROM recipients WHERE project_id=?) OR dedupe IN (SELECT 'note:'||id FROM threads WHERE project_id=?)",(pid,pid))
        if any(j['state']=='sending' for j in jobs):raise AppError('A related delivery is in progress. Try again after its outcome is known.',409)
        for job in jobs:self.s.db.execute("UPDATE outbox SET payload='{}',state='cancelled',error='Project data deleted' WHERE id=?",(job['id'],))
        for table in ('event_projects','recipients','reply_tokens','bindings','groups','threads','cases','activity'):
            self.s.db.execute('DELETE FROM '+table+' WHERE project_id=?',(pid,))
        self.s.db.execute('UPDATE tasks SET project_id=NULL WHERE project_id=?',(pid,))
        self.s.db.execute('DELETE FROM projects WHERE id=?',(pid,))
        for flow in self.s.rows('SELECT user_id,data FROM flows'):
            if json.loads(flow['data']).get('pid')==pid:self.s.db.execute('DELETE FROM flows WHERE user_id=?',(flow['user_id'],))
