#!/usr/bin/env python3
"""Consistent backup or restore into a NEW file. Never overwrites a database."""
import argparse
import os
import sqlite3
from pathlib import Path
from urllib.parse import quote

def copy_database(source,destination):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if not source.is_file(): raise ValueError('Source database does not exist')
    if destination==source or destination.exists(): raise ValueError('Destination already exists; choose a new filename')
    if not destination.parent.is_dir(): raise ValueError('Destination parent directory does not exist')
    db=sqlite3.connect('file:'+quote(str(source),safe='/')+'?mode=ro',uri=True)
    try:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Source integrity check failed')
        if db.execute('PRAGMA user_version').fetchone()[0] not in (1,2):raise ValueError('Unsupported database schema')
        fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        target=sqlite3.connect(destination)
        try:
            db.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup integrity check failed')
            counts={t:target.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('projects','cases','users')}
        finally:target.close()
    finally:db.close()
    return counts

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['backup','restore']);parser.add_argument('--source',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args()
    try:counts=copy_database(args.source,args.output)
    except (ValueError,sqlite3.Error,OSError) as e:parser.exit(1,str(e)+'\n')
    print(args.action+' verified: '+str(counts))
    print('File contains private data. Encrypt it before remote storage. Restore only with the app stopped and use DATABASE_PATH pointing to the new file.')

if __name__=='__main__':main()
