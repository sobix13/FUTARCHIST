from ownership.__main__ import configure_bot
from ownership.guide import visible_sections
from tests.helpers import Fixture
from tests.test_http import HTTPFixture


class GuideTests(Fixture):
    def buttons(self, uid=101):
        return [b for row in self.api.chat(uid)[-1].get('reply_markup', {}).get('inline_keyboard', []) for b in row]

    def test_guest_home_has_discoverable_guide(self):
        self.bot.app_url='';self.update('/start')
        self.assertIn('guide', [b.get('callback_data') for b in self.buttons()])
        self.callback('guide');self.assertIn('Getting started', str(self.buttons()))

    def test_admin_start_prioritizes_dashboard_without_guest_code_prompt(self):
        self.update('/start',1)
        self.assertIn('Your admin access is active',self.api.chat(1)[-1]['text'])
        self.assertNotIn('Enter the access code',self.api.chat(1)[-1]['text'])
        labels=[b['text'] for b in self.buttons(1)]
        self.assertLess(labels.index('Open dashboard'),labels.index('Manage in Telegram'))

    def test_admin_start_explains_unconfigured_dashboard(self):
        self.bot.app_url='';self.update('/start',1)
        self.assertIn('not connected yet',self.api.chat(1)[-1]['text'])
        self.assertIn('Dashboard setup',[b['text'] for b in self.buttons(1)])
        self.callback('guide:browser',1);self.assertIn('configured HTTPS address',self.api.chat(1)[-1]['text'])

    def test_native_dashboard_action_uses_current_workspace_and_login_flow(self):
        self.update('/manage',1)
        button=next(b for b in self.buttons(1) if b['text']=='Open dashboard')
        self.callback(button['callback_data'],1)
        self.assertIn('Personal login link',self.api.chat(1)[-1]['text'])
        self.assertEqual(self.s.one('SELECT COUNT(*) n FROM login_links')['n'],1)

    def test_help_opens_guide_and_preserves_custom_help(self):
        self.s.db.execute("INSERT INTO text_settings(key,value,version,updated_at) VALUES('help','Our English help',1,?)", (self.now,))
        self.update('/help')
        self.assertIn('Our English help', [m['text'] for m in self.api.chat(101)])
        self.assertIn('FUTARCHIST Guide', self.api.chat(101)[-1]['text'])

    def test_guest_cannot_open_admin_or_owner_topics(self):
        self.create(name='Private review project')
        for section in ('cases','admins','health'):
            with self.subTest(section=section):
                self.callback('guide:'+section)
                self.assertIn('unavailable', self.api.chat(101)[-1]['text'])
                self.assertNotIn('Private review project', self.api.chat(101)[-1]['text'])

    def test_regular_admin_cannot_open_superadmin_topics(self):
        self.update('/guide', 2)
        options=str(self.buttons(2));self.assertIn('Cases and reviews',options);self.assertNotIn('Bot text',options)
        self.callback('guide:admins',2);self.assertIn('unavailable',self.api.chat(2)[-1]['text'])

    def test_superadmin_gets_complete_role_guide(self):
        self.update('/guide',1)
        self.assertIn('Health and recovery',str(self.buttons(1)))
        self.assertIn('Admins and permissions',str(self.buttons(1)))
        for key, title, text in visible_sections('owner'):
            with self.subTest(section=key):
                self.callback('guide:'+key,1)
                self.assertIn(title,self.api.chat(1)[-1]['text'])
                self.assertLessEqual(len(self.api.chat(1)[-1]['text']),3800)

    def test_guest_draft_and_current_buttons_survive_guide(self):
        self.update('/start intake_'+self.route['token']);self.action('consent');self.action('purpose:general')
        self.update('Saved draft');before=self.flow()
        self.update('/guide');self.callback('guide:forms');self.callback('guide')
        self.assertEqual(self.flow(),before)
        self.action('answer:gaming');self.assertEqual(self.flow()['answers']['categories'],['gaming'])

    def test_admin_form_can_resume_after_guide(self):
        self.update('/manage',1)
        nonce=self.bot.native.flow(1)['nonce'];self.callback('a:'+nonce+':newadmin',1)
        self.update('20',1);before=self.bot.native.flow(1)
        self.callback('guide',1);self.callback('guide:admins',1)
        self.assertEqual(self.bot.native.flow(1),before)
        self.assertIn('Resume admin step',str(self.buttons(1)))
        self.callback('guide:resume_admin',1);self.update('New colleague',1)
        self.assertEqual(self.s.actor(20)['role'],'admin')
        self.assertEqual(self.s.actor(20)['name'],'New colleague')

    def test_help_does_not_abandon_admin_form(self):
        self.update('/manage',1)
        nonce=self.bot.native.flow(1)['nonce'];self.callback('a:'+nonce+':newteam',1)
        before=self.bot.native.flow(1);self.update('/help',1)
        self.assertEqual(self.bot.native.flow(1),before)
        self.update('Guide test team',1)
        self.assertIsNotNone(self.s.one("SELECT id FROM spaces WHERE name='Guide test team'"))

    def test_guide_is_available_without_active_workspace(self):
        self.s.db.execute('UPDATE spaces SET active=0');self.update('/manage',1)
        self.assertIn('Guide',str(self.buttons(1)));self.callback('guide',1)
        self.assertIn('Health and recovery',str(self.buttons(1)))

    def test_group_guide_only_links_to_private_chat(self):
        self.update('/guide@OwnershipDemoBot',101,-1007,True)
        self.assertIn('private chat',self.api.chat(-1007)[-1]['text'])
        self.assertEqual(self.api.chat(101),[])

    def test_other_bot_group_guide_is_ignored(self):
        u=self.update('/guide@AnotherBot',101,-1007,True)
        self.assertEqual(self.api.chat(-1007),[])
        self.assertIsNone(self.s.one('SELECT update_id FROM inbox WHERE update_id=?',(u['update_id'],)))

    def test_unknown_section_does_not_fail_queue(self):
        self.callback('guide:not-a-topic');self.update('/id')
        self.assertIn('101',self.api.chat(101)[-1]['text'])
        self.assertEqual(self.s.rows('SELECT * FROM incidents'),[])

    def test_guest_cannot_resume_admin_step(self):
        self.callback('guide:resume_admin')
        self.assertIn('approved admins',self.api.chat(101)[-1]['text'])
        self.assertIsNone(self.s.one('SELECT user_id FROM native_flows WHERE user_id=101'))

    def test_guide_does_not_mutate_cases_codes_or_assignments(self):
        self.create();before={table:self.s.rows('SELECT * FROM '+table) for table in ('projects','cases','routes','members')}
        self.update('/guide',1);self.callback('guide:cases',1);self.callback('guide:codes',1)
        after={table:self.s.rows('SELECT * FROM '+table) for table in before}
        self.assertEqual(before,after)

    def test_command_setup_registers_help_and_guide_for_all_scopes(self):
        class Client:
            def __init__(self):self.commands=[]
            def call(self,method,payload):
                if method=='setMyCommands':self.commands.append(payload)
                return True
        client=Client();configure_bot(client,(1,2))
        self.assertEqual(len(client.commands),3)
        for payload in client.commands:
            self.assertIn('guide',[c['command'] for c in payload['commands']])
            self.assertIn('help',[c['command'] for c in payload['commands']])


class GuideHTTPTests(HTTPFixture):
    def test_guidance_styles_do_not_expose_app_data(self):
        status,body,headers=self.request('/guidance.css',authorized=False,raw=True)
        self.assertEqual(status,200);self.assertIn('.page-help',body)
        self.assertEqual(self.request('/api/projects?space='+str(self.team),authorized=False)[0],401)
