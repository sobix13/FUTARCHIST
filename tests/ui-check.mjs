// Optional real-browser check. Runtime bot does not need Node or Playwright.
// Uses a fresh temporary DEMO database only. It never connects to Telegram.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import assert from 'node:assert/strict';
const temp=await fs.mkdtemp(path.join(os.tmpdir(),'futarchist-ui-test-'));
const base='http://127.0.0.1:8791';const screenshots=path.resolve('reports/screenshots');
await fs.mkdir(screenshots,{recursive:true});
const server=spawn(process.env.PYTHON||'python3',['-m','futarchist','--demo','--port','8791','--database',path.join(temp,'demo.sqlite3')],{stdio:['ignore','pipe','pipe']});
let browser;const report={type:'real-browser-local-demo',started_at:new Date().toISOString(),checks:[],errors:[],live_telegram:'not_run'};
let serverErrors='';server.stderr.on('data',d=>serverErrors+=d.toString());
async function ready(){for(let n=0;n<100;n++){if(server.exitCode!==null)throw new Error(serverErrors);try{const r=await fetch(base+'/api/config');const c=await r.json();if(c.demo)return;}catch{}await new Promise(r=>setTimeout(r,100));}throw new Error('Demo server did not become ready');}
const record=name=>report.checks.push({name,status:'passed'});
try{
 await ready();browser=await chromium.launch({headless:true});const context=await browser.newContext({viewport:{width:1280,height:900}});const page=await context.newPage();
 page.on('pageerror',e=>report.errors.push(e.message));await page.goto(base);await page.getByRole('button',{name:'Log in as superadmin'}).click();await page.getByRole('heading',{name:'Overview',exact:true}).waitFor();record('Superadmin login and overview');
 await page.getByLabel('Select workspace').selectOption({label:'Programs and Raise Review · Team'});await page.getByRole('button',{name:'Lumen Games',exact:true}).waitFor();
 await page.screenshot({path:path.join(screenshots,'desktop-overview.png'),fullPage:true});record('Workspace isolation and seeded team case');
 await page.getByRole('button',{name:'Cases',exact:true}).click();await page.getByText('More filters',{exact:true}).click();await page.locator('[name=stage]').selectOption('beta');await page.locator('[name=category][value=gaming]').check();await page.getByRole('button',{name:'Apply filters',exact:true}).click();await page.getByRole('button',{name:'Lumen Games',exact:true}).waitFor();record('Combined category and stage filters');
 await page.getByRole('button',{name:'Lumen Games',exact:true}).click();await page.getByRole('heading',{name:'Raise information',exact:true}).waitFor();
 await page.locator('#note-form [name=text]').fill('UI test internal note');await page.locator('#note-form').getByRole('button',{name:'Save',exact:true}).click();await page.getByText('UI test internal note',{exact:true}).waitFor();record('Internal note submit and escaped detail rendering');
 await page.getByRole('button',{name:'Close',exact:true}).click();
 await page.getByRole('button',{name:'Invitations',exact:true}).click();await page.locator('[name=topic]').fill('Gaming UI test');await page.locator('[name=when]').fill('Friday 18:00 UTC');await page.getByRole('button',{name:'Create preview'}).click();await page.getByRole('button',{name:/Confirm and send to 1 destinations/}).waitFor();record('Campaign preview before send');
 page.once('dialog',dialog=>dialog.accept());await page.getByRole('button',{name:/Confirm and send to 1 destinations/}).click();await page.getByText('Confirmed',{exact:true}).waitFor();record('Explicit campaign confirmation');
 await page.getByRole('button',{name:'Close',exact:true}).click();
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Cases',exact:true}).click();await page.getByRole('button',{name:'Lumen Games',exact:true}).waitFor();
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+2),'Mobile page overflows viewport');await page.screenshot({path:path.join(screenshots,'mobile-inbox.png'),fullPage:true});record('390px responsive inbox, no global horizontal overflow');
 const chat=await context.newPage();await chat.setViewportSize({width:390,height:844});await chat.goto(base+'/emulator');
 async function send(text){await chat.getByLabel('Message text').fill(text);await chat.getByRole('button',{name:'Send',exact:true}).click();}
 async function press(name){await chat.getByRole('button',{name,exact:true}).last().click();}
 await send('/start');await press('Submit information');await press('Agree and continue');await press('General information');await send('UI native intake');await press('Gaming');await press('Done selecting');await press('Skip for now');await press('Beta');await press('Testnet');await press('Skip for now');await press('Skip for now');await press('Submit');await press('No');await chat.getByText(/Done/).waitFor();record('Native Telegram-shaped intake complete in mobile chat');
 await chat.screenshot({path:path.join(screenshots,'mobile-chat.png'),fullPage:true});
 assert.equal(report.errors.length,0,report.errors.join('\n'));report.status='passed';
}catch(error){report.status='failed';report.errors.push(String(error));process.exitCode=1;}
finally{
 if(browser)await browser.close();server.kill('SIGTERM');await new Promise(resolve=>{server.once('exit',resolve);setTimeout(resolve,3000);});
 // This directory was created by this test and contains only synthetic data.
 await fs.rm(temp,{recursive:true,force:true});report.finished_at=new Date().toISOString();await fs.mkdir('reports',{recursive:true});await fs.writeFile('reports/ui-report.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
}
