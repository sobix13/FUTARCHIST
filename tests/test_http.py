import concurrent.futures
import hashlib
import hmac
import json
import threading
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from ownership.server import AppServer
from ownership.service import DEFAULT_TEMPLATE
from ownership.simulator import FakeAPIServer
from ownership.telegram import TelegramClient
from tests.helpers import Fixture

class HTTPFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.http=AppServer(('127.0.0.1',0),self.s,self.svc,self.engine,'http://127.0.0.1','123:test',False)
        self.base=f'http://127.0.0.1:{self.http.server_port}';self.http.origin=self.base
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start();self.cookie='';self.csrf=''

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join(2);super().tearDown()

    def request(self,path,data=None,method='POST',headers=None,authorized=True,raw=False):
        hs={'Origin':self.base}
        if authorized:hs.update({'Cookie':self.cookie,'X-CSRF-Token':self.csrf})
        hs.update(headers or {})
        if data is not None:
            hs.setdefault('Content-Type','application/json');body=data if isinstance(data,bytes) else json.dumps(data).encode()
        else:body=None
        req=Request(self.base+path,data=body,headers=hs,method=method if data is not None else 'GET')
        try: response=urlopen(req,timeout=5)
        except HTTPError as e:response=e
        with response:
            value=response.read();value=value.decode() if raw else json.loads(value)
            return response.status,value,dict(response.headers)

    def login(self,uid=2):
        with self.s.tx():token=self.s.login_link(uid)
        code,data,headers=self.request('/api/auth/link',{'token':token},authorized=False)
        self.assertEqual(code,200);self.cookie=headers['Set-Cookie'].split(';')[0];self.csrf=data['csrf'];return token

class HTTPTests(HTTPFixture):
    def test_api_requires_session(self):self.assertEqual(self.request('/api/me')[0],401)
    def test_live_demo_login_disabled(self):self.assertEqual(self.request('/api/auth/demo',{'user_id':1})[0],404)
    def test_live_simulator_routes_disabled(self):
        self.login();self.assertEqual(self.request('/demo/chat')[0],404);self.assertEqual(self.request('/emulator',raw=True)[0],404)
    def test_link_login_http_only_cookie_and_single_use(self):
        token=self.login();code,data,headers=self.request('/api/auth/link',{'token':token});self.assertEqual(code,401)
        self.assertEqual(self.request('/api/me')[1]['user']['id'],2)
    def test_telegram_login_hmac_not_user_claim(self):
        raw={'auth_date':str(self.now),'user':json.dumps({'id':2,'first_name':'Nima'})};key=hmac.new(b'WebAppData',b'123:test',hashlib.sha256).digest()
        raw['hash']=hmac.new(key,'\n'.join(f'{k}={v}' for k,v in sorted(raw.items())).encode(),hashlib.sha256).hexdigest()
        code,d,headers=self.request('/api/auth/telegram',{'init_data':urlencode(raw)},authorized=False);self.assertEqual(code,200);self.assertIn('HttpOnly',headers['Set-Cookie'])
        raw['user']=json.dumps({'id':1,'first_name':'Owner'});self.assertEqual(self.request('/api/auth/telegram',{'init_data':urlencode(raw)},authorized=False)[0],401)
    def mini_app_session(self):
        raw={'auth_date':str(self.now),'user':json.dumps({'id':2,'first_name':'Nima'})};key=hmac.new(b'WebAppData',b'123:test',hashlib.sha256).digest()
        raw['hash']=hmac.new(key,'\n'.join(f'{k}={v}' for k,v in sorted(raw.items())).encode(),hashlib.sha256).hexdigest()
        code,data,_=self.request('/api/auth/telegram',{'init_data':urlencode(raw)},authorized=False);self.assertEqual(code,200)
        return {'Authorization':'Bearer '+data['session_token'],'X-CSRF-Token':data['csrf']}
    def test_mini_app_without_cookie_reads_writes_and_exports(self):
        self.create();headers=self.mini_app_session()
        self.assertEqual(self.request('/api/me',headers=headers,authorized=False)[1]['user']['id'],2)
        self.assertEqual(self.request('/api/routes',{'space_id':self.team,'name':'Cookie-free','purpose':'general','assignee':2},headers=headers,authorized=False)[0],200)
        self.assertEqual(self.request('/api/export?space='+str(self.team),headers=headers,authorized=False,raw=True)[0],200)
    def test_mini_app_session_revocation_and_csrf(self):
        headers=self.mini_app_session();bad={**headers,'X-CSRF-Token':'wrong'}
        self.assertEqual(self.request('/api/routes',{},headers=bad,authorized=False)[0],403)
        self.s.deactivate(1,2,False)
        self.assertEqual(self.request('/api/me',headers=headers,authorized=False)[0],401)
    def test_csrf_missing_denies_mutation(self):
        self.login();self.csrf='';self.assertEqual(self.request('/api/routes',{'space_id':self.team,'name':'New','purpose':'general','assignee':2})[0],403)
    def test_cross_origin_denies_mutation(self):
        self.login();self.assertEqual(self.request('/api/routes',{},headers={'Origin':'https://attacker.example'})[0],403)
    def test_forged_role_in_body_cannot_add_admin(self):
        self.login();self.assertEqual(self.request('/api/admins',{'user_id':20,'name':'Fake','role':'owner'})[0],403)
    def test_guest_cannot_login(self):
        self.assertEqual(self.request('/api/auth/telegram',{'init_data':'user={"id":101,"role":"owner"}'})[0],401)
    def test_financial_http_data_redacted_for_viewer(self):
        pid=self.create();self.login(3);code,p,_=self.request('/api/projects/'+str(pid));self.assertEqual(code,200);self.assertIsNone(p['fundraising'])
        self.assertEqual([c['purpose'] for c in p['cases']],['general'])
    def test_cross_space_http_project_access_denied(self):
        pid=self.create(route={'token':'public'});self.login(2);self.assertEqual(self.request('/api/projects/'+str(pid))[0],403)
    def test_financial_filter_api_denied(self):
        self.login(3);path='/api/projects?'+urlencode({'space':self.team,'filters':json.dumps({'min_target':'1','currency':'USD'})});self.assertEqual(self.request(path)[0],403)
    def test_revoked_session_http(self):
        self.login();self.s.deactivate(1,2,False);self.assertEqual(self.request('/api/me')[0],401)
    def test_logout_revokes_session(self):
        self.login();self.assertEqual(self.request('/api/logout',{})[0],200);self.assertEqual(self.request('/api/me')[0],401)
    def test_json_type_and_size_limits(self):
        self.login();self.assertEqual(self.request('/api/routes',b'[]')[0],400)
        self.assertEqual(self.request('/api/routes',b'not json')[0],400)
        self.assertEqual(self.request('/api/routes',b'{}',headers={'Content-Type':'text/plain'})[0],415)
        self.assertEqual(self.request('/api/routes',b'x'*65537)[0],413)
    def test_static_resources_security_headers(self):
        for path in ('/','/app.js','/style.css','/guide'):
            with self.subTest(path=path):
                code,body,headers=self.request(path,raw=True);self.assertEqual(code,200);self.assertIn('Content-Security-Policy',headers);self.assertEqual(headers['Referrer-Policy'],'no-referrer')
    def test_route_create_assign_status_and_export_through_http(self):
        self.login();code,r,_=self.request('/api/routes',{'space_id':self.team,'name':'HTTP intake','purpose':'both','assignee':2});self.assertEqual(code,200)
        pid=self.create(route=r);p=self.request('/api/projects/'+str(pid))[1];c=p['cases'][0]
        self.assertEqual(self.request('/api/cases/'+str(c['id']),{'version':c['version'],'status':'followup','assignee':3})[0],200)
        code,csv,headers=self.request('/api/export?space='+str(self.team),raw=True);self.assertEqual(code,200);self.assertIn('text/csv',headers['Content-Type']);self.assertIn('Lumen Games',csv)
    def test_concurrent_changes_have_one_winner(self):
        pid=self.create();c=self.s.project(2,pid)['cases'][0];self.login()
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda status:self.request('/api/cases/'+str(c['id']),{'version':1,'status':status})[0],['reviewing','closed']))
        self.assertEqual(sorted(results),[200,409])
    def test_owner_team_and_admin_management_through_http(self):
        self.login(1);self.assertEqual(self.request('/api/admins',{'user_id':45,'name':'Extra'})[0],200)
        sid=self.request('/api/spaces',{'name':'New team'})[1]['id']
        self.assertEqual(self.request('/api/members',{'space_id':sid,'user_id':45,'permissions':['read_general']})[0],200)
        self.assertIn(45,[m['id'] for m in self.request('/api/members?space='+str(sid))[1]])
    def test_transaction_rolls_back_failed_campaign(self):
        self.login();before=self.s.one('SELECT COUNT(*) n FROM campaigns')['n']
        self.assertEqual(self.request('/api/campaigns',{'space_id':self.team,'topic':'X','when':'Y','template':'{bad}','filters':{}})[0],400)
        self.assertEqual(self.s.one('SELECT COUNT(*) n FROM campaigns')['n'],before)
    def test_unexpected_methods_do_not_expose_data(self):
        self.login();self.assertEqual(self.request('/api/me',{},method='DELETE')[0],404)

class FullWorkflowTests(HTTPFixture):
    def test_intake_to_admin_to_question_to_invite_to_reply(self):
        # Both directions use a real local HTTP API transport with Telegram-shaped JSON.
        fake=FakeAPIServer(self.api);thread=threading.Thread(target=fake.serve_forever,daemon=True);thread.start()
        original=self.engine.client;self.engine.client=TelegramClient('DEMO',f'http://127.0.0.1:{fake.server_port}',True)
        try:
            self.login(2)
            self.update('/start intake_'+self.route['token']);self.action('consent');self.action('purpose:both')
            self.update('HTTP end-to-end');self.action('answer:gaming');self.action('done');self.action('skip');self.action('answer:beta');self.action('answer:testnet');self.action('skip');self.action('skip')
            self.action('answer:unsuccessful');self.action('answer:yes');self.update('MetaDAO');self.action('answer:USDC');self.update('100000');self.update('0');self.action('answer:yes');self.action('submit');self.action('opt:yes')
            path='/api/projects?'+urlencode({'space':self.team,'filters':json.dumps({'categories':['gaming'],'raise_status':'unsuccessful','retry':'yes','metadao':'yes'})})
            code,projects,_=self.request(path);self.assertEqual(code,200);self.assertEqual(len(projects),1);p=projects[0]
            self.assertEqual(self.request('/api/notes',{'project_id':p['id'],'purpose':'raise','text':'When will you retry?','guest':True})[0],200);self.engine.drain()
            token=self.s.one('SELECT token FROM reply_tokens')['token'];self.update('/start reply_'+token);self.update('Next quarter.')
            detail=self.request('/api/projects/'+str(p['id']))[1];self.assertEqual(detail['threads'][-1]['text'],'Next quarter.')
            code,campaign,_=self.request('/api/campaigns',{'space_id':self.team,'topic':'Gaming','when':'Friday 18:00 UTC','template':DEFAULT_TEMPLATE,'filters':{'categories':['gaming']}})
            self.assertEqual(code,200);self.assertEqual(len(campaign['recipients']),1)
            self.assertEqual(self.request('/api/campaigns/'+str(campaign['id'])+'/confirm',{})[0],200);self.engine.drain()
            token=campaign['recipients'][0]['token'];self.update('/start invite_'+token);self.callback('rsvp:'+token+':yes')
            status=self.request('/api/campaigns/'+str(campaign['id']))[1];self.assertEqual(status['recipients'][0]['response'],'yes');self.assertEqual(status['recipients'][0]['delivery_state'],'sent')
            self.login(3);self.assertIsNone(self.request('/api/projects/'+str(p['id']))[1]['fundraising'])
        finally:self.engine.client=original;fake.shutdown();fake.server_close();thread.join(2)
