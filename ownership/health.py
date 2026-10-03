"""Observed health and narrow repairs, without rewriting code or business data."""
from __future__ import annotations
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path
from .core import AppError, dumps

class Health:
    def __init__(self,store):self.s=store

    def beat(self,component,state='ok',detail=''):
        self.s.db.execute('INSERT INTO heartbeats VALUES(?,?,?,?) ON CONFLICT(component) DO UPDATE SET state=excluded.state,last_at=excluded.last_at,detail=excluded.detail',(component,state,self.s.clock(),detail[:160]))

    def incident(self,component,code,summary,severity='error'):
        # Callers supply fixed descriptions, not user data, secrets, URLs or tracebacks.
        row=self.s.one("SELECT id FROM incidents WHERE component=? AND code=? AND state='open'",(component,code))
        if row:
            self.s.db.execute('UPDATE incidents SET count=count+1,updated_at=? WHERE id=?',(self.s.clock(),row['id']));return row['id']
        return self.s.db.execute('INSERT INTO incidents(component,code,severity,summary,created_at,updated_at) VALUES(?,?,?,?,?,?)',(component,code,severity,summary[:240],self.s.clock(),self.s.clock())).lastrowid

    def recovered(self,component,code):
        self.s.db.execute("UPDATE incidents SET state='resolved',resolved_at=? WHERE component=? AND code=? AND state='open'",(self.s.clock(),component,code))

    def snapshot(self,uid):
        self.s.owner(uid)
        now=self.s.clock();checks={}
        quick=self.s.one('PRAGMA quick_check')['quick_check'];checks['database']={'state':'ok' if quick=='ok' else 'failed','detail':'SQLite quick_check'}
        foreign=self.s.rows('PRAGMA foreign_key_check');checks['references']={'state':'ok' if not foreign else 'failed','count':len(foreign)}
        heartbeat=self.s.rows('SELECT * FROM heartbeats ORDER BY component')
        for h in heartbeat:
            timeout=90 if h['component'] in ('poller','maintenance') else 30
            checks[h['component']]={**h,'state':'stale' if now-h['last_at']>timeout else h['state'],'age_seconds':round(now-h['last_at'],1)}
        directory=Path(self.s.path).parent if self.s.path!=':memory:' else Path('.')
        disk=shutil.disk_usage(directory);checks['disk']={'state':'ok' if disk.free>100_000_000 else 'low','free_bytes':disk.free}
        outbox=self.s.rows('SELECT state,COUNT(*) count FROM outbox GROUP BY state')
        inbox=self.s.rows('SELECT update_id,attempts,error FROM inbox WHERE done=0 ORDER BY update_id LIMIT 100')
        return {'checks':checks,'outbox':outbox,'inbox':inbox,'incidents':self.s.rows('SELECT * FROM incidents ORDER BY id DESC LIMIT 100'),'database_version':2,
                'autorepair':'bounded queue recovery and expiry cleanup','support':[{'username':'sobix13','id':313342234},{'username':'SrMessiSOL','id':5691137098}]}

    def repair(self,uid=None,automatic=False):
        if not automatic:self.s.owner(uid)
        result={'expired':0,'recovered_updates':0}
        now=self.s.clock()
        for table in ('sessions','login_links','reply_tokens','bindings','operation_tokens'):
            result['expired']+=self.s.db.execute('DELETE FROM '+table+' WHERE expires<?',(now,)).rowcount
        # Retry only verification that did not send anything and is known to be transient.
        result['recovered_updates']=self.s.db.execute("UPDATE inbox SET attempts=0,error=NULL,next_at=0 WHERE done=0 AND attempts>=5 AND error='Group verification temporarily unavailable' AND received_at>?",(now-3600,)).rowcount
        self.s.db.execute('DELETE FROM native_flows WHERE updated_at<?',(now-7*86400,))
        self.beat('maintenance')
        if uid:self.s.audit(uid,'safe_repair',details=result)
        return result

    def retry_update(self,uid,update_id):
        self.s.owner(uid)
        row=self.s.one('SELECT * FROM inbox WHERE update_id=? AND done=0',(update_id,))
        if not row:raise AppError('Failed update not found.',404)
        # The whole update transaction rolled back. Retrying cannot replay committed changes.
        self.s.db.execute('UPDATE inbox SET attempts=0,error=NULL,next_at=0 WHERE update_id=?',(update_id,))
        self.s.audit(uid,'update_retried',details={'update_id':update_id})

    def resolve(self,uid,iid):
        self.s.owner(uid)
        self.s.db.execute("UPDATE incidents SET state='acknowledged',resolved_at=? WHERE id=? AND state='open'",(self.s.clock(),iid))
        self.s.audit(uid,'incident_acknowledged',details={'incident':iid})

    def backup(self,uid):
        self.s.owner(uid)
        directory=Path(self.s.path).parent/'backups';directory.mkdir(mode=0o700,exist_ok=True)
        name='futarchist-'+str(time.time_ns())+'.sqlite3';target=directory/name
        if target.exists():raise AppError('A backup already uses this filename.')
        self.s.backup(target)
        conn=sqlite3.connect('file:'+str(target)+'?mode=ro',uri=True)
        try:
            if conn.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise AppError('Backup integrity check failed.')
        finally:conn.close()
        os.chmod(target,0o600)
        self.s.audit(uid,'backup_created',details={'file':name})
        return {'name':name,'bytes':target.stat().st_size,'verified':True}
