// DOM integration tests for our scripts. This is not a visual browser test.
import {spawn} from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import assert from 'node:assert/strict';
const {JSDOM,VirtualConsole}=await import(process.env.FUTARCHIST_JSDOM_MODULE||'jsdom');
const temporary=await fs.mkdtemp(path.join(os.tmpdir(),'futarchist-dom-'));
const base='http://127.0.0.1:8792';
const server=spawn(process.env.PYTHON||'python3',['-m','futarchist','--demo','--port','8792','--database',path.join(temporary,'demo.sqlite3')],{stdio:['ignore','pipe','pipe']});
let serverLog='',dom,simulator;server.stderr.on('data',v=>serverLog+=v.toString());
const report={type:'DOM integration, not browser rendering',started_at:new Date().toISOString(),checks:[],errors:[]};
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(fn,label){for(let i=0;i<150;i++){if(fn())return;await pause(20);}throw new Error(label);}
const record=name=>report.checks.push({name,status:'passed'});
try{
 for(let n=0;n<100;n++){if(server.exitCode!==null)throw new Error(serverLog);try{if((await fetch(base+'/api/config')).ok)break;}catch{}await pause(50);}
 const source=await (await fetch(base)).text(),app=await fs.readFile('ownership/static/app.js','utf8'),ops=await fs.readFile('ownership/static/operations.js','utf8');
 const html=source.replace(/<script[^>]*src=[^>]*><\/script>/g,'').replace('</body>',`<script>${ops}</script><script>${app}</script></body>`);
 const console=new VirtualConsole();console.on('jsdomError',e=>report.errors.push(e.message));
 let cookie='',exports=[];
 dom=new JSDOM(html,{url:base,runScripts:'dangerously',virtualConsole:console,beforeParse(w){
  w.AbortController=globalThis.AbortController;
  w.fetch=async(input,options={})=>{const headers={...options.headers,...(cookie?{Cookie:cookie}:{}),Origin:base};const response=await fetch(new URL(input,base),{...options,headers});const set=response.headers.get('set-cookie');if(set)cookie=set.split(';')[0];return response;};
  w.confirm=()=>true;w.prompt=()=> 'DOM saved view';
  w.HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
  w.HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');};
  w.URL.createObjectURL=blob=>{exports.push({blob});return 'blob:test';};w.URL.revokeObjectURL=()=>{};
  w.HTMLAnchorElement.prototype.click=function(){if(exports.length)exports.at(-1).name=this.download;};
 }});
 const w=dom.window,d=w.document,$=s=>d.querySelector(s);
 assert.equal(d.documentElement.lang,'en');assert.equal(d.documentElement.dir,'ltr');record('English-only interface and left-to-right document');
 const click=async selector=>{await until(()=>$(selector)&&!$(selector).disabled,'Control absent or busy: '+selector);$(selector).click();await pause(80);};
 const submit=async selector=>{$(selector).dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await pause(80);};
 const set=(selector,value)=>{assert.ok($(selector),'Missing input '+selector);$(selector).value=value;};
 const nav=async page=>{await click(`#nav [data-page="${page}"]`);await until(()=>!$('#view').textContent.includes('Loading'),page);};
 await until(()=>!$('#demo-login').hidden,'Demo login absent');await click('[data-login="1"]');await until(()=>!$('#shell').hidden&&$('#nav').children.length,'Login failed');record('Superadmin login and navigation');
 const team=[...$('#workspace').options].find(o=>o.textContent.includes('Programs and Raise Review'));
 assert.ok(team);set('#workspace',team.value);$('#workspace').dispatchEvent(new w.Event('change'));await until(()=>$('#view').textContent.includes('Lumen Games'),'Team case absent');record('Workspace selector and isolation');
 const fastFetch=w.fetch;let delayed=false;w.fetch=async(input,opts)=>{const url=new URL(input,base);if(!delayed&&url.pathname==='/api/projects'&&url.searchParams.get('space')===team.value){delayed=true;await pause(250);}return fastFetch(input,opts);};
 await click('#nav [data-page="inbox"]');const personal=[...$('#workspace').options].find(o=>o.textContent.includes('Sobix'))||$('#workspace').options[0];set('#workspace',personal.value);$('#workspace').dispatchEvent(new w.Event('change'));await until(()=>$('#view').textContent.includes('Signal Markets'),'Personal case absent');await pause(300);assert.equal($('#view').textContent.includes('Lumen Games'),false);w.fetch=fastFetch;set('#workspace',team.value);$('#workspace').dispatchEvent(new w.Event('change'));await until(()=>$('#view').textContent.includes('Lumen Games'),'Team did not recover');record('Late response cannot overwrite the newly selected workspace');
 await nav('overview');assert.equal(d.querySelectorAll('.workflow-grid .card').length,4);assert.equal(d.querySelectorAll('#nav .nav-group').length,4);record('Overview maps the four work steps and groups navigation');
 for(const page of ['inbox','events','tasks','exports','texts','raise','campaigns','routes','team','audit','deliveries','operations']){await nav(page);assert.ok($('#view').children.length,page);assert.equal($('#toast').classList.contains('error')&&!$('#toast').hidden,false,$('#toast').textContent);assert.ok($('#page-help summary').textContent.startsWith('How to use '),page);assert.ok($('#page-help ol li').textContent,page);assert.ok($('#page-help a').getAttribute('href').startsWith('/guide#'),page);record('Render and section guide '+page);}
 await nav('inbox');await click('[data-project]');await until(()=>$('#detail').open&&$('#note-form'),'Project detail absent');const projectId=$('[data-edit-project]').dataset.editProject;
 set('#note-form [name=text]','DOM internal note <script>literal</script>');await submit('#note-form');await until(()=>$('#detail-content').textContent.includes('DOM internal note'),'Note was not saved');assert.equal($('#detail-content script'),null);record('Internal note and HTML escaping');
 await click('[data-edit-project]');set('#project-edit-form [name=name]','DOM Lumen');await submit('#project-edit-form');await until(()=>$('#detail-content').textContent.includes('DOM Lumen'),'Edit absent');record('Project editing via shared permission service');
 await click('[data-edit-project][data-purpose="raise"]');await until(()=>$('#project-edit-form [name=raise_status]'),'Raise form absent');set('#project-edit-form [name=raise_status]','not_started');$('#project-edit-form [name=raise_status]').dispatchEvent(new w.Event('change'));assert.ok($('#project-edit-form [name=raised_amount]').disabled);await submit('#project-edit-form');await until(()=>$('#detail-content').querySelector('[data-prepare="archive_project"]'),'Raise edit absent');record('Conditional raise edit clears inapplicable fields');
 await click('[data-action="close-detail"]');await nav('events');await click('[data-new-event]');await until(()=>$('#event-form'),'Event form absent');
 set('#event-form [name=title]','DOM program');set('#event-form [name=starts_at]','2026-10-20T18:00');await submit('#event-form');await until(()=>$('#detail-content').textContent.includes('Projects and participation'),'Event not saved');record('Program create and detail');const eventId=$('[data-prepare="archive_event"]').dataset.target;
 await click('[data-prepare="archive_event"]');await click('[data-confirm-operation]');await nav('events');await click('[data-show-archived-events]');await click(`[data-event="${eventId}"]`);await click('[data-prepare="restore_event"]');await click('[data-confirm-operation]');await click('[data-show-archived-events]');record('Program archive and restore confirmation');
 await click('[data-action="close-detail"]');await nav('tasks');await click('[data-new-task]');await until(()=>$('#task-form'),'Task form absent');set('#task-form [name=title]','DOM follow-up');await submit('#task-form');await until(()=>$('#view').textContent.includes('DOM follow-up'),'Task absent');record('Task create and assignee');
 await nav('exports');await submit('#export-form');await until(()=>exports.length,'Download absent');assert.ok(exports.at(-1).name.endsWith('.xlsx'));assert.ok((await exports.at(-1).blob.arrayBuffer()).byteLength>1000);record('Authenticated XLSX download');
 await nav('inbox');await click(`[data-project="${projectId}"]`);await click('[data-prepare="archive_project"]');await click('[data-confirm-operation]');await click('[data-archived]');await click(`[data-project="${projectId}"]`);await until(()=>$('#detail-content').textContent.includes('Source:'),'Archived source tag absent');assert.equal($('#note-form'),null);await click('[data-prepare="restore_project"]');await click('[data-confirm-operation]');await click('[data-archived]');record('Project archive preserves source tags and disables editing');
 await nav('routes');await click('[data-route-grants]');await until(()=>$('[data-grant-user]'),'Activated guests absent');await click('[data-grant-user]');await until(()=>$('[data-grant-active="1"]'),'Guest was not revoked');await click('[data-grant-user]');await until(()=>$('[data-grant-active="0"]'),'Guest was not reactivated');record('Individual code access revoke and reactivate');await click('[data-action="close-detail"]');
 await nav('texts');set('[data-key="welcome"] [name=value]','FUTARCHIST DOM welcome');await submit('[data-key="welcome"]');await until(()=>$('[data-key="welcome"]').dataset.version==='1','Text version absent');record('Superadmin bot-text edit');
 await nav('operations');await click('[data-health-repair]');await until(()=>$('#toast').textContent.includes('Safe recovery'),'Repair did not complete');record('Health and safe repair UI');
 const onlineFetch=w.fetch;w.fetch=async()=>{throw new Error('Synthetic offline');};await click('[data-action="refresh"]');await until(()=>!$('#connection').hidden,'Connection fallback absent');w.fetch=onlineFetch;await click('#connection [data-action="refresh"]');await until(()=>$('#connection').hidden,'Connection did not recover');record('Connection failure exposes native fallback and recovery');
 await click('#logout');await until(()=>$('#shell').hidden,'Logout failed');await click('[data-login="2"]');await until(()=>!$('#shell').hidden,'Admin login failed');assert.equal($('#nav [data-page="texts"]'),null);assert.equal($('#nav [data-page="operations"]'),null);record('Admin does not receive superadmin controls');
 await click('#logout');await click('[data-login="4"]');await until(()=>$('#nav [data-page="texts"]'),'Second superadmin controls absent');record('Second superadmin has full controls');
 const simulatorHtml=await (await fetch(base+'/emulator')).text(),simulatorCode=await fs.readFile('ownership/static/emulator.js','utf8');
 simulator=new JSDOM(simulatorHtml.replace(/<script[^>]*src=[^>]*><\/script>/g,'').replace('</body>',`<script>${simulatorCode}</script></body>`),{url:base+'/emulator',runScripts:'dangerously',virtualConsole:console,beforeParse(v){v.fetch=w.fetch;v.open=()=>{};}});
 const sd=simulator.window.document;
 assert.equal(sd.documentElement.lang,'en');assert.equal(sd.documentElement.dir,'ltr');
 await until(()=>sd.querySelector('#start')&&!sd.querySelector('#start').disabled,'Simulator did not initialise');
 sd.querySelector('#start').click();await until(()=>sd.querySelector('#chat').textContent.includes('FUTARCHIST DOM welcome'),'Simulator Start failed');
 assert.equal(/[\u0600-\u06ff]/.test(sd.querySelector('#chat').textContent),false);record('English Telegram simulator boots and Start opens the guest home');
 sd.querySelector('#actor').value='1';sd.querySelector('#actor').dispatchEvent(new simulator.window.Event('change'));
 sd.querySelector('#message').value='/manage';sd.querySelector('#composer').dispatchEvent(new simulator.window.Event('submit',{bubbles:true,cancelable:true}));
 await until(()=>[...sd.querySelectorAll('#chat button')].some(b=>b.textContent==='Cases'),'Simulator native management failed');record('Telegram simulator opens native admin controls');
 const guideButton=[...sd.querySelectorAll('#chat button')].find(b=>b.textContent==='Guide');assert.ok(guideButton,'Native Guide is missing');guideButton.click();await until(()=>sd.querySelector('#chat').textContent.includes('Choose a section.'),'Native guide failed');record('Telegram guide opens without a web login link');
 const caseGuide=[...sd.querySelectorAll('#chat button')].find(b=>b.textContent==='Cases and reviews');assert.ok(caseGuide,'Case guide is missing');caseGuide.click();await until(()=>sd.querySelector('#chat').textContent.includes('General and Raise are separate review branches'),'Native case guide failed');record('Native case guide explains source, assignee, status and next actions');
 assert.deepEqual(report.errors,[]);report.status='passed';
}catch(error){report.status='failed';report.errors.push(error.stack||String(error));report.last_toast=dom?.window.document.querySelector('#toast')?.textContent;process.exitCode=1;}
finally{
 if(simulator)simulator.window.close();if(dom)dom.window.close();server.kill('SIGTERM');await Promise.race([new Promise(r=>server.once('exit',r)),pause(3000)]);await fs.rm(temporary,{recursive:true,force:true});
 report.finished_at=new Date().toISOString();await fs.mkdir('reports',{recursive:true});await fs.writeFile('reports/dom-report.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}
