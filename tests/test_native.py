import json
from unittest.mock import patch
from ownership.core import AppError, PERMISSIONS
from ownership.management import Management
from ownership.exports import Exports
from ownership.health import Health
from tests.helpers import Fixture

class NativeTests(Fixture):
    def setUp(self):
        super().setUp();self.native=self.bot.native
        with self.s.tx():self.native.open(1,self.team)
        self.engine.drain()

    def press(self,action,uid=1):
        nonce=self.native.flow(uid)['nonce'];self.callback('a:'+nonce+':'+action,uid)

    def screen(self,uid=1):return self.api.chat(uid)[-1]

    def options(self,uid=1):return [b for row in self.screen(uid).get('reply_markup',{}).get('inline_keyboard',[]) for b in row]

    def test_owner_home_has_native_sections_and_no_browser_dependency(self):
        self.bot.app_url='';self.update('/manage',1)
        text=str(self.screen());self.assertIn('Manage workspaces',text);self.assertIn('Export Excel / CSV',text);self.assertNotIn('Browser login link',text)

    def test_owner_add_admin_creates_private_code(self):
        self.press('newadmin');self.assertIn('Numeric Telegram ID',self.screen()['text']);self.update('20',1);self.assertIn('Admin display name',self.screen()['text']);self.update('New admin',1)
        self.assertEqual(self.s.actor(20)['role'],'admin');route=self.s.one('SELECT * FROM routes WHERE creator=20');self.assertNotEqual(route['token'],'public');self.assertIn(route['token'],str(self.api.chat(1)))

    def test_native_team_and_membership_creation(self):
        self.press('newteam');self.update('Agency',1);space=self.s.one("SELECT id FROM spaces WHERE name='Agency'")['id'];self.press('space:'+str(space));self.press('membership');self.update('2',1)
        self.press('multi:0');self.press('multi:1');self.press('done');self.assertIn('write_general',self.s.permissions(2,space))

    def test_empty_membership_removes_only_current_space(self):
        self.press('membership');self.update('3',1);self.press('done');self.assertIsNone(self.s.one('SELECT 1 FROM members WHERE user_id=3 AND space_id=?',(self.team,)));self.assertEqual(len(self.s.spaces(3)),1)

    def test_stale_button_does_not_edit(self):
        nonce=self.native.flow(1)['nonce'];self.press('admins');self.callback('a:'+nonce+':newadmin',1);self.assertIn('old',self.screen()['text']);self.assertNotIn('form',self.native.flow(1))

    def test_guest_cannot_reuse_admin_button(self):
        nonce=self.native.flow(1)['nonce'];self.callback('a:'+nonce+':health',101);self.assertNotIn('FUTARCHIST',self.screen(101)['text']);self.assertIn('approved admins',self.screen(101)['text'])

    def test_admin_cannot_forge_owner_operations(self):
        self.update('/manage',2);self.press('texts',2);self.assertIn('superadmin access',self.screen(2)['text']);self.assertEqual(self.s.rows('SELECT * FROM text_settings'),[])

    def test_native_project_edit_keeps_case_source(self):
        pid=self.create();source=self.s.project(2,pid)['cases'];self.press('pf:'+str(pid)+':general:name');self.update('Native rename',1)
        self.assertEqual(self.s.project(2,pid)['general']['name'],'Native rename');self.assertEqual(self.s.project(2,pid)['cases'],source)

    def test_optional_project_field_can_be_cleared(self):
        pid=self.create();self.press('pf:'+str(pid)+':general:website');self.press('clear');self.assertIsNone(self.s.project(2,pid)['general']['website'])

    def test_custom_currency_is_two_step_and_existing_custom_is_kept(self):
        pid=self.create();self.press('pf:'+str(pid)+':raise:currency');self.press('val:5');self.update('GBP',1);self.assertEqual(self.s.project(2,pid)['fundraising']['currency'],'GBP')
        self.press('pf:'+str(pid)+':raise:currency');self.press('skip');self.press('skip');self.assertEqual(self.s.project(2,pid)['fundraising']['currency'],'GBP')

    def test_standard_currency_skips_custom_currency_question(self):
        pid=self.create();self.press('pf:'+str(pid)+':raise:currency');self.press('val:0');self.assertNotIn('form',self.native.flow(1));self.assertEqual(self.s.project(2,pid)['fundraising']['currency'],'USD')

    def test_code_limit_and_clear_capacity(self):
        self.press('rconfig:'+str(self.route['id']));self.press('skip');self.update('2',1);self.press('skip');self.press('skip');self.assertEqual(self.s.one('SELECT max_uses FROM routes WHERE id=?',(self.route['id'],))['max_uses'],2)
        self.press('rconfig:'+str(self.route['id']));self.press('skip');self.press('clear');self.press('skip');self.press('skip');self.assertIsNone(self.s.one('SELECT max_uses FROM routes WHERE id=?',(self.route['id'],))['max_uses'])

    def test_individual_code_access_can_be_closed_and_opened(self):
        self.s.activate(101,self.route['token']);self.press('grants:'+str(self.route['id']));self.press('grant_toggle:'+str(self.route['id'])+':101');self.assertEqual(self.s.guest_routes(101),[])
        self.press('grant_toggle:'+str(self.route['id'])+':101');self.assertEqual(len(self.s.guest_routes(101)),1)

    def test_code_rotation_is_available_in_native_panel(self):
        old=self.route['token'];self.press('rrotate:'+str(self.route['id']));self.assertIn('Access code',self.screen()['text']);self.assertFalse(self.s.one('SELECT active FROM routes WHERE token=?',(old,))['active'])

    def test_native_filter_combines_criteria(self):
        pid=self.create();self.press('filter:categories');self.press('multi:0');self.press('done');self.press('filter:network');self.press('val:2');self.press('projects');self.assertIn('Lumen Games',str(self.screen()))
        self.assertEqual(self.native.flow(1)['filters'],{'categories':['gaming'],'network':'testnet'})

    def test_malformed_option_returns_friendly_error_and_keeps_form(self):
        self.press('membership');self.update('2',1);self.press('multi:999');self.assertIn('Invalid option',self.screen()['text']);self.assertIn('form',self.native.flow(1));self.assertEqual(self.s.rows('SELECT * FROM incidents'),[])

    def test_start_clears_admin_form_before_guest_intake(self):
        self.press('newadmin');self.update('/start',1);self.assertNotIn('form',self.native.flow(1));self.update('123',1);self.assertIsNone(self.s.one('SELECT * FROM users WHERE id=123'))

    def test_program_create_and_edit_flow(self):
        self.press('newevent');self.update('Native radio',1);self.press('val:0');self.press('skip');self.press('skip');self.update('2026-10-10 18:00',1);self.press('skip')
        event=self.s.one("SELECT * FROM events WHERE title='Native radio'");self.assertEqual(event['kind'],'radio');self.press('eedit:'+str(event['id']));self.press('skip');self.press('val:2');self.press('skip');self.press('skip');self.press('skip');self.update('Completed session',1)
        event=self.s.one('SELECT * FROM events WHERE id=?',(event['id'],));self.assertEqual(event['status'],'completed');self.assertEqual(event['outcome'],'Completed session')

    def test_native_task_create_view_and_edit(self):
        self.press('newtask');self.update('Native task',1);self.press('val:0');self.press('skip');self.press('skip');self.press('skip');self.press('skip');self.press('skip')
        task=self.s.one("SELECT * FROM tasks WHERE title='Native task'");self.assertEqual(task['assignee'],1);self.press('task:'+str(task['id']));self.assertIn('Edit task',str(self.screen()));self.press('tedit:'+str(task['id']));self.press('skip');self.press('val:2');self.press('skip');self.press('skip');self.assertEqual(self.s.one('SELECT status FROM tasks WHERE id=?',(task['id'],))['status'],'done')

    def test_archive_restore_events_and_tasks(self):
        m=Management(self.s);event=m.save_event(1,self.team,{'title':'Archive','starts_at':'2026-10-10 18:00'});task=m.save_task(1,self.team,{'title':'Archive'})
        for kind,row in [('event',event),('task',task)]:
            self.press('prepare:archive_'+kind+':'+str(row['id']));self.callback(self.options()[0]['callback_data'],1);self.press('archived_'+('events' if kind=='event' else 'tasks'));self.press(kind+':'+str(row['id']));self.assertIn('Restore',str(self.screen()));self.press('prepare:restore_'+kind+':'+str(row['id']));self.callback(self.options()[0]['callback_data'],1);table='events' if kind=='event' else 'tasks';self.assertIsNone(self.s.one('SELECT archived_at FROM '+table+' WHERE id=?',(row['id'],))['archived_at'])

    def test_native_archive_restore_and_purge_project(self):
        pid=self.create();self.press('prepare:archive_project:'+str(pid));self.callback(self.options()[0]['callback_data'],1);self.press('archived');self.press('project:'+str(pid));self.assertIn('Permanently delete data',str(self.screen()));self.press('prepare:purge_project:'+str(pid));self.callback(self.options()[0]['callback_data'],1);self.assertIsNone(self.s.one('SELECT * FROM projects WHERE id=?',(pid,)))

    def test_health_retry_and_incident_ack(self):
        self.s.db.execute("INSERT INTO inbox(update_id,payload,attempts,error,received_at,next_at) VALUES(999,'{}',5,'Internal processing error',?,?)",(self.now,self.now+1000));iid=Health(self.s).incident('test','X','Synthetic fault');self.press('health');self.assertIn('update 999',self.screen()['text']);self.press('ack:'+str(iid));self.assertEqual(self.s.one('SELECT state FROM incidents WHERE id=?',(iid,))['state'],'acknowledged');self.press('retry');self.update('999',1);self.assertEqual(self.s.one('SELECT next_at FROM inbox WHERE update_id=999')['next_at'],0)

    def test_export_is_native_and_uses_actor_destination(self):
        self.create();self.press('file:projects:xlsx');calls=[c for c in self.api.calls if c['method']=='sendDocument'];self.assertEqual(len(calls),1);self.assertEqual(calls[0]['payload']['chat_id'],1);self.assertTrue(calls[0]['payload']['_file']['data'].startswith(b'PK'))

    def test_export_build_failure_does_not_block_next_message(self):
        self.s.queue('sendDocument',{'chat_id':1,'_export':{'uid':1,'sid':self.team,'dataset':'projects','format':'xlsx'}},sid=self.team,actor=1,permission='export');self.s.queue('sendMessage',{'chat_id':102,'text':'Next'})
        with patch.object(Exports,'build',side_effect=RuntimeError('Synthetic fault')):self.assertTrue(self.engine.dispatch_one())
        self.assertTrue(self.engine.dispatch_one());self.assertEqual(self.api.chat(102)[-1]['text'],'Next');self.assertEqual(self.s.one("SELECT count(*) n FROM incidents WHERE component='export'")['n'],1)

    def test_project_pagination_reaches_older_records(self):
        for i in range(25):self.create(name='Project '+str(i))
        self.press('projects');self.assertIn('Next page',str(self.screen()));self.press('page:projects:20');self.assertIn('Project 0',str(self.screen()))

    def test_workspace_can_be_disabled_and_reenabled_natively(self):
        self.press('workspace:'+str(self.team));self.press('prepare:disable_space:'+str(self.team));self.callback(self.options()[0]['callback_data'],1);self.assertFalse(self.s.one('SELECT active FROM spaces WHERE id=?',(self.team,))['active']);self.press('workspaces');self.press('workspace:'+str(self.team));self.press('prepare:enable_space:'+str(self.team));self.callback(self.options()[0]['callback_data'],1);self.assertTrue(self.s.one('SELECT active FROM spaces WHERE id=?',(self.team,))['active'])

    def test_owner_can_recover_when_all_workspaces_are_disabled(self):
        self.s.db.execute('UPDATE spaces SET active=0');self.update('/manage',1);self.assertIn('Manage workspaces',str(self.screen()));self.press('workspaces');self.press('workspace:'+str(self.team));self.press('prepare:enable_space:'+str(self.team));self.callback(self.options()[0]['callback_data'],1);self.assertEqual(len(self.s.spaces(1)),1)

    def test_financial_audit_is_hidden_after_financial_export(self):
        self.create();Exports(self.s,self.svc).build(2,self.team,'all','xlsx');audit=self.svc.audit(3,self.team);self.assertNotIn('export_created',[r['action'] for r in audit])

class MidFormGateTests(Fixture):
    def setUp(self):super().setUp();self.s.gated=True
    def test_revoked_grant_blocks_final_submission(self):
        self.update('/start intake_'+self.route['token']);self.action('consent');self.action('purpose:general');self.update('Gate test');self.action('answer:gaming');self.action('done');self.action('skip');self.action('answer:building');self.action('answer:na');self.action('skip');self.action('skip');Management(self.s).revoke_grant(2,self.route['id'],101);self.action('submit');self.assertEqual(self.s.rows('SELECT * FROM projects'),[]);self.assertIn('access to this route is inactive',self.api.chat(101)[-1]['text'])

    def test_no_direct_store_save_without_activation(self):
        from ownership.forms import split_answers
        g,f=split_answers('general',{'name':'Unauthorized','categories':['gaming'],'stage':'idea','network':'na'},'G')
        with self.assertRaises(AppError):self.s.save_project(101,self.route['token'],g,f,'general')
