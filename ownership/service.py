from __future__ import annotations
import json
import secrets
import string
from .core import AppError, PERMISSIONS, PRESETS, bounded, dumps, text_units, is_financial_filter
from .forms import label
from .management import Management

DEFAULT_TEMPLATE='Hi {project} team,\nWe are hosting {topic} at {when}. With your focus on {sector}, we would like to hear about your progress and plans. Reply using the link below.'

class Service:
    """All dashboard operations are authorized here, not in the browser."""
    def __init__(self,store,bot_name='FutarchistBot'):
        self.s=store; self.name=bot_name; self.management=Management(store,self)

    def me(self,uid):
        user=self.s.actor(uid)
        if user['role'] not in ('owner','admin'): raise AppError('The dashboard is restricted to approved admins.',403)
        return {'user':user,'spaces':self.s.spaces(uid),'permissions':list(PERMISSIONS),'presets':PRESETS,
                'bot_name':self.name,'default_template':self.management.text('invite_template')}

    def members(self,uid,sid):
        self.s.check(uid,sid,'read_general')
        people=self.s.rows("SELECT u.id,u.name,u.active,m.permissions FROM members m JOIN users u ON u.id=m.user_id WHERE m.space_id=? ORDER BY u.name",(sid,))
        owners=self.s.rows("SELECT id,name,active FROM users WHERE role='owner' ORDER BY id")
        return [dict(owner,permissions=list(PERMISSIONS)) for owner in owners]+[{**p,'permissions':json.loads(p['permissions'])} for p in people]

    def admins(self,uid):
        self.s.owner(uid)
        return self.s.rows("SELECT id,name,active,started FROM users WHERE role='admin' ORDER BY name")

    def routes(self,uid,sid):
        self.s.check(uid,sid,'routes')
        rows=self.s.rows('SELECT r.*,u.name source_name,a.name assignee_name FROM routes r JOIN users u ON u.id=r.creator JOIN users a ON a.id=r.assignee WHERE r.space_id=? ORDER BY r.id DESC',(sid,))
        if self.s.gated:rows=[r for r in rows if r['token']!='public']
        if 'read_raise' not in self.s.permissions(uid,sid):rows=[r for r in rows if r['purpose']=='general']
        return [{**r,'url':f'https://t.me/{self.name}?start=intake_{r["token"]}'} for r in rows]

    def route_status(self,uid,rid,active):
        r=self.s.one('SELECT * FROM routes WHERE id=?',(rid,))
        if not r: raise AppError('Route not found.',404)
        self.s.check(uid,r['space_id'],'routes')
        if r['purpose']!='general': self.s.check(uid,r['space_id'],'read_raise')
        if self.s.actor(uid)['role']!='owner' and r['creator']!=uid:raise AppError('Changing another admin\'s code requires superadmin access.',403)
        self.s.db.execute('UPDATE routes SET active=? WHERE id=?',(int(active),rid))
        self.s.audit(uid,'route_status',r['space_id'],details={'route':rid,'active':active})

    def binding(self,uid,pid):
        p=self.s.project(uid,pid,'send')
        token=secrets.token_urlsafe(18)
        self.s.db.execute('INSERT INTO bindings VALUES(?,?,?,?,0)',(token,pid,uid,self.s.clock()+600))
        self.s.audit(uid,'group_binding_created',p['space_id'],pid)
        return {'command':'/bind '+token,'expires_in':600,
                'instruction':'Add the bot to the group. The admin who created the code or the project\'s representative must send this command as a group admin. The code is single-use and expires in 10 minutes.'}

    def group(self,uid,pid,disconnect=False):
        p=self.s.project(uid,pid,'send' if disconnect else 'read_general')
        if disconnect:
            self.s.db.execute('UPDATE groups SET active=0 WHERE project_id=?',(pid,))
            self.s.audit(uid,'group_disconnected',p['space_id'],pid)
        row=self.s.one('SELECT * FROM groups WHERE project_id=?',(pid,))
        return dict(row) if row else None

    def validate_template(self,template):
        template=bounded(template,2800,True)
        try:
            for literal,field,fmt,conversion in string.Formatter().parse(template):
                if field is not None and (field not in ('project','topic','when','sector') or fmt or conversion):
                    raise ValueError()
        except ValueError: raise AppError('Supported variables: {project}, {topic}, {when}, {sector}.') from None
        return template

    def campaign(self,uid,sid,topic,when_text,template,filters):
        self.s.check(uid,sid,'send')
        topic=bounded(topic,160,True); when_text=bounded(when_text,160,True)
        template=self.validate_template(template)
        projects=self.s.projects(uid,sid,filters)
        cid=self.s.db.execute('INSERT INTO campaigns(space_id,creator,topic,when_text,template,filters,created_at) VALUES(?,?,?,?,?,?,?)',
                (sid,uid,topic,when_text,template,dumps(filters),self.s.clock())).lastrowid
        used=set(); skipped=[]
        for p in projects:
            g=self.s.one('SELECT * FROM groups WHERE project_id=? AND active=1',(p['id'],))
            u=self.s.actor(p['submitter'])
            if g: chat,kind=g['chat_id'],'group'
            elif u['started'] and u['invites']: chat,kind=u['id'],'dm'
            else:
                skipped.append({'project':p['id'],'name':p['general']['name'],'reason':'No connected group or representative with DM invitation consent.'}); continue
            if chat in used:
                skipped.append({'project':p['id'],'name':p['general']['name'],'reason':'Duplicate destination. Each destination receives one invitation.'}); continue
            used.add(chat)
            text=template.format(project=p['general']['name'],topic=topic,when=when_text,
                                 sector=', '.join(label(c) for c in p['general']['categories']))
            if text_units(text)>3800: raise AppError('The personalized message is too long.')
            token=secrets.token_urlsafe(18)
            self.s.db.execute('INSERT INTO recipients(campaign_id,project_id,chat_id,kind,text,token) VALUES(?,?,?,?,?,?)',(cid,p['id'],chat,kind,text,token))
        self.s.audit(uid,'campaign_preview',sid,purpose='raise' if self.financial(filters) else 'general',details={'campaign':cid,'count':len(used)})
        return {**self.campaign_detail(uid,cid),'skipped':skipped}

    def campaigns(self,uid,sid):
        self.s.check(uid,sid,'send')
        result=[]
        for c in self.s.rows('SELECT c.*,u.name creator_name FROM campaigns c JOIN users u ON u.id=c.creator WHERE space_id=? ORDER BY c.id DESC',(sid,)):
            # Filter selections themselves may reveal financial information.
            if self.financial(json.loads(c['filters'])) and 'read_raise' not in self.s.permissions(uid,sid): continue
            counts=self.s.one('SELECT COUNT(*) total,SUM(response=\'yes\') yes,SUM(response=\'no\') no,SUM(response=\'later\') later FROM recipients WHERE campaign_id=?',(c['id'],))
            result.append({**c,'counts':dict(counts)})
        return result

    @staticmethod
    def financial(filters):
        return is_financial_filter(filters)

    def campaign_detail(self,uid,cid):
        c=self.s.one('SELECT c.*,u.name creator_name FROM campaigns c JOIN users u ON u.id=c.creator WHERE c.id=?',(cid,))
        if not c: raise AppError('Invitation not found.',404)
        self.s.check(uid,c['space_id'],'send')
        if self.financial(json.loads(c['filters'])): self.s.check(uid,c['space_id'],'read_raise')
        recipients=self.s.rows('SELECT r.*,p.general,o.state delivery_state,o.error delivery_error FROM recipients r JOIN projects p ON p.id=r.project_id LEFT JOIN outbox o ON o.id=r.outbox_id WHERE campaign_id=? ORDER BY r.id',(cid,))
        for r in recipients:
            r['project_name']=json.loads(r.pop('general'))['name']
            # Token is useful only to the project representative, not an admin credential.
        return {**dict(c),'filters':json.loads(c['filters']),'recipients':recipients}

    def confirm(self,uid,cid):
        c=self.campaign_detail(uid,cid)
        if c['state']!='draft': raise AppError('This invitation was already confirmed or cancelled.',409)
        if not c['recipients']: raise AppError('No permitted destination was found.')
        # Validate all filters again using the confirmer's current permissions.
        self.s.projects(uid,c['space_id'],c['filters'])
        self.s.db.execute("UPDATE campaigns SET state='queued' WHERE id=?",(cid,))
        for r in c['recipients']:
            payload={'chat_id':r['chat_id'],'text':r['text'],'reply_markup':{'inline_keyboard':[[{'text':'Reply to invitation','url':f'https://t.me/{self.name}?start=invite_{r["token"]}'}]]}}
            perms='send|read_general'+('|read_raise' if self.financial(c['filters']) else '')
            oid=self.s.queue('sendMessage',payload,f'campaign:{cid}:{r["id"]}',c['space_id'],uid,perms)
            self.s.db.execute('UPDATE recipients SET outbox_id=? WHERE id=?',(oid,r['id']))
        self.s.audit(uid,'campaign_confirmed',c['space_id'],purpose='raise' if self.financial(c['filters']) else 'general',details={'campaign':cid,'count':len(c['recipients'])})
        return self.campaign_detail(uid,cid)

    def cancel(self,uid,cid):
        c=self.campaign_detail(uid,cid)
        if c['state']=='cancelled': return
        self.s.db.execute("UPDATE campaigns SET state='cancelled' WHERE id=?",(cid,))
        self.s.db.execute("UPDATE outbox SET state='cancelled',error='Campaign cancelled' WHERE state='pending' AND id IN (SELECT outbox_id FROM recipients WHERE campaign_id=?)",(cid,))
        self.s.audit(uid,'campaign_cancelled',c['space_id'],purpose='raise' if self.financial(c['filters']) else 'general',details={'campaign':cid})

    def views(self,uid,sid):
        self.s.check(uid,sid,'read_general')
        rows=[{**v,'filters':json.loads(v['filters'])} for v in self.s.rows('SELECT * FROM views WHERE space_id=? AND user_id=? ORDER BY id',(sid,uid))]
        return [v for v in rows if not self.financial(v['filters']) or 'read_raise' in self.s.permissions(uid,sid)]

    def save_view(self,uid,sid,name,filters):
        self.s.projects(uid,sid,filters)
        vid=self.s.db.execute('INSERT INTO views(space_id,user_id,name,filters) VALUES(?,?,?,?)',(sid,uid,bounded(name,100,True),dumps(filters))).lastrowid
        return vid

    def delete_view(self,uid,vid):
        row=self.s.one('SELECT * FROM views WHERE id=? AND user_id=?',(vid,uid))
        if not row: raise AppError('Saved filter not found.',404)
        self.s.check(uid,row['space_id'],'read_general')
        self.s.db.execute('DELETE FROM views WHERE id=?',(vid,))

    def audit(self,uid,sid=None,limit=500):
        if sid:
            self.s.check(uid,sid,'read_general')
            sql='SELECT a.*,u.name actor_name FROM activity a JOIN users u ON u.id=a.actor WHERE a.space_id=?'
            args=[sid]
            if 'read_raise' not in self.s.permissions(uid,sid): sql+=" AND a.purpose!='raise'"
        else:
            self.s.owner(uid)
            sql='SELECT a.*,u.name actor_name FROM activity a JOIN users u ON u.id=a.actor WHERE a.space_id IS NULL'; args=[]
        if limit is not None and (type(limit) is not int or not 1<=limit<=100000):raise AppError('Invalid activity limit.')
        return self.s.rows(sql+' ORDER BY a.id DESC'+(' LIMIT '+str(limit) if limit else ''),args)

    def deliveries(self,uid,sid):
        self.s.check(uid,sid,'send')
        rows=self.s.rows('SELECT id,method,dedupe,state,attempts,next_at,error,actor,permission,created_at FROM outbox WHERE space_id=? ORDER BY id DESC LIMIT 300',(sid,))
        return [r for r in rows if 'read_raise' not in (r['permission'] or '') or 'read_raise' in self.s.permissions(uid,sid)]
