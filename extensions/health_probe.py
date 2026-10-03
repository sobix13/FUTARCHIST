#!/usr/bin/env python3
"""Read-only database and worker-liveness probe. Never repairs or restarts."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sqlite3
import time
from urllib.parse import quote

def probe(database,mode='bot',max_age=180,clock=time.time):
    if mode not in ('bot','web','all') or not 60<=max_age<=3600:raise ValueError('Invalid mode or age limit')
    path=Path(database).resolve()
    if not path.is_file():raise ValueError('Database does not exist')
    db=sqlite3.connect('file:'+quote(str(path),safe='/')+'?mode=ro',uri=True,timeout=3);db.row_factory=sqlite3.Row
    try:
        good=db.execute('PRAGMA quick_check').fetchone()[0]=='ok' and not db.execute('PRAGMA foreign_key_check').fetchall()
        if db.execute('PRAGMA user_version').fetchone()[0]!=2:raise ValueError('Schema 2 is required')
        expected=(['poller','inbox','outbox','maintenance'] if mode in ('bot','all') else [])+(['web'] if mode in ('web','all') else [])
        beats={r['component']:dict(r) for r in db.execute('SELECT * FROM heartbeats')};rows=[]
        for component in expected:
            beat=beats.get(component);age=clock()-beat['last_at'] if beat else None
            rows.append({'component':component,'age_seconds':round(age,2) if age is not None else None,'state':beat['state'] if beat else 'missing','live':age is not None and -60<=age<=max_age})
        return {'live':good and all(r['live'] for r in rows),'database':'ok' if good else 'failed','workers':rows,'connectivity_degraded':any(r['state']=='degraded' for r in rows)}
    finally:db.close()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--database',required=True);p.add_argument('--mode',choices=['bot','web','all'],default='bot');p.add_argument('--max-age',type=int,default=180);a=p.parse_args()
    try:result=probe(a.database,a.mode,a.max_age)
    except (ValueError,sqlite3.Error,OSError):print(json.dumps({'live':False,'error':'Probe unavailable. Check database path, schema and access.'}));return 2
    print(json.dumps(result));return 0 if result['live'] else 1

if __name__=='__main__':raise SystemExit(main())
