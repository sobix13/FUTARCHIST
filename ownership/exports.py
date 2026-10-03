"""Portable CSV/OOXML exports. All values are literal data, never formulas."""
from __future__ import annotations
import csv
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape
from .core import AppError, dumps, is_financial_filter
from .management import Management

DATASETS=('projects','cases','raise','notes','events','tasks','campaigns','activity','routes','groups')
HEADERS={
 'projects':['id','workspace','name','categories','motivation','stage','network','website','socials','representative','telegram_id','created_at_utc','updated_at_utc','version','archived'],
 'cases':['id','project_id','project','purpose','source_admin','source_name','route_id','assignee','assignee_name','status','version'],
 'raise':['project_id','project','raise_status','retry','platform','currency','target_amount','raised_amount','metadao'],
 'notes':['id','project_id','purpose','actor','actor_name','visibility','text','created_at_utc','version'],
 'events':['id','title','kind','topic','starts_at_utc','timezone','status','description','outcome','creator','creator_name','version'],
 'tasks':['id','title','purpose','assignee','assignee_name','project_id','event_id','due_at_utc','status','creator','version'],
 'campaigns':['campaign_id','topic','when','creator','creator_name','state','project_id','project','destination_type','chat_id','response','delivery_state'],
 'activity':['id','project_id','purpose','actor','actor_name','action','created_at_utc'],
 'routes':['id','name','purpose','source_admin','source_name','assignee','assignee_name','active','uses','max_uses','expires_at_utc','bound_user'],
 'groups':['project_id','project','chat_id','name','active','consent_actor'],
}

def utc(value):
    return datetime.fromtimestamp(value,timezone.utc).isoformat(timespec='seconds') if value is not None else ''

def csv_bytes(headers,rows):
    buf=io.StringIO();writer=csv.writer(buf);writer.writerow(headers)
    for row in rows:
        cells=[]
        for value in row:
            text='' if value is None else str(value)
            if text.lstrip().startswith(('=','+','-','@','\t','\r')):text="'"+text
            cells.append(text)
        writer.writerow(cells)
    return ('\ufeff'+buf.getvalue()).encode()

def column_name(n):
    name=''
    while n:n,remainder=divmod(n-1,26);name=chr(65+remainder)+name
    return name

def xml_text(value):
    # XML 1.0 excludes control characters and lone surrogates.
    value=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]','',str(value))
    if len(value)>32767:raise AppError('A cell is too long for Excel. Choose CSV instead.')
    return escape(value)

def xlsx_bytes(tables):
    buf=io.BytesIO();ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    if not tables:raise AppError('No dataset is available to export.')
    names=list(tables)
    for name in names:
        if len(name)>31 or any(c in name for c in '\\/*?:[]'):raise AppError('Invalid worksheet name.')
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'+''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1,len(names)+1))+'</Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml',f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><bookViews><workbookView/></bookViews><sheets>'+''.join(f'<sheet name="{xml_text(name)}" sheetId="{i}" r:id="rId{i}"/>' for i,name in enumerate(names,1))+'</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,len(names)+1))+f'<Relationship Id="rId{len(names)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr('xl/styles.xml',f'<styleSheet xmlns="{ns}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF152E35"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
        for i,(name,(headers,rows)) in enumerate(tables.items(),1):
            if len(rows)>100000:raise AppError('The export is too large. Apply a narrower filter.')
            all_rows=[headers]+rows;rendered=[]
            for rnum,row in enumerate(all_rows,1):
                cells=''.join(f'<c r="{column_name(cnum)}{rnum}" s="{1 if rnum==1 else 0}" t="inlineStr"><is><t xml:space="preserve">{xml_text("" if value is None else value)}</t></is></c>' for cnum,value in enumerate(row,1))
                rendered.append(f'<row r="{rnum}">{cells}</row>')
            end=f'{column_name(len(headers))}{max(1,len(all_rows))}'
            cols=''.join(f'<col min="{n}" max="{n}" width="{min(48,max(16,len(h)+4))}" customWidth="1"/>' for n,h in enumerate(headers,1))
            sheet=f'<worksheet xmlns="{ns}"><dimension ref="A1:{end}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>{cols}</cols><sheetData>'+''.join(rendered)+f'</sheetData><autoFilter ref="A1:{end}"/></worksheet>'
            z.writestr(f'xl/worksheets/sheet{i}.xml',sheet)
    return buf.getvalue()

class Exports:
    def __init__(self,store,service):self.s=store;self.service=service;self.management=Management(store,service)

    def tables(self,uid,sid,dataset='projects',filters=None):
        self.s.check(uid,sid,'export')
        if dataset not in DATASETS+('all',):raise AppError('Invalid export type.')
        finance='read_raise' in self.s.permissions(uid,sid)
        if dataset=='raise' and not finance:raise AppError('You do not have raise export access.',403)
        projects=self.s.projects(uid,sid,filters or {});by_id={p['id']:p for p in projects};ids=set(by_id)
        chosen=list(DATASETS) if dataset=='all' else [dataset]
        if not finance:chosen=[d for d in chosen if d!='raise']
        # Export permission alone does not expose administrative route codes or invitations.
        permissions=self.s.permissions(uid,sid)
        if dataset=='all':chosen=[d for d in chosen if (d!='routes' or 'routes' in permissions) and (d!='campaigns' or 'send' in permissions)]
        tables={}
        for d in chosen:
            rows=[]
            if d=='projects':
                for p in projects:
                    g=p['general'];rows.append([p['id'],sid,g['name'],', '.join(g['categories']),g.get('motivation'),g['stage'],g['network'],g.get('website'),g.get('socials'),g.get('contact'),p['submitter'],utc(p['created_at']),utc(p['updated_at']),p['version'],bool(p['archived_at'])])
            elif d=='cases':
                for p in projects:
                    for c in p['cases']:rows.append([c['id'],p['id'],p['general']['name'],c['purpose'],c['source_admin'],c['source_name'],c['route_id'],c['assignee'],c['assignee_name'],c['status'],c['version']])
            elif d=='raise':
                for p in projects:
                    if not any(c['purpose']=='raise' for c in p['cases']):continue
                    f=p['fundraising'];rows.append([p['id'],p['general']['name']]+[f.get(k) for k in HEADERS[d][2:]])
            elif d=='notes':
                for p in projects:
                    for n in self.s.history(uid,p['id'],include_archived=bool(p['archived_at']))['threads']:rows.append([n['id'],p['id'],n['purpose'],n['actor'],n['actor_name'],n['visibility'],n['text'],utc(n['created_at']),n['version']])
            elif d=='events':
                for e in self.management.events(uid,sid):
                    linked={r['project_id'] for r in self.s.rows('SELECT project_id FROM event_projects WHERE event_id=?',(e['id'],))}
                    if filters and linked and not linked&ids:continue
                    rows.append([e['id'],e['title'],e['kind'],e['topic'],utc(e['starts_at']),e['timezone'],e['status'],e['description'],e['outcome'],e['creator'],e['creator_name'],e['version']])
            elif d=='tasks':
                for t in self.management.tasks(uid,sid):
                    if filters and t['project_id'] and t['project_id'] not in ids:continue
                    rows.append([t['id'],t['title'],t['purpose'],t['assignee'],t['assignee_name'],t['project_id'],t['event_id'],utc(t['due_at']),t['status'],t['creator'],t['version']])
            elif d=='campaigns':
                for c in self.service.campaigns(uid,sid):
                    for r in self.service.campaign_detail(uid,c['id'])['recipients']:
                        if r['project_id'] not in ids:continue
                        rows.append([c['id'],c['topic'],c['when_text'],c['creator'],c['creator_name'],c['state'],r['project_id'],r['project_name'],r['kind'],r['chat_id'],r['response'],r['delivery_state']])
            elif d=='activity':
                for a in self.service.audit(uid,sid,limit=None):
                    if a['project_id'] and a['project_id'] not in ids:continue
                    rows.append([a['id'],a['project_id'],a['purpose'],a['actor'],a['actor_name'],a['action'],utc(a['created_at'])])
            elif d=='routes':
                for r in self.service.routes(uid,sid):rows.append([r['id'],r['name'],r['purpose'],r['creator'],r['source_name'],r['assignee'],r['assignee_name'],bool(r['active']),r['uses'],r['max_uses'],utc(r['expires']),r['bound_user']])
            elif d=='groups':
                for p in projects:
                    g=self.service.group(uid,p['id'])
                    if g:rows.append([p['id'],p['general']['name'],g['chat_id'],g['name'],bool(g['active']),g['consent_actor']])
            tables[d]=(HEADERS[d],rows)
        return tables

    def build(self,uid,sid,dataset='projects',format='xlsx',filters=None):
        if format not in ('csv','xlsx'):raise AppError('Invalid export format.')
        tables=self.tables(uid,sid,dataset,filters)
        if any(len(rows)>100000 for _,rows in tables.values()):raise AppError('The dataset is too large. Narrow the filter.')
        if format=='xlsx':body=xlsx_bytes(tables);extension='xlsx';mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        elif len(tables)==1:
            headers,rows=next(iter(tables.values()));body=csv_bytes(headers,rows);extension='csv';mime='text/csv; charset=utf-8'
        else:
            buf=io.BytesIO()
            with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
                for name,(headers,rows) in tables.items():z.writestr(name+'.csv',csv_bytes(headers,rows))
            body=buf.getvalue();extension='zip';mime='application/zip'
        if len(body)>20_000_000:raise AppError('The export exceeds the app\'s size limit. Narrow the filter.')
        finance='raise' in tables or any(row[3]=='raise' for row in tables.get('cases',([],[]))[1]) or any(row[2]=='raise' for row in tables.get('notes',([],[]))[1]) or any(row[2]=='raise' for row in tables.get('events',([],[]))[1]) or any(row[2]=='raise' for row in tables.get('tasks',([],[]))[1])
        self.s.audit(uid,'export_created',sid,purpose='raise' if finance or is_financial_filter(filters or {}) else 'general',details={'dataset':dataset,'format':format,'rows':sum(len(r) for h,r in tables.values())})
        return body,f'futarchist-{sid}-{dataset}.{extension}',mime
