#!/usr/bin/env python3
"""Three backend passes, English audit, DOM integration and live evidence."""
from __future__ import annotations
import datetime
import html
import importlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import unittest
from html.parser import HTMLParser

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));os.chdir(ROOT)

class ReportResult(unittest.TextTestResult):
    def __init__(self,*a,**kw):super().__init__(*a,**kw);self.entries=[]
    def startTest(self,test):super().startTest(test);self.started=time.monotonic()
    def addSuccess(self,test):super().addSuccess(test);self.entries.append({'test':test.id(),'status':'passed','seconds':round(time.monotonic()-self.started,4)})
    def addFailure(self,test,err):super().addFailure(test,err);self.entries.append({'test':test.id(),'status':'failed','error':self._exc_info_to_string(err,test)})
    def addError(self,test,err):super().addError(test,err);self.entries.append({'test':test.id(),'status':'error','error':self._exc_info_to_string(err,test)})
    def addSkip(self,test,reason):super().addSkip(test,reason);self.entries.append({'test':test.id(),'status':'skipped','reason':reason})

def phase(name,modules):
    suite=unittest.TestSuite();stream=io.StringIO()
    for module in modules:suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(module)))
    start=time.monotonic();result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=ReportResult).run(suite)
    print(name+': '+str(result.testsRun)+' tests, '+('PASSED' if result.wasSuccessful() else 'FAILED'),flush=True)
    return {'name':name,'status':'passed' if result.wasSuccessful() else 'failed','tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'seconds':round(time.monotonic()-start,3),'entries':result.entries,'log':stream.getvalue()}

def command(name,args):
    r=subprocess.run(args,capture_output=True,text=True);print(name+': '+('PASSED' if r.returncode==0 else 'FAILED'),flush=True)
    return {'name':name,'status':'passed' if r.returncode==0 else 'failed','exit_code':r.returncode,'output':r.stdout+r.stderr}

class GuideParser(HTMLParser):
    def __init__(self):super().__init__();self.ids=[];self.links=[];self.images=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if a.get('id'):self.ids.append(a['id'])
        if tag=='a' and a.get('href','').startswith('#'):self.links.append(a['href'][1:])
        if tag=='img':self.images.append(a['src'])

def guide_check():
    p=GuideParser();p.feed((ROOT/'ownership/static/guide.html').read_text());assert len(p.ids)==len(set(p.ids));assert set(p.links)<=set(p.ids)
    for image in p.images:assert (ROOT/'ownership/static'/image.lstrip('/')).is_file(),image
    return {'name':'Guide sections, internal anchors and original logo assets','status':'passed','sections':len(p.ids),'images':len(p.images)}

def english_check():
    paths=[ROOT/'README.md']
    for folder in ('ownership','futarchist','tests','docs','extensions','tools'):
        paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.js','.mjs','.html','.css','.md','.sql','.example'))
    violations=[]
    for path in paths:
        value=path.read_text()
        if re.search(r'[\u0600-\u06ff]',value):violations.append(str(path.relative_to(ROOT)))
    for name in ('index.html','emulator.html','guide.html'):
        value=(ROOT/'ownership/static'/name).read_text()
        if '<html lang="en" dir="ltr">' not in value:violations.append(name+': wrong document language')
    return {'name':'English-only source, documentation and HTML language audit','status':'failed' if violations else 'passed','files':len(paths),'violations':violations}

def main():
    report={'version':'2.1.0','interface_language':'en','timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'environment':{'python':sys.version.split()[0],'platform':sys.platform,'runtime_dependencies':'Python standard library','virtual_environment':sys.prefix!=sys.base_prefix}}
    first=['tests.test_core'];second=['tests.test_bot','tests.test_delivery','tests.test_http','tests.test_futarchist','tests.test_native','tests.test_operations','tests.test_language'];full=first+second+['tests.test_regression']
    report['phases']=[phase('1. Core and independent access rules',first),phase('2. Native Telegram, HTTP, exports, lifecycle and English migration',second),phase('3. Full regression, concurrency, isolation and backup',full)]
    report['unique_test_cases']=len({x['test'] for x in report['phases'][-1]['entries']})
    report['static_checks']=[command('Python compile',[sys.executable,'-W','error','-m','compileall','-q','ownership','futarchist','tests','extensions','tools']),guide_check(),english_check()]
    node=shutil.which('node')
    if node:
        for file in ('ownership/static/app.js','ownership/static/operations.js','ownership/static/emulator.js','tests/dom-check.mjs','tests/ui-check.mjs'):
            report['static_checks'].append(command('JavaScript syntax: '+file,[node,'--check',file]))
        report['static_checks'].append(command('Pure JavaScript data helpers',[node,'tests/client-helpers.mjs']))
        report['dom_command']=command('DOM integration with real local HTTP',[node,'tests/dom-check.mjs'])
    else:report['dom_command']={'status':'not_run','reason':'Node not installed'}
    for key,file,default in (
        ('dom_ui','dom-report.json',{'status':'not_run'}),
        ('live_telegram','live-telegram.json',{'status':'not_run','reason':'Run tools/live_check.py with your private env'}),
        ('browser_ui','ui-report.json',{'status':'not_run','reason':'Cloud browser blocked 127.0.0.1 with ERR_BLOCKED_BY_CLIENT. Chromium download failed. Visual rendering, mobile layout and official Mini App client flow remain unverified.'})):
        path=ROOT/'reports'/file;report[key]=json.loads(path.read_text()) if path.exists() else default
    report['backend_status']='passed' if all(p['status']=='passed' for p in report['phases']+report['static_checks']) else 'failed'
    report['release_status']='backend_and_dom_verified_real_client_acceptance_pending' if report['backend_status']=='passed' and report['dom_command']['status']=='passed' and report['dom_ui'].get('status')=='passed' else 'checks_incomplete'
    directory=ROOT/'reports';directory.mkdir(exist_ok=True);(directory/'test-results.json').write_text(json.dumps(report,indent=2))
    rows=''.join(f'<tr><td>{html.escape(p["name"])}</td><td>{p["tests"]}</td><td>{p["status"]}</td><td>{p["failures"]}</td><td>{p["errors"]}</td></tr>' for p in report['phases'])
    tests=''.join(f'<tr><td>{html.escape(e["test"])}</td><td>{e["status"]}</td></tr>' for e in report['phases'][-1]['entries'])
    dom=report['dom_ui'];live=report['live_telegram'];worker=live.get('worker_smoke',{})
    checks=''.join('<li>'+html.escape(c['name'])+'</li>' for c in dom.get('checks',[]))
    static=''.join('<li>'+html.escape(c['name'])+': '+c['status']+'</li>' for c in report['static_checks'])
    live_text='Live Bot API '+live.get('status','not_run')+' · '+live.get('username','')+' · worker '+worker.get('status','not_run')
    document=f'''<!doctype html><html lang="en" dir="ltr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FUTARCHIST | Test report</title>
<style>body{{margin:0;background:#f3f6f6;color:#193239;font:14px/1.7 system-ui,sans-serif}}main{{max-width:1100px;margin:30px auto;background:#fff;padding:32px;border:1px solid #d5e1e3;border-radius:14px}}h1{{font-size:28px}}h2{{margin-top:28px;font-size:19px}}table{{width:100%;border-collapse:collapse;font-size:12px}}td,th{{text-align:start;border-bottom:1px solid #dce5e7;padding:9px;overflow-wrap:anywhere}}.notice{{background:#fff8eb;border:1px solid #e9dcc2;padding:18px;border-radius:8px}}.ok{{background:#edf7f6;padding:18px;border-radius:8px}}@media(max-width:700px){{main{{margin:12px;padding:18px}}}}</style>
<main><h1>FUTARCHIST 2.1 · Test report</h1><p>{html.escape(report['timestamp_utc'])} · Python {report['environment']['python']} · Virtual environment: {report['environment']['virtual_environment']}</p>
<div class="ok"><strong>{report['unique_test_cases']} independent backend test cases · {report['backend_status']}</strong><p>Three passes ran separately. The third pass repeats the full suite, so total executions exceed the number of unique cases.</p></div>
<table><tr><th>Pass</th><th>Tests</th><th>Result</th><th>Failures</th><th>Errors</th></tr>{rows}</table>
<h2>English-only release</h2><p>Bot messages, questions, buttons, validation, dashboards, guides and sample content use English. No language selector remains. Upgrade tests cover legacy defaults, cached form titles, user-data preservation and idempotence.</p>
<h2>Static checks</h2><ul>{static}</ul>
<h2>Interface integration</h2><p>{len(dom.get('checks',[]))} DOM checks · {dom.get('status','not_run')} · real HTTP on loopback. This verifies interactive behavior without graphical browser rendering, layout measurement or screenshots.</p><ul>{checks}</ul>
<h2>Live Telegram connection</h2><p>{html.escape(live_text)}</p><p>Bot identity, name, privacy mode, webhook and command menus were read through the real API. Worker duration: {worker.get('seconds',0)} seconds. Received updates: {worker.get('received_updates','unknown')}. Delivered messages: {worker.get('delivered_messages','unknown')}.</p><p>Both superadmins are configured in the app. Their scoped command menus can be configured after their first Start using --configure-bot.</p>
<h2>Acceptance still required</h2><div class="notice"><p>The cloud browser blocked local access with ERR_BLOCKED_BY_CLIENT; the Chromium download also failed. Visual design, actual mobile layout, the official Telegram client, public HTTPS Mini App flow and real group invitation/reply flows are unverified.</p><p>A brief worker smoke test is not a human end-to-end test. Support account identities come from the supplied numeric IDs. Account ownership has not been checked through human login.</p><p>No production VPS is deployed. Large-scale load, real disk failure and an independent security audit have not been tested. Recovery is bounded; uninterrupted connectivity is not guaranteed.</p></div>
<h2>Regression coverage</h2><ul><li>Access revoked during a draft; old buttons cannot submit it.</li><li>General and financial permissions remain separate in forms, history, programs, tasks and exports.</li><li>Both superadmins have equal authority; personal and team workspaces stay isolated.</li><li>Stale edits are rejected; destructive confirmations are single-use.</li><li>Malformed updates and failed Excel exports do not block independent queues.</li><li>Verified backups run without request-transaction deadlocks.</li><li>Source attribution survives reassignment, code rotation and archiving.</li><li>Suspended authors remain attributed; exports are not limited to dashboard rows.</li><li>Late workspace responses cannot replace the current dashboard.</li><li>Raise status changes clear fields that no longer apply.</li></ul>
<h2>Final test cases</h2><table><tr><th>Test</th><th>Result</th></tr>{tests}</table><p>Built by Ownership · Support @sobix13 / @SrMessiSOL</p></main></html>'''
    (directory/'test-report.html').write_text(document)
    print('Backend: '+report['backend_status']+'. Unique tests: '+str(report['unique_test_cases'])+'. DOM: '+dom.get('status','not_run')+'. Real-client acceptance remains pending.',flush=True)
    return 0 if report['release_status']=='backend_and_dom_verified_real_client_acceptance_pending' else 1

if __name__=='__main__':raise SystemExit(main())
