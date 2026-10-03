import io
import json
import sqlite3
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
from ownership.core import Store, AppError, PERMISSIONS
from ownership.management import Management, parse_time
from ownership.exports import Exports, xlsx_bytes, csv_bytes, column_name
from ownership.health import Health
from ownership.simulator import FakeAPIServer, message_update
from ownership.telegram import TelegramClient, TelegramError, Engine
from ownership.service import Service, DEFAULT_TEMPLATE
from tests.helpers import Fixture
from tests.test_http import HTTPFixture

class GatedTests(Fixture):
    def setUp(self):
        super().setUp();self.s.gated=True
    def test_unknown_start_does_not_offer_submission(self):
        self.update('/start',103);self.assertIsNone(self.flow(103));self.assertNotIn('Submit information',str(self.api.chat(103)[-1]['reply_markup']))
    def test_known_public_code_never_unlocks(self):
        self.update('/start intake_public',103);self.assertIsNone(self.flow(103));self.assertEqual(self.s.one('SELECT COUNT(*) n FROM access_grants')['n'],0)
    def test_code_activates_only_its_workspace(self):
        self.update('/activate '+self.route['token']);self.assertEqual(self.flow()['route'],self.route['token']);self.assertEqual(self.s.guest_routes(101)[0]['space_id'],self.team)
    def test_plain_code_works_after_start(self):
        self.update('/start',103);self.update(self.route['token'],103);self.assertEqual(self.flow(103)['phase'],'consent')
    def test_repeat_activation_does_not_spend_capacity(self):
        self.s.db.execute('UPDATE routes SET max_uses=1 WHERE id=?',(self.route['id'],))
        with self.s.tx():self.s.activate(101,self.route['token']);self.s.activate(101,self.route['token'])
        self.assertEqual(self.s.one('SELECT uses FROM routes WHERE id=?',(self.route['id'],))['uses'],1)
        with self.assertRaises(AppError):self.s.activate(102,self.route['token'])
    def test_bound_code_rejects_other_user(self):
        self.s.db.execute('UPDATE routes SET bound_user=102 WHERE id=?',(self.route['id'],))
        with self.assertRaises(AppError):self.s.activate(101,self.route['token'])
        self.s.activate(102,self.route['token'])
    def test_expiry_and_revocation_close_entry(self):
        self.s.activate(101,self.route['token']);Management(self.s).revoke_grant(2,self.route['id'],101)
        with self.assertRaises(AppError):self.s.activate(101,self.route['token'])
        self.assertEqual(self.s.guest_routes(101),[])
        Management(self.s).revoke_grant(2,self.route['id'],101,True);self.s.activate(101,self.route['token'])
        self.s.db.execute('UPDATE routes SET expires=? WHERE id=?',(self.now-1,self.route['id']))
        with self.assertRaises(AppError):self.s.active_route(self.route['token'])
    def test_rotating_code_preserves_existing_source(self):
        pid=self.create();source=self.s.project(2,pid)['cases'][0]['source_admin'];new=Management(self.s).rotate_route(2,self.route['id'])
        self.assertNotEqual(new['token'],self.route['token']);self.assertEqual(new['creator'],2)
        with self.assertRaises(AppError):self.s.active_route(self.route['token'])
        self.assertEqual(self.s.project(2,pid)['cases'][0]['source_admin'],source)
    def test_guest_cannot_use_native_management(self):
        self.update('/manage');self.assertIn('approved admins',self.api.chat(101)[-1]['text'])
    def test_callback_new_does_not_bypass_code(self):
        self.callback('new',103);self.assertIsNone(self.flow(103))

class SuperadminTests(unittest.TestCase):
    def test_two_configured_superadmins_are_equal(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(Path(d)/'x.sqlite3',313342234,super_admin_ids=(313342234,5691137098))
            try:
                with s.tx():
                    s.owner(313342234);s.owner(5691137098);sid=s.team(5691137098,'Team');s.add_admin(313342234,20,'A');s.membership(5691137098,sid,20,list(PERMISSIONS))
                    s.check(313342234,sid,'export');s.check(5691137098,sid,'export')
                    with self.assertRaises(AppError):s.add_admin(313342234,5691137098,'No')
                    with self.assertRaises(AppError):s.deactivate(5691137098,313342234,False)
                self.assertEqual(len(s.rows("SELECT * FROM users WHERE role='owner'")),2)
            finally:s.close()
    def test_restart_preserves_admin_and_gate(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'x.sqlite3';s=Store(path,10,super_admin_ids=(10,11));s.add_admin(10,20,'A');route=s.rows('SELECT * FROM routes WHERE creator=20')[0];s.register(101,'G');s.activate(101,route['token']);s.close()
            s=Store(path,10,super_admin_ids=(10,11))
            try:self.assertEqual(s.guest_routes(101)[0]['creator'],20);self.assertEqual(s.actor(11)['role'],'owner')
            finally:s.close()
    def test_migration_from_v1_is_backed_up_and_preserves_records(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'v1.sqlite3';old=sqlite3.connect(path)
            old.executescript((Path(__file__).parent/'fixtures'/'schema-v1.sql').read_text())
            old.execute("INSERT INTO users(id,name,role) VALUES(1,'Old','owner')");old.commit();old.close()
            s=Store(path,1,super_admin_ids=(1,4))
            try:
                self.assertEqual(s.one('PRAGMA user_version')['user_version'],2);self.assertEqual(s.actor(1)['name'],'Old');self.assertEqual(len(list(Path(d).glob('*.before-v2-*.sqlite3'))),1)
            finally:s.close()

class ManagementTests(Fixture):
    def setUp(self):super().setUp();self.m=Management(self.s,self.svc)
    def test_edit_general_keeps_finance_and_source(self):
        pid=self.create();before=self.s.project(2,pid);self.m.edit_project(2,pid,1,{'name':'New','motivation':'Better'},'general');after=self.s.project(2,pid)
        self.assertEqual(after['fundraising'],before['fundraising']);self.assertEqual(after['cases'],before['cases']);self.assertEqual(after['general']['name'],'New')
    def test_edit_finance_requires_scope(self):
        pid=self.create()
        with self.assertRaises(AppError):self.m.edit_project(3,pid,1,{'raised_amount':'100'},'raise')
        self.m.edit_project(2,pid,1,{'raised_amount':'100'},'raise');self.assertEqual(self.s.project(2,pid)['fundraising']['raised_amount'],'100')
    def test_edit_race_rejected(self):
        pid=self.create();self.m.edit_project(2,pid,1,{'name':'First'})
        with self.assertRaises(AppError):self.m.edit_project(2,pid,1,{'name':'Second'})
    def test_invalid_fields_and_cross_workspace_rejected(self):
        pid=self.create()
        for patch in ({'submitter':2},{'source_admin':1},{'name':'x','raised_amount':'1'}):
            with self.assertRaises(AppError):self.m.edit_project(2,pid,1,patch)
        with self.assertRaises(AppError):self.m.edit_project(3,pid,1,{'name':'x'})
    def test_finance_condition_cleanup_and_custom_currency(self):
        pid=self.create();self.m.edit_project(2,pid,1,{'currency':'OTHER','currency_code':'GBP'},'raise');self.assertEqual(self.s.project(2,pid)['fundraising']['currency'],'GBP')
        self.m.edit_project(2,pid,2,{'raise_status':'not_started'},'raise');self.assertNotIn('raised_amount',self.s.project(2,pid)['fundraising'])
    def test_edit_note_owns_or_superadmin_and_version(self):
        pid=self.create();tid=self.s.note(2,pid,'general','First');self.m.edit_note(1,tid,1,'Second')
        with self.assertRaises(AppError):self.m.edit_note(2,tid,1,'Third')
        self.assertEqual(self.s.one('SELECT text FROM threads WHERE id=?',(tid,))['text'],'Second')
    def test_guest_message_cannot_be_rewritten(self):
        pid=self.create();tid=self.s.note(2,pid,'general','Original',True)
        with self.assertRaises(AppError):self.m.edit_note(1,tid,1,'Fake reply')
    def test_text_owner_only_and_optimistic_version(self):
        with self.assertRaises(AppError):self.m.set_text(2,'welcome','New',0)
        self.m.set_text(1,'welcome','New',0);self.assertEqual(self.m.text('welcome'),'New')
        with self.assertRaises(AppError):self.m.set_text(1,'welcome','Other',0)
    def test_text_template_rejects_code_paths(self):
        with self.assertRaises(AppError):self.m.set_text(1,'invite_template','{project.__class__}',0)
        with self.assertRaises(AppError):self.m.set_text(1,'secret','Value',0)
    def test_custom_question_appears_in_bot(self):
        self.m.set_text(1,'question:name','What is your team called?',0);self.update('/start intake_'+self.route['token']);self.action('consent');self.action('purpose:general');self.assertIn('What is your team called?',self.api.chat(101)[-1]['text'])
    def test_archive_restore_and_purge_confirm_once(self):
        pid=self.create();op=self.m.prepare(1,'archive_project',{'id':pid,'version':1});self.m.confirm(1,op['token'])
        self.assertEqual(self.s.projects(2,self.team),[])
        with self.assertRaises(AppError):self.m.confirm(1,op['token'])
        restore=self.m.prepare(1,'restore_project',{'id':pid,'version':2});self.m.confirm(1,restore['token']);self.assertEqual(len(self.s.projects(2,self.team)),1)
        arch=self.m.prepare(1,'archive_project',{'id':pid,'version':3});self.m.confirm(1,arch['token']);purge=self.m.prepare(1,'purge_project',{'id':pid,'version':4});self.m.confirm(1,purge['token'])
        self.assertIsNone(self.s.one('SELECT * FROM projects WHERE id=?',(pid,)));self.assertEqual(self.s.rows('PRAGMA foreign_key_check'),[])
    def test_purge_requires_archive_and_current_version(self):
        pid=self.create();op=self.m.prepare(1,'purge_project',{'id':pid,'version':1})
        with self.assertRaises(AppError):self.m.confirm(1,op['token'])
        op=self.m.prepare(1,'archive_project',{'id':pid,'version':1});self.m.edit_project(2,pid,1,{'name':'Later'})
        with self.assertRaises(AppError):self.m.confirm(1,op['token'])
    def test_operation_token_cannot_be_used_by_other_account(self):
        pid=self.create();op=self.m.prepare(1,'archive_project',{'id':pid,'version':1})
        with self.assertRaises(AppError):self.m.confirm(2,op['token'])
    def test_archive_cancels_pending_invite_and_disables_group(self):
        pid=self.create();self.optin();c=self.svc.campaign(2,self.team,'Gaming','UTC',DEFAULT_TEMPLATE,{});self.svc.confirm(2,c['id'])
        op=self.m.prepare(1,'archive_project',{'id':pid,'version':1});self.m.confirm(1,op['token']);self.assertEqual(self.s.one('SELECT state FROM outbox WHERE dedupe LIKE \'campaign:%\'')['state'],'cancelled')
    def test_event_link_and_history_are_workspace_bound(self):
        pid=self.create();e=self.m.save_event(2,self.team,{'title':'Weekly','kind':'radio','starts_at':'2026-10-10 18:00','timezone':'Asia/Tehran'})
        self.m.link_event(2,e['id'],pid,'attended');self.assertEqual(self.m.event(2,e['id'])['projects'][0]['participation'],'attended')
        other=self.create(route={'token':'public'},name='Private')
        with self.assertRaises(AppError):self.m.link_event(1,e['id'],other,'invited')
    def test_raise_events_hidden_and_cannot_be_demoted_without_permission(self):
        e=self.m.save_event(2,self.team,{'title':'Private raise','kind':'raise','starts_at':'2026-10-10 18:00'})
        self.assertEqual(self.m.events(3,self.team),[])
        with self.assertRaises(AppError):self.m.event(3,e['id'])
        with self.assertRaises(AppError):self.m.save_event(3,self.team,{'kind':'meeting','version':1},e['id'])
    def test_event_versions_and_bad_time(self):
        e=self.m.save_event(2,self.team,{'title':'One','starts_at':'2026-10-10 18:00'});self.m.save_event(2,self.team,{'title':'Two','version':1},e['id'])
        with self.assertRaises(AppError):self.m.save_event(2,self.team,{'title':'Three','version':1},e['id'])
        for value in ('wrong','2026-15-10'):
            with self.assertRaises(AppError):parse_time(value)
        with self.assertRaises(AppError):parse_time('2026-10-10 18:00','Unknown/Zone')
    def test_task_scope_finance_and_assignment(self):
        pid=self.create();t=self.m.save_task(2,self.team,{'title':'Check','purpose':'raise','project_id':pid})
        self.assertEqual(self.m.tasks(3,self.team),[])
        with self.assertRaises(AppError):self.m.save_task(2,self.team,{'title':'Invalid assignment','purpose':'raise','assignee':3})
        with self.assertRaises(AppError):self.m.save_task(3,self.team,{'status':'done','version':1},t['id'])
    def test_task_version_and_event_compatibility(self):
        e=self.m.save_event(2,self.team,{'title':'Raise','kind':'raise','starts_at':'2026-10-10 18:00'})
        with self.assertRaises(AppError):self.m.save_task(2,self.team,{'title':'Leak','purpose':'general','event_id':e['id']})
        t=self.m.save_task(2,self.team,{'title':'Work'});self.m.save_task(2,self.team,{'status':'done','version':1},t['id'])
        with self.assertRaises(AppError):self.m.save_task(2,self.team,{'status':'open','version':1},t['id'])

class ExportTests(Fixture):
    def setUp(self):super().setUp();self.ex=Exports(self.s,self.svc)
    def test_xlsx_sheets_filter_and_literal_values(self):
        self.create(name='=SUM(1,2)');self.create(102,name='Other',categories=['defi'])
        body,name,mime=self.ex.build(2,self.team,'all','xlsx',{'categories':['gaming']})
        self.assertTrue(name.endswith('.xlsx'))
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            self.assertIsNone(z.testzip());workbook=ET.fromstring(z.read('xl/workbook.xml'));self.assertIn('raise',str(z.read('xl/workbook.xml')))
            for n in z.namelist():
                if n.endswith('.xml'):ET.fromstring(z.read(n))
            sheet=z.read('xl/worksheets/sheet1.xml');self.assertIn(b'=SUM(1,2)',sheet);self.assertNotIn(b'<f>',sheet);self.assertNotIn(b'Other',sheet)
    def test_csv_injection_unicode_and_zero(self):
        self.create(name='@hidden',raised_amount='0');body,_,_=self.ex.build(2,self.team,'projects','csv');self.assertTrue(body.startswith(b'\xef\xbb\xbf'));self.assertIn(b"'@hidden",body)
        body,_,_=self.ex.build(2,self.team,'raise','csv');self.assertIn(b',0,',body)
    def test_general_export_does_not_leak_finance(self):
        self.create();self.s.membership(1,self.team,3,['read_general','export'])
        body,_,_=self.ex.build(3,self.team,'all','xlsx')
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            text=b''.join(z.read(n) for n in z.namelist());self.assertNotIn(b'500000',text);self.assertNotIn(b'unsuccessful',text);self.assertNotIn(b'target_amount',text)
        with self.assertRaises(AppError):self.ex.build(3,self.team,'raise','csv')
    def test_every_dataset_and_csv_bundle(self):
        self.create()
        for d in ('projects','cases','raise','notes','events','tasks','campaigns','activity','routes','groups'):
            body,name,mime=self.ex.build(2,self.team,d,'csv');self.assertTrue(name.endswith('.csv'));self.assertGreater(len(body),5)
        body,name,_=self.ex.build(2,self.team,'all','csv')
        with zipfile.ZipFile(io.BytesIO(body)) as z:self.assertEqual(len(z.namelist()),10)
    def test_native_export_uses_real_multipart_http(self):
        self.create();api=FakeAPIServer(self.api);thread=threading.Thread(target=api.serve_forever,daemon=True);thread.start()
        try:
            engine=Engine(self.s,self.bot,TelegramClient('TEST',f'http://127.0.0.1:{api.server_port}',True),False)
            self.s.queue('sendDocument',{'chat_id':2,'_export':{'uid':2,'sid':self.team,'dataset':'all','format':'xlsx','filters':{}}},sid=self.team,actor=2,permission='export')
            self.assertTrue(engine.dispatch_one());self.assertEqual(self.s.one('SELECT state FROM outbox ORDER BY id DESC LIMIT 1')['state'],'sent');call=self.api.calls[-1];self.assertEqual(call['method'],'sendDocument');self.assertTrue(call['payload']['_file']['data'].startswith(b'PK'))
        finally:api.shutdown();api.server_close();thread.join(2)
    def test_export_rechecks_revoked_permission(self):
        self.create();self.s.queue('sendDocument',{'chat_id':2,'_export':{'uid':2,'sid':self.team,'dataset':'all','format':'xlsx'}},sid=self.team,actor=2,permission='export');self.s.membership(1,self.team,2,['read_general']);self.engine.dispatch_one();self.assertEqual(len(self.api.messages),0)
    def test_column_letters_and_xml_controls(self):
        self.assertEqual(column_name(27),'AA');body=xlsx_bytes({'data':(['A'],[['x\x00y']])})
        with zipfile.ZipFile(io.BytesIO(body)) as z:self.assertNotIn(b'\x00',z.read('xl/worksheets/sheet1.xml'))

class HealthTests(Fixture):
    def test_safe_repair_removes_expired_not_business_data(self):
        pid=self.create();token=self.s.login(2);self.now+=13*3600;r=Health(self.s).repair(1);self.assertEqual(r['expired'],1);self.assertEqual(self.s.project(2,pid)['id'],pid)
    def test_uncertain_sends_are_not_autorepaired(self):
        self.s.queue('sendMessage',{'chat_id':101,'text':'X'});self.api.failures=['timeout'];self.engine.dispatch_one();Health(self.s).repair(1);self.assertEqual(self.s.one('SELECT state FROM outbox')['state'],'uncertain')
    def test_poison_update_does_not_block_next_update(self):
        update=message_update(1,101,'bad');next_update=message_update(2,102,'/id');self.engine.ingest([update,next_update]);original=self.bot.process
        def process(u,verified=False):
            if u['update_id']==1:raise RuntimeError('Synthetic failure')
            return original(u,verified)
        with patch.object(self.bot,'process',process):self.assertFalse(self.engine.process_one());self.assertTrue(self.engine.process_one())
        self.assertEqual(self.s.one('SELECT done FROM inbox WHERE update_id=2')['done'],1)
    def test_fault_incident_is_deduped_and_health_requires_owner(self):
        h=Health(self.s);first=h.incident('web','X','Fixed description');second=h.incident('web','X','Fixed description');self.assertEqual(first,second);self.assertEqual(h.snapshot(1)['incidents'][0]['count'],2)
        with self.assertRaises(AppError):h.snapshot(2)
    def test_backup_inside_request_transaction_does_not_deadlock(self):
        self.create()
        with self.s.tx():r=Health(self.s).backup(1)
        self.assertTrue(r['verified']);self.assertTrue((self.path.parent/'backups'/r['name']).is_file())
    def test_transient_only_autorepair(self):
        for i,error in [(1,'Group verification temporarily unavailable'),(2,'Internal processing error')]:self.s.db.execute('INSERT INTO inbox(update_id,payload,attempts,error,received_at) VALUES(?,\'{}\',5,?,?)',(i,error,self.now))
        self.assertEqual(Health(self.s).repair(1)['recovered_updates'],1);self.assertEqual(self.s.one('SELECT attempts FROM inbox WHERE update_id=2')['attempts'],5)

class NewHTTPTests(HTTPFixture):
    def test_events_tasks_and_edits_http(self):
        pid=self.create();self.login(2);code,e,_=self.request('/api/events',{'space_id':self.team,'title':'Test','starts_at':'2026-10-10 18:00'});self.assertEqual(code,200)
        self.assertEqual(self.request('/api/events/'+str(e['id'])+'/projects',{'project_id':pid,'participation':'confirmed'})[0],200)
        self.assertEqual(self.request('/api/tasks',{'space_id':self.team,'title':'Check','project_id':pid})[0],200)
        self.assertEqual(self.request('/api/projects/'+str(pid)+'/edit',{'version':1,'changes':{'name':'HTTP edit'}})[0],200)
    def test_health_and_texts_require_superadmin(self):
        self.login(2);self.assertEqual(self.request('/api/operations')[0],403);self.assertEqual(self.request('/api/texts')[0],403);self.assertEqual(self.request('/api/repair',{})[0],403)
        self.login(1);self.assertEqual(self.request('/api/operations')[0],200);self.assertEqual(self.request('/api/texts',{'key':'welcome','value':'Hello','version':0})[0],200)
    def test_ready_and_assets_whitelist(self):
        self.assertEqual(self.request('/ready')[0],200)
        from urllib.request import urlopen
        with urlopen(self.base+'/assets/futardio.png') as r:self.assertEqual(r.headers['Content-Type'],'image/png');self.assertTrue(r.read().startswith(b'\x89PNG'))
        self.assertEqual(self.request('/assets/../core.py')[0],404)
    def test_owner_archive_http_confirm_and_restore(self):
        pid=self.create();self.login(1);code,p,_=self.request('/api/prepare',{'action':'archive_project','data':{'id':pid,'version':1}});self.assertEqual(code,200);self.assertEqual(self.request('/api/confirm',{'token':p['token']})[0],200);self.assertEqual(self.request('/api/confirm',{'token':p['token']})[0],409)
        self.assertEqual(self.request('/api/projects/'+str(pid))[0],200)
