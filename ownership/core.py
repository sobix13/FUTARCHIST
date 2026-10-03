from __future__ import annotations
import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qsl

PERMISSIONS = ('read_general','write_general','read_raise','write_raise','send','assign','export','routes')
PRESETS = {'viewer':['read_general'], 'reviewer':['read_general','write_general','read_raise','write_raise','assign'],
           'manager':list(PERMISSIONS)}
CATEGORIES = ['gaming','defi','prediction','tokenization','infra','payments','consumer','other']
STAGES = ['idea','building','beta','live']
NETWORKS = ['na','devnet','testnet','mainnet']
RAISE_STATES = ['not_started','planning','ongoing','success','partial','unsuccessful']
STATUSES = ['new','reviewing','followup','accepted','closed']
FINANCIAL_FILTERS = ['raise_status','retry','metadao','platform','currency','min_target','max_target','min_raised','max_raised']

def is_financial_filter(filters):
    return filters.get('purpose')=='raise' or any(filters.get(k) not in ('',None,[]) for k in FINANCIAL_FILTERS)

class AppError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status

def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',',':'))

def bounded(value, maximum=500, required=False):
    if not isinstance(value, str):
        raise AppError('Enter valid text.')
    value = value.strip()
    if len(value) > maximum or (required and not value):
        raise AppError(f'Text length must be between {1 if required else 0} and {maximum} characters.')
    if any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise AppError('The text contains an invalid character.')
    return value

def text_units(text):
    # Telegram entity offsets use UTF-16. A conservative limit also covers astral characters.
    try: return len(text.encode('utf-16-le'))//2
    except UnicodeEncodeError: raise AppError('The text contains an invalid Unicode character.') from None

def tg_auth(raw, bot_token, now=None):
    now = time.time() if now is None else now
    pairs = parse_qsl(raw, keep_blank_values=True)
    if len({k for k,v in pairs}) != len(pairs):
        raise AppError('Invalid login.',401)
    data = dict(pairs)
    signature = data.pop('hash','')
    secret = hmac.new(b'WebAppData',bot_token.encode(),hashlib.sha256).digest()
    expected = hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(data.items())).encode(),hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(expected,signature):
        raise AppError('Invalid login.',401)
    try:
        age = now - int(data['auth_date'])
        user = json.loads(data['user'])
        uid = user['id']
        if age > 300 or age < -30 or not isinstance(uid,int) or isinstance(uid,bool) or uid <= 0:
            raise ValueError()
    except (ValueError,KeyError,TypeError,json.JSONDecodeError):
        raise AppError('Login expired or invalid.',401) from None
    return uid, bounded(user.get('first_name','User'),100,True)

class Store:
    def __init__(self,path,owner_id=1,clock=time.time,super_admin_ids=None,gated=True):
        self.path = str(path)
        self.clock = clock
        self.gated = gated
        self.super_admin_ids = tuple(sorted(set(super_admin_ids or (owner_id,))))
        if owner_id not in self.super_admin_ids or any(type(uid) is not int or uid<=0 for uid in self.super_admin_ids):
            raise ValueError('Invalid superadmin configuration')
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path,check_same_thread=False,isolation_level=None,timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA busy_timeout=10000')
        version=self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0,1,2):
            self.db.close()
            raise RuntimeError('Unsupported database version')
        if version==1 and self.path!=':memory:':
            backup=sqlite3.connect(self.path+'.before-v2-'+str(time.time_ns())+'.sqlite3')
            try:self.db.backup(backup)
            finally:backup.close()
        changes=[]
        if version in (1,2):
            for table,columns in {'routes':{'expires':'REAL','max_uses':'INTEGER','uses':'INTEGER NOT NULL DEFAULT 0','bound_user':'INTEGER'},
                                  'projects':{'archived_at':'REAL'},'threads':{'version':'INTEGER NOT NULL DEFAULT 1','deleted_at':'REAL'},
                                  'inbox':{'next_at':'REAL NOT NULL DEFAULT 0'}}.items():
                present={r['name'] for r in self.db.execute('PRAGMA table_info('+table+')')}
                changes += ['ALTER TABLE '+table+' ADD COLUMN '+name+' '+kind+';' for name,kind in columns.items() if name not in present]
        try:self.db.executescript('BEGIN IMMEDIATE;\n'+'\n'.join(changes)+'\n'+Path(__file__).with_name('schema.sql').read_text()+'\nCOMMIT;')
        except BaseException:
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            self.db.close();raise
        existing_owners={r['id'] for r in self.rows("SELECT id FROM users WHERE role='owner'")}
        if not existing_owners<=set(self.super_admin_ids):
            self.db.close()
            raise RuntimeError('Superadmin configuration excludes an existing owner. Explicit migration required.')
        with self.tx():
            for uid in self.super_admin_ids:
                name={313342234:'Sobix',5691137098:'SrMessi'}.get(uid,'Superadmin '+str(uid))
                self.db.execute("INSERT INTO users(id,name,role) VALUES(?,?,'owner') ON CONFLICT(id) DO UPDATE SET role='owner',active=1",(uid,name))
            if not self.one('SELECT id FROM spaces'):
                sid = self.db.execute("INSERT INTO spaces(name,kind,creator) VALUES('Superadmin inbox','personal',?)",(owner_id,)).lastrowid
                self.db.execute("INSERT INTO routes(token,space_id,creator,assignee,name,purpose) VALUES('public',?,?,?,'Public intake','both')",(sid,owner_id,owner_id))
            if self.gated:self.db.execute("UPDATE routes SET active=0 WHERE token='public'")
            for uid in self.super_admin_ids:
                personal=self.one("SELECT id FROM spaces WHERE creator=? AND kind='personal'",(uid,))
                if not personal:
                    sid=self.db.execute("INSERT INTO spaces(name,kind,creator) VALUES(?,'personal',?)",('Workspace '+self.actor(uid)['name'],uid)).lastrowid
                else:sid=personal['id']
                self.default_route(uid,sid)
            from .english import upgrade_english
            upgrade_english(self)

    def close(self):
        self.db.close()

    @contextmanager
    def tx(self):
        with self.lock:
            nested = self.db.in_transaction
            if not nested:
                self.db.execute('BEGIN IMMEDIATE')
            try:
                yield self
                if not nested:
                    self.db.execute('COMMIT')
            except BaseException:
                if not nested:
                    self.db.execute('ROLLBACK')
                raise

    def one(self,sql,args=()):
        return self.db.execute(sql,args).fetchone()

    def rows(self,sql,args=()):
        return [dict(r) for r in self.db.execute(sql,args).fetchall()]

    def actor(self,uid):
        u = self.one('SELECT * FROM users WHERE id=?',(uid,))
        if not u or not u['active']:
            raise AppError('This account\'s access is inactive.',403)
        return dict(u)

    def owner(self,uid):
        if self.actor(uid)['role'] != 'owner':
            raise AppError('This section requires superadmin access.',403)

    def check(self,uid,sid,permission):
        u = self.actor(uid)
        space = self.one('SELECT * FROM spaces WHERE id=? AND active=1',(sid,))
        if not space:
            raise AppError('Workspace unavailable.',403)
        if u['role'] == 'owner':
            return
        member = self.one('SELECT permissions FROM members WHERE space_id=? AND user_id=?',(sid,uid))
        if u['role'] != 'admin' or not member or permission not in json.loads(member['permissions']):
            raise AppError('You do not have permission for this action.',403)

    def permissions(self,uid,sid):
        try:
            self.check(uid,sid,'read_general')
        except AppError:
            return []
        if self.actor(uid)['role']=='owner':
            return list(PERMISSIONS)
        return json.loads(self.one('SELECT permissions FROM members WHERE space_id=? AND user_id=?',(sid,uid))['permissions'])

    def audit(self,uid,action,sid=None,pid=None,purpose='general',details=None):
        self.db.execute('INSERT INTO activity(space_id,project_id,purpose,actor,action,details,created_at) VALUES(?,?,?,?,?,?,?)',
                        (sid,pid,purpose,uid,action,dumps(details or {}),self.clock()))

    def register(self,uid,name,started=False):
        self.db.execute('INSERT INTO users(id,name,started) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, started=MAX(users.started,excluded.started)',
                        (uid,bounded(name,100,True),int(started)))

    def add_admin(self,owner,uid,name):
        self.owner(owner)
        if uid<=0 or uid==owner:
            raise AppError('Invalid admin ID.')
        old = self.one('SELECT role FROM users WHERE id=?',(uid,))
        if old and old['role']=='owner':
            raise AppError('The superadmin role cannot be changed.')
        self.db.execute("INSERT INTO users(id,name,role) VALUES(?,?,'admin') ON CONFLICT(id) DO UPDATE SET role='admin',active=1,name=excluded.name",(uid,bounded(name,100,True)))
        existing = self.one("SELECT id FROM spaces WHERE kind='personal' AND creator=?",(uid,))
        if not existing:
            sid = self.db.execute("INSERT INTO spaces(name,kind,creator) VALUES(?,'personal',?)",(f'Workspace {name}',uid)).lastrowid
            self.db.execute('INSERT INTO members VALUES(?,?,?)',(sid,uid,dumps(list(PERMISSIONS))))
        else:sid=existing['id']
        self.default_route(uid,sid)
        self.audit(owner,'admin_added',details={'user':uid})

    def deactivate(self,owner,uid,active):
        self.owner(owner)
        target=self.one('SELECT role FROM users WHERE id=?',(uid,))
        if uid==owner or not target or target['role']!='admin':
            raise AppError('Only an admin\'s status is editable.')
        self.db.execute('UPDATE users SET active=? WHERE id=?',(int(active),uid))
        self.db.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
        self.audit(owner,'admin_status',details={'user':uid,'active':bool(active)})

    def team(self,owner,name):
        self.owner(owner)
        sid = self.db.execute("INSERT INTO spaces(name,kind,creator) VALUES(?,'team',?)",(bounded(name,100,True),owner)).lastrowid
        self.audit(owner,'team_created',sid)
        return sid

    def membership(self,owner,sid,uid,permissions):
        self.owner(owner)
        space = self.one('SELECT * FROM spaces WHERE id=?',(sid,))
        if not space or self.actor(uid)['role']!='admin':
            raise AppError('Invalid team or admin.')
        if space['kind']=='personal' and space['creator']!=uid:
            raise AppError('A personal workspace is reserved for its owner.')
        if not isinstance(permissions,list) or not set(permissions)<=set(PERMISSIONS):
            raise AppError('Invalid permissions.')
        if permissions and 'read_general' not in permissions:
            raise AppError('General read access is required.')
        for p in ['write_general','write_raise','send','assign','export','routes']:
            if p in permissions and (('read_raise' if p=='write_raise' else 'read_general') not in permissions):
                raise AppError('The corresponding read permission is required.')
        if permissions:
            self.db.execute('INSERT INTO members VALUES(?,?,?) ON CONFLICT(space_id,user_id) DO UPDATE SET permissions=excluded.permissions',(sid,uid,dumps(sorted(set(permissions)))))
        else:
            self.db.execute('DELETE FROM members WHERE space_id=? AND user_id=?',(sid,uid))
        self.db.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
        self.audit(owner,'membership_changed',sid,details={'user':uid,'permissions':permissions})

    def spaces(self,uid):
        u = self.actor(uid)
        if u['role']=='owner':
            spaces = self.rows('SELECT * FROM spaces WHERE active=1 ORDER BY id')
        else:
            spaces = self.rows('SELECT s.* FROM spaces s JOIN members m ON m.space_id=s.id WHERE m.user_id=? AND s.active=1 ORDER BY s.id',(uid,))
        for s in spaces:
            s['permissions']=self.permissions(uid,s['id'])
        return spaces

    def route(self,uid,sid,name,purpose,assignee):
        self.check(uid,sid,'routes')
        if purpose not in ('general','raise','both'):
            raise AppError('Invalid route type.')
        self.check(assignee,sid,'read_general')
        if purpose in ('raise','both'):
            self.check(uid,sid,'read_raise')
            self.check(assignee,sid,'read_raise')
        token = secrets.token_urlsafe(18)
        rid = self.db.execute('INSERT INTO routes(token,space_id,creator,assignee,name,purpose) VALUES(?,?,?,?,?,?)',
                       (token,sid,uid,assignee,bounded(name,100,True),purpose)).lastrowid
        self.audit(uid,'route_created',sid,details={'route':rid})
        return dict(self.one('SELECT * FROM routes WHERE id=?',(rid,)))

    def default_route(self,uid,sid):
        row=self.one('SELECT * FROM routes WHERE creator=? AND space_id=? AND active=1 AND token<>\'public\' ORDER BY id LIMIT 1',(uid,sid))
        if row:return dict(row)
        return self.route(uid,sid,'Intake code '+self.actor(uid)['name'],'both',uid)

    def activate(self,uid,token):
        token=bounded(token,64,True)
        route=self.active_route(token)
        if route.get('bound_user') and route['bound_user']!=uid:raise AppError('This code is assigned to another account.',403)
        prior=self.one('SELECT active FROM access_grants WHERE user_id=? AND route_id=?',(uid,route['id']))
        if prior and not prior['active']:raise AppError('Your access to this route is closed. Contact the sender.',403)
        if not prior and route.get('max_uses') is not None and route['uses']>=route['max_uses']:
            raise AppError('This code has reached its activation limit. Ask for a new code.')
        if not prior:
            self.db.execute('UPDATE routes SET uses=uses+1 WHERE id=?',(route['id'],))
        self.db.execute('INSERT INTO access_grants VALUES(?,?,?,1) ON CONFLICT(user_id,route_id) DO UPDATE SET active=1',(uid,route['id'],self.clock()))
        self.audit(uid,'access_activated',route['space_id'],details={'route':route['id']})
        return route

    def guest_routes(self,uid):
        result=[]
        for r in self.rows('SELECT r.token FROM access_grants g JOIN routes r ON r.id=g.route_id WHERE g.user_id=? AND g.active=1 ORDER BY g.created_at DESC',(uid,)):
            try:result.append(self.active_route(r['token']))
            except AppError:pass
        return result

    def active_route(self,token):
        if self.gated and token=='public':raise AppError('Enter your contact\'s private access code.')
        route = self.one('SELECT r.*,s.name space_name FROM routes r JOIN spaces s ON s.id=r.space_id WHERE r.token=? AND r.active=1 AND s.active=1',(token,))
        if not route:
            raise AppError('This route is inactive. Ask your contact for a new link.')
        if route['expires'] is not None and route['expires']<=self.clock():raise AppError('This code has expired. Ask your contact for a new code.')
        self.check(route['creator'],route['space_id'],'routes')
        if route['purpose']!='general':self.check(route['creator'],route['space_id'],'read_raise')
        self.check(route['assignee'],route['space_id'],'read_raise' if route['purpose']!='general' else 'read_general')
        return dict(route)

    def guest_route(self,uid,token):
        route=self.active_route(token)
        if self.gated:
            grant=self.one('SELECT active FROM access_grants WHERE user_id=? AND route_id=?',(uid,route['id']))
            if not grant or not grant['active']:raise AppError('Your access to this route is inactive. Contact the sender.',403)
            if route.get('bound_user') and route['bound_user']!=uid:raise AppError('This code belongs to another account.',403)
        return route

    def save_project(self,guest,route_token,general,fundraising,purpose,pid=None,version=None):
        route = self.guest_route(guest,route_token)
        self.actor(guest)
        if purpose not in ('general','raise','both') or (route['purpose']!='both' and purpose!=route['purpose']):
            raise AppError('The case type does not match the intake route.')
        key = str(general['name']).strip().casefold()
        existing = self.one('SELECT * FROM projects WHERE id=?',(pid,)) if pid else self.one('SELECT * FROM projects WHERE space_id=? AND submitter=? AND project_key=?',(route['space_id'],guest,key))
        if existing:
            if existing['archived_at']:raise AppError('This case is archived. Contact its reviewer.')
            if existing['submitter']!=guest or existing['space_id']!=route['space_id']:
                raise AppError('This case does not belong to your account or route.',403)
            if version is not None and existing['version']!=version:
                raise AppError('The information has changed. Reopen the case.',409)
            collision=self.one('SELECT id FROM projects WHERE space_id=? AND submitter=? AND project_key=? AND id<>?',
                               (route['space_id'],guest,key,existing['id']))
            if collision: raise AppError('Another project uses this name. Choose a different name.')
            pid=existing['id']
            self.db.execute('UPDATE projects SET general=?,fundraising=?,project_key=?,version=version+1,updated_at=? WHERE id=?',
                            (dumps(general),dumps(fundraising if purpose!='general' else json.loads(existing['fundraising'])),key,self.clock(),pid))
        else:
            pid=self.db.execute('INSERT INTO projects(space_id,submitter,project_key,general,fundraising,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                        (route['space_id'],guest,key,dumps(general),dumps(fundraising),self.clock(),self.clock())).lastrowid
        for p in (['general','raise'] if purpose=='both' else [purpose]):
            self.db.execute('INSERT OR IGNORE INTO cases(project_id,purpose,source_admin,route_id,assignee) VALUES(?,?,?,?,?)',
                            (pid,p,route['creator'],route['id'],route['assignee']))
        self.audit(guest,'project_updated' if existing else 'project_submitted',route['space_id'],pid,'raise' if purpose=='raise' else 'general')
        return pid

    def project(self,uid,pid,permission='read_general',include_archived=False):
        row=self.one('SELECT * FROM projects WHERE id=?',(pid,))
        if not row or (row['archived_at'] and not include_archived):
            raise AppError('Case not found.',404)
        self.check(uid,row['space_id'],permission)
        r=dict(row)
        r['general']=json.loads(r['general'])
        perms=self.permissions(uid,r['space_id'])
        r['fundraising']=json.loads(r['fundraising']) if 'read_raise' in perms else None
        r['cases']=self.rows('SELECT c.*,a.name assignee_name,u.name source_name FROM cases c JOIN users a ON a.id=c.assignee JOIN users u ON u.id=c.source_admin WHERE c.project_id=?',(pid,))
        if 'read_raise' not in perms:
            r['cases']=[c for c in r['cases'] if c['purpose']=='general']
        return r

    def projects(self,uid,sid,filters=None):
        self.check(uid,sid,'read_general')
        f=filters or {}
        allowed={'categories','stage','network','raise_status','retry','metadao','platform','min_target','max_target','min_raised','max_raised','currency','purpose','status','assignee','source_admin','search','archived'}
        if not isinstance(f,dict) or not set(f)<=allowed:
            raise AppError('Invalid filter.')
        from decimal import Decimal, InvalidOperation
        for k in allowed:
            if k not in f or f[k] in ('',None,[]): continue
            if k=='archived':
                if f[k] not in ('only','all'):raise AppError('Invalid archive filter.')
                self.owner(uid)
            elif k=='categories':
                values=[f[k]] if isinstance(f[k],str) else f[k]
                if not isinstance(values,list) or any(not isinstance(v,str) or v not in CATEGORIES for v in values):
                    raise AppError('Invalid category filter.')
            elif k.startswith(('min_','max_')):
                try:
                    v=Decimal(str(f[k]))
                    if not v.is_finite() or v<0 or v>Decimal('1e15'): raise ValueError()
                    if not f.get('currency'): raise AppError('Select a currency before filtering amounts.')
                except (InvalidOperation,ValueError): raise AppError('Invalid filter amount.') from None
            elif k in ('assignee','source_admin'):
                if isinstance(f[k],bool) or not str(f[k]).isdigit(): raise AppError('Invalid filter ID.')
            else:
                bounded(f[k],1200)
        for key,values in {'stage':STAGES,'network':NETWORKS,'raise_status':RAISE_STATES+['unknown'],
                            'retry':['yes','no','undecided'],'metadao':['yes','no','considering','unknown'],
                            'purpose':['general','raise'],'status':STATUSES}.items():
            if f.get(key) and f[key] not in values: raise AppError('Invalid filter option.')
        for field in ('target','raised'):
            if f.get('min_'+field) not in ('',None) and f.get('max_'+field) not in ('',None):
                if Decimal(str(f['min_'+field]))>Decimal(str(f['max_'+field])): raise AppError('The minimum amount exceeds the maximum.')
        if any(k in f and f[k] not in ('',None,[]) for k in ['raise_status','retry','metadao','platform','min_target','max_target','min_raised','max_raised','currency']):
            self.check(uid,sid,'read_raise')
        if f.get('purpose')=='raise':
            self.check(uid,sid,'read_raise')
        result=[]
        archived=f.get('archived')
        for row in self.rows('SELECT id FROM projects WHERE space_id=?'+(' AND archived_at IS NOT NULL' if archived=='only' else '' if archived=='all' else ' AND archived_at IS NULL')+' ORDER BY updated_at DESC,id DESC',(sid,)):
            p=self.project(uid,row['id'],include_archived=bool(archived))
            g=p['general']; funding=p['fundraising'] or {}
            if f.get('search') and str(f['search']).casefold() not in dumps(g).casefold(): continue
            cat=f.get('categories',[])
            if isinstance(cat,str): cat=[cat]
            if cat and not set(cat)&set(g.get('categories',[])): continue
            if any(f.get(k) and g.get(k)!=f[k] for k in ('stage','network')): continue
            if any(f.get(k) and funding.get(k)!=f[k] for k in ('raise_status','retry','metadao','currency')): continue
            if f.get('platform') and str(funding.get('platform') or '').casefold()!=f['platform'].strip().casefold(): continue
            numeric_match=True
            for field in ['target','raised']:
                for prefix,compare in [('min',lambda a,b:a>=b),('max',lambda a,b:a<=b)]:
                    key=f'{prefix}_{field}'
                    if f.get(key) not in ('',None):
                        try:
                            if not f.get('currency'): raise AppError('Select a currency before filtering amounts.')
                            if not funding.get(field+'_amount') or not compare(Decimal(funding[field+'_amount']),Decimal(str(f[key]))): numeric_match=False
                        except (InvalidOperation,ValueError): raise AppError('Invalid filter amount.') from None
            if not numeric_match: continue
            cases=p['cases']
            if any(f.get(k) not in ('',None,[]) for k in ('purpose','status','assignee','source_admin')):
                def case_match(c):
                    return all(f.get(k) in ('',None,[]) or str(c.get(k))==str(f[k]) for k in ('purpose','status','assignee','source_admin'))
                if not any(case_match(c) for c in cases): continue
            result.append(p)
        return result

    def update_case(self,uid,cid,version,status=None,assignee=None):
        c=self.one('SELECT c.*,p.space_id FROM cases c JOIN projects p ON p.id=c.project_id WHERE c.id=?',(cid,))
        if not c: raise AppError('Case not found.',404)
        self.check(uid,c['space_id'],'write_'+c['purpose'])
        if c['version']!=version: raise AppError('This case has changed. Refresh the page.',409)
        if status is not None and status not in STATUSES: raise AppError('Invalid status.')
        if assignee is not None:
            self.check(uid,c['space_id'],'assign')
            self.check(assignee,c['space_id'],'read_'+c['purpose'])
        self.db.execute('UPDATE cases SET status=?,assignee=?,version=version+1 WHERE id=?',(status or c['status'],assignee or c['assignee'],cid))
        self.audit(uid,'case_changed',c['space_id'],c['project_id'],c['purpose'],{'case':cid,'status':status,'assignee':assignee})

    def queue(self,method,payload,dedupe=None,sid=None,actor=None,permission=None):
        cur=self.db.execute('INSERT OR IGNORE INTO outbox(method,payload,dedupe,space_id,actor,permission,created_at) VALUES(?,?,?,?,?,?,?)',
                (method,dumps(payload),dedupe,sid,actor,permission,self.clock()))
        return cur.lastrowid if cur.rowcount else self.one('SELECT id FROM outbox WHERE dedupe=?',(dedupe,))['id']

    def note(self,uid,pid,purpose,text,guest=False,bot_name='FutarchistBot'):
        if purpose not in ('general','raise'): raise AppError('Invalid message type.')
        p=self.project(uid,pid,'write_'+purpose)
        text=bounded(text,3000,True)
        if guest:
            self.check(uid,p['space_id'],'send')
            u=self.actor(p['submitter'])
            if not u['started']: raise AppError('The representative has not started the bot yet.')
        mid=self.db.execute('INSERT INTO threads(project_id,purpose,actor,text,visibility,created_at) VALUES(?,?,?,?,?,?)',(pid,purpose,uid,text,'guest' if guest else 'internal',self.clock())).lastrowid
        if guest:
            token=secrets.token_urlsafe(18)
            self.db.execute('INSERT INTO reply_tokens VALUES(?,?,?,?,?,0)',(token,pid,purpose,p['submitter'],self.clock()+7*86400))
            self.queue('sendMessage',{'chat_id':p['submitter'],'text':text,'reply_markup':{'inline_keyboard':[[{'text':'Reply','url':f'https://t.me/{bot_name}?start=reply_{token}'}]]}},f'note:{mid}',p['space_id'],uid,'send|read_'+purpose)
        self.audit(uid,'question_sent' if guest else 'note_added',p['space_id'],pid,purpose)
        return mid

    def history(self,uid,pid,include_archived=False):
        p=self.project(uid,pid,include_archived=include_archived)
        can_raise='read_raise' in self.permissions(uid,p['space_id'])
        threads=self.rows('SELECT t.*,u.name actor_name FROM threads t JOIN users u ON u.id=t.actor WHERE t.project_id=? AND t.deleted_at IS NULL ORDER BY id',(pid,))
        audit=self.rows('SELECT a.*,u.name actor_name FROM activity a JOIN users u ON u.id=a.actor WHERE a.project_id=? ORDER BY id',(pid,))
        return {'threads':[t for t in threads if t['purpose']!='raise' or can_raise], 'activity':[a for a in audit if a['purpose']!='raise' or can_raise]}

    def csv_export(self,uid,sid,filters):
        self.check(uid,sid,'export')
        rows=self.projects(uid,sid,filters)
        buf=io.StringIO(); writer=csv.writer(buf)
        finance='read_raise' in self.permissions(uid,sid)
        header=['id','name','categories','stage','network','website','representative']
        if finance: header+=['raise_status','platform','currency','target_amount','raised_amount']
        writer.writerow(header)
        for p in rows:
            g=p['general']; f=p['fundraising'] or {}
            cells=[p['id'],g['name'],','.join(g['categories']),g['stage'],g['network'],g.get('website',''),g.get('contact','')]
            if finance: cells += [f.get(k,'') for k in header[7:]]
            cells=[("'"+str(v)) if str(v).lstrip().startswith(('=','+','-','@','\t','\r')) else v for v in cells]
            writer.writerow(cells)
        self.audit(uid,'csv_exported',sid,purpose='raise' if is_financial_filter(filters or {}) else 'general',details={'count':len(rows)})
        return '\ufeff'+buf.getvalue()

    def login(self,uid):
        if self.actor(uid)['role'] not in ('owner','admin'): raise AppError('This account is not an admin.',403)
        token=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(24)
        self.db.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),uid,csrf,self.clock()+12*3600))
        return token,csrf

    def login_link(self,uid):
        if self.actor(uid)['role'] not in ('owner','admin'): raise AppError('This account is not an admin.',403)
        token=secrets.token_urlsafe(32)
        self.db.execute('INSERT INTO login_links VALUES(?,?,?,0)',(hashlib.sha256(token.encode()).hexdigest(),uid,self.clock()+300))
        return token

    def consume_link(self,token):
        digest=hashlib.sha256(token.encode()).hexdigest()
        row=self.one('SELECT * FROM login_links WHERE token_hash=? AND used=0 AND expires>?',(digest,self.clock()))
        if not row: raise AppError('The login link has expired or was used. In the bot, send /admin first.',401)
        self.actor(row['user_id'])
        self.db.execute('UPDATE login_links SET used=1 WHERE token_hash=?',(digest,))
        return self.login(row['user_id'])

    def session(self,token):
        s=self.one('SELECT * FROM sessions WHERE token_hash=? AND expires>?',(hashlib.sha256(token.encode()).hexdigest(),self.clock()))
        if not s: raise AppError('Sign in again.',401)
        self.actor(s['user_id'])
        return dict(s)

    def backup(self,path):
        with self.lock:
            target=sqlite3.connect(path)
            source=self.db
            if self.db.in_transaction:
                if self.path==':memory:':raise AppError('An in-memory backup is unavailable inside a transaction.')
                from urllib.parse import quote
                source=sqlite3.connect('file:'+quote(str(Path(self.path).resolve()),safe='/')+'?mode=ro',uri=True)
            try:source.backup(target)
            finally:
                if source is not self.db:source.close()
                target.close()
