import time
from urllib.request import Request, urlopen
from extensions.health_probe import probe
from ownership.core import AppError, PERMISSIONS
from ownership.exports import Exports
from ownership.management import Management
from ownership.health import Health
from tests.helpers import Fixture
from tests.test_http import HTTPFixture

class OperationalTests(Fixture):
    def test_project_archive_read_is_owner_only(self):
        pid=self.create();m=Management(self.s);op=m.prepare(1,'archive_project',{'id':pid,'version':1});m.confirm(1,op['token'])
        with self.assertRaises(AppError):self.s.projects(2,self.team,{'archived':'only'})
        self.assertEqual(len(self.s.projects(1,self.team,{'archived':'only'})),1)

    def test_task_edit_without_assignment_change_does_not_need_assign(self):
        m=Management(self.s);task=m.save_task(2,self.team,{'title':'Shared work','assignee':2});self.s.membership(1,self.team,3,['read_general','write_general']);m.save_task(3,self.team,{'status':'doing','version':1},task['id']);self.assertEqual(self.s.one('SELECT status FROM tasks WHERE id=?',(task['id'],))['status'],'doing')

    def test_taking_an_existing_task_requires_assignment_permission(self):
        m=Management(self.s);task=m.save_task(2,self.team,{'title':'Assigned','assignee':2});self.s.membership(1,self.team,3,['read_general','write_general'])
        with self.assertRaises(AppError):m.save_task(3,self.team,{'assignee':3,'version':1},task['id'])

    def test_raise_status_can_advance_before_amounts_are_known(self):
        pid=self.create(raise_status='not_started');m=Management(self.s);m.edit_project(1,pid,1,{'raise_status':'planning'},'raise');self.assertEqual(self.s.project(1,pid)['fundraising']['currency'],'unknown');m.edit_project(1,pid,2,{'raise_status':'partial'},'raise');self.assertEqual(self.s.project(1,pid)['fundraising']['retry'],'undecided')

    def test_native_custom_currency_code_has_current_value(self):
        pid=self.create();Management(self.s).edit_project(1,pid,1,{'currency':'OTHER','currency_code':'GBP'},'raise');self.bot.native.open(1,self.team);self.bot.native.handle(1,'pf:'+str(pid)+':raise:currency_code');self.assertEqual(self.bot.native.flow(1)['form']['fields'][0]['default'],'GBP')

    def test_second_plain_code_opens_another_authorized_workspace(self):
        self.s.gated=True;self.s.activate(101,self.route['token']);personal=self.s.one("SELECT id FROM spaces WHERE creator=2 AND kind='personal'")['id'];r=self.s.default_route(2,personal);self.update('/start',101);self.update(r['token'],101);self.assertEqual(self.flow(101)['route'],r['token']);self.assertEqual(len(self.s.guest_routes(101)),2)

    def test_native_write_selection_adds_required_read_permissions(self):
        n=self.bot.native;n.open(1,self.team);n.handle(1,'membership');n.consume(1,3);f=n.flow(1);n.callback(1,'a:'+f['nonce']+':multi:3',{});f=n.flow(1);n.callback(1,'a:'+f['nonce']+':done',{});self.assertEqual(set(self.s.permissions(3,self.team)),{'read_general','read_raise','write_raise'})

    def test_probe_requires_all_expected_live_workers(self):
        self.assertFalse(probe(self.path,clock=lambda:self.now)['live'])
        for component in ('poller','inbox','outbox','maintenance'):Health(self.s).beat(component)
        result=probe(self.path,clock=lambda:self.now);self.assertTrue(result['live']);self.assertFalse(result['connectivity_degraded'])
        self.now+=181;self.assertFalse(probe(self.path,clock=lambda:self.now)['live'])

    def test_probe_reports_degraded_connectivity_without_restart_loop(self):
        for component in ('poller','inbox','outbox','maintenance'):Health(self.s).beat(component,'degraded' if component=='poller' else 'ok')
        result=probe(self.path,clock=lambda:self.now);self.assertTrue(result['live']);self.assertTrue(result['connectivity_degraded'])

    def test_probe_is_read_only(self):
        count=self.s.one('SELECT COUNT(*) n FROM activity')['n'];probe(self.path,'web',clock=lambda:self.now);self.assertEqual(self.s.one('SELECT COUNT(*) n FROM activity')['n'],count)

    def test_activity_export_includes_rows_beyond_dashboard_limit(self):
        for n in range(520):self.s.audit(2,'sample',self.team)
        self.assertEqual(len(self.svc.audit(2,self.team)),500)
        body,_,_=Exports(self.s,self.svc).build(2,self.team,'activity','csv');self.assertEqual(body.count(b'sample'),520)

    def test_team_admin_cannot_disable_another_admins_route(self):
        other=self.s.route(1,self.team,'Owner code','general',1)
        with self.assertRaises(AppError):self.svc.route_status(2,other['id'],False)
        self.svc.route_status(1,other['id'],False)

    def test_financial_grant_control_requires_financial_read(self):
        self.s.activate(101,self.route['token']);self.s.membership(1,self.team,3,['read_general','routes']);m=Management(self.s)
        for op in (lambda:m.grants(3,self.route['id']),lambda:m.rotate_route(3,self.route['id']),lambda:m.revoke_grant(3,self.route['id'],101)):
            with self.assertRaises(AppError):op()

    def test_native_saved_filter_roundtrip_and_deletion(self):
        self.bot.native.open(1,self.team);f=self.bot.native.flow(1);f['filters']={'categories':['gaming'],'network':'testnet'};self.bot.native.save(1,f);self.bot.native.handle(1,'saveview');self.bot.native.consume(1,'Saved');view=self.svc.views(1,self.team)[0];self.bot.native.handle(1,'clearfilters');self.bot.native.handle(1,'useview:'+str(view['id']));self.assertEqual(self.bot.native.flow(1)['filters'],view['filters']);self.bot.native.handle(1,'delview:'+str(view['id']));self.assertEqual(self.svc.views(1,self.team),[])

    def test_native_history_preserves_inactive_author(self):
        pid=self.create();tid=self.s.note(2,pid,'general','Historical note');self.s.deactivate(1,2,False);self.bot.native.open(1,self.team);self.bot.native.handle(1,'thread:'+str(tid));self.engine.drain();self.assertIn('Historical note',self.api.chat(1)[-1]['text']);self.assertIn('Nima / 2',self.api.chat(1)[-1]['text'])

    def test_native_finance_menu_follows_current_raise_status(self):
        pid=self.create(raise_status='not_started');self.bot.native.open(1,self.team);self.bot.native.handle(1,'pedit:'+str(pid)+':raise');self.engine.drain();buttons=str(self.api.chat(1)[-1]['reply_markup']);self.assertIn('raise_status',buttons);self.assertIn('metadao',buttons);self.assertNotIn('raised_amount',buttons)

    def test_restore_uses_latest_event_version(self):
        m=Management(self.s);e=m.save_event(1,self.team,{'title':'E','starts_at':'2026-10-10 18:00'});a=m.prepare(1,'archive_event',{'id':e['id'],'version':1});m.confirm(1,a['token']);bad=m.prepare(1,'restore_event',{'id':e['id'],'version':1})
        with self.assertRaises(AppError):m.confirm(1,bad['token'])
        good=m.prepare(1,'restore_event',{'id':e['id'],'version':2});m.confirm(1,good['token']);self.assertEqual(len(m.events(1,self.team)),1)

    def test_native_large_number_returns_validation_error(self):
        self.bot.native.open(1,self.team);self.bot.native.handle(1,'newadmin')
        with self.assertRaises(AppError):self.bot.native.consume(1,'9'*100)
        self.assertEqual(self.bot.native.flow(1)['form']['index'],0)

class OperationsHTTPTests(HTTPFixture):
    def test_archived_events_tasks_owner_only_http(self):
        m=Management(self.s);e=m.save_event(1,self.team,{'title':'E','starts_at':'2026-10-10 18:00'});t=m.save_task(1,self.team,{'title':'T'})
        for kind,row in [('event',e),('task',t)]:c=m.prepare(1,'archive_'+kind,{'id':row['id'],'version':1});m.confirm(1,c['token'])
        self.login(2);self.assertEqual(self.request('/api/events?space='+str(self.team)+'&archived=only')[0],403);self.login(1);self.assertEqual(len(self.request('/api/events?space='+str(self.team)+'&archived=only')[1]),1);self.assertEqual(len(self.request('/api/tasks?space='+str(self.team)+'&archived=only')[1]),1)

    def test_workspace_recovery_and_rename_http(self):
        self.login(1);self.s.db.execute('UPDATE spaces SET active=0');self.assertEqual(self.request('/api/spaces')[0],200);code,op,_=self.request('/api/prepare',{'action':'enable_space','data':{'id':self.team,'active':0}});self.assertEqual(code,200);self.assertEqual(self.request('/api/confirm',{'token':op['token']})[0],200);self.assertEqual(self.request('/api/spaces/'+str(self.team)+'/rename',{'name':'Recovered team'})[0],200);self.assertEqual(self.s.spaces(1)[0]['name'],'Recovered team')

    def test_demo_native_document_is_downloadable_without_serializing_bytes(self):
        self.http.demo=True;self.login(1);self.create();self.bot.native.open(1,self.team);self.bot.native.handle(1,'file:projects:xlsx');self.engine.drain();code,chat,_=self.request('/demo/chat?chat=1');self.assertEqual(code,200);doc=next(m for m in chat if m.get('document_url'))
        req=Request(self.base+doc['document_url'],headers={'Cookie':self.cookie,'Origin':self.base})
        with urlopen(req) as response:self.assertTrue(response.read().startswith(b'PK'));self.assertIn('.xlsx',response.headers['Content-Disposition'])
