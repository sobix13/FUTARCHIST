import json
from ownership.core import AppError, Store
from ownership.forms import questions
from ownership.simulator import callback_update, message_update
from ownership.telegram import Engine
from tests.helpers import Fixture

class BotTests(Fixture):
    def start_form(self,purpose='general',uid=101):
        self.update('/start intake_'+self.route['token'],uid);self.action('consent',uid);self.action('purpose:'+purpose,uid)

    def complete(self,purpose='general',uid=101):
        self.start_form(purpose,uid)
        self.update('New Project',uid);self.action('answer:gaming',uid);self.action('done',uid);self.action('skip',uid)
        self.action('answer:live',uid);self.action('answer:mainnet',uid);self.update('https://example.com/live',uid);self.action('skip',uid)
        if purpose!='general':
            self.action('answer:unsuccessful',uid);self.action('answer:yes',uid);self.update('MetaDAO',uid)
            self.action('answer:USDC',uid);self.update('1,000',uid);self.update('0',uid);self.action('answer:considering',uid)

    def test_full_general_intake(self):
        self.complete();self.assertEqual(self.flow()['phase'],'review');self.action('submit');self.action('opt:no')
        self.assertIsNone(self.flow());self.assertEqual(self.s.one('SELECT COUNT(*) n FROM projects')['n'],1)
        self.assertEqual(self.s.one('SELECT COUNT(*) n FROM cases')['n'],1)
    def test_full_both_intake(self):
        self.complete('both');self.action('submit');self.action('opt:yes')
        p=self.s.projects(2,self.team)[0];self.assertEqual(p['fundraising']['target_amount'],'1000');self.assertEqual(p['fundraising']['raised_amount'],'0');self.assertEqual(len(p['cases']),2)
        self.assertTrue(self.s.actor(101)['invites'])
    def test_draft_pause_and_resume(self):
        self.start_form();self.update('Draft');self.action('pause');saved=self.flow();self.update('/resume')
        self.assertEqual(self.flow()['answers']['name'],'Draft');self.assertNotEqual(self.flow()['nonce'],saved['nonce'])
    def test_old_button_never_advances_form(self):
        self.start_form();old='f:'+self.flow()['nonce']+':skip';self.update('Draft');index=self.flow()['index'];self.callback(old)
        self.assertEqual(self.flow()['index'],index);self.assertIn('older step',self.api.chat(101)[-1]['text'])
    def test_category_toggle_remains_same_question(self):
        self.start_form();self.update('A');self.action('answer:gaming');self.action('answer:defi');self.action('answer:gaming')
        self.assertEqual(self.flow()['answers']['categories'],['defi']);self.assertEqual(self.flow()['index'],1)
    def test_required_category_cannot_skip(self):
        self.start_form();self.update('A');self.action('skip');self.assertEqual(self.flow()['index'],1)
    def test_back_preserves_existing_answers(self):
        self.start_form();self.update('A');self.action('answer:gaming');self.action('done');self.action('back')
        self.assertEqual(self.flow()['index'],1);self.assertEqual(self.flow()['answers']['name'],'A')
    def test_duplicate_update_exactly_one_transition(self):
        self.start_form();u=self.update('Once');count=len(self.api.messages);self.engine.ingest([u]);self.engine.drain()
        self.assertEqual(len(self.api.messages),count);self.assertEqual(self.flow()['index'],1)
    def test_duplicate_submit_callback_no_duplicate_project(self):
        self.complete();f=self.flow();data='f:'+f['nonce']+':submit';self.callback(data);self.callback(data)
        self.assertEqual(self.s.one('SELECT COUNT(*) n FROM projects')['n'],1)
    def test_new_link_does_not_silently_discard_draft(self):
        self.start_form();self.update('Saved');self.update('/start');self.callback('new')
        self.assertEqual(self.flow()['answers']['name'],'Saved');self.assertIn('switch_route',self.flow())
    def test_explicit_cancel_only_removes_draft(self):
        self.create();self.start_form();self.update('/cancel')
        self.assertIsNone(self.flow());self.assertEqual(self.s.one('SELECT COUNT(*) n FROM projects')['n'],1)
    def test_owner_can_edit_own_submission_not_others(self):
        pid=self.create();self.update('/start',102);self.callback('edit:'+str(pid),102)
        self.assertIsNone(self.flow(102));self.assertIn('belong',self.api.chat(102)[-1]['text'])
    def test_edit_uses_optimistic_version_and_keeps_source(self):
        pid=self.create();self.update('/projects');self.callback('edit:'+str(pid));self.assertEqual(self.flow()['pid'],pid)
        self.assertEqual(self.flow()['version'],1);self.assertEqual(self.flow()['purpose'],'both')
    def test_ordinary_group_messages_not_retained(self):
        u=self.update('Private group conversation',102,-1007,True)
        self.assertIsNone(self.s.one('SELECT update_id FROM inbox WHERE update_id=?',(u['update_id'],)))
        self.assertEqual(self.api.chat(-1007),[])
    def test_bot_command_address_suffix(self):
        self.update('/start@OwnershipDemoBot');self.assertTrue(self.api.chat(101))
        self.update('/id@OwnershipDemoBot');self.assertIn('101',self.api.chat(101)[-1]['text'])
    def test_general_and_raise_notes_privacy(self):
        pid=self.create();self.s.note(2,pid,'raise','Secret finance');self.s.note(2,pid,'general','General note')
        self.assertNotIn('Secret finance',json.dumps(self.s.history(3,pid)));self.assertIn('General note',json.dumps(self.s.history(3,pid)))
    def test_case_question_reply_bound_to_guest_one_time(self):
        pid=self.create();self.s.note(2,pid,'raise','What happened?',True)
        token=self.s.one('SELECT token FROM reply_tokens')['token'];self.update('/start reply_'+token,102)
        self.assertIsNone(self.flow(102));self.update('/start reply_'+token);self.update('We will retry.')
        self.assertEqual(self.s.one('SELECT used FROM reply_tokens')['used'],1)
        self.assertEqual(self.s.history(2,pid)['threads'][-1]['text'],'We will retry.')
        self.update('/start reply_'+token);self.assertIsNone(self.flow())
    def test_question_reply_expires(self):
        pid=self.create();self.s.note(2,pid,'general','Question',True);token=self.s.one('SELECT token FROM reply_tokens')['token'];self.now+=7*86400+1
        self.update('/start reply_'+token);self.assertIsNone(self.flow())
    def test_stop_only_opts_out_not_delete_case(self):
        self.create();self.optin();self.update('/stop');self.assertFalse(self.s.actor(101)['invites']);self.assertTrue(self.s.projects(2,self.team))
    def test_group_connection_requires_group_admin_and_app_access(self):
        pid=self.create();binding=self.svc.binding(2,pid)
        self.update(binding['command'],3,-1007,True);self.assertIsNone(self.s.one('SELECT * FROM groups'))
        self.update(binding['command'],2,-1007,True);self.assertEqual(self.s.one('SELECT project_id FROM groups')['project_id'],pid)
    def test_group_binding_is_single_use(self):
        pid=self.create();command=self.svc.binding(2,pid)['command'];self.update(command,2,-1007,True);self.update(command,2,-1007,True)
        self.assertEqual(self.s.one('SELECT COUNT(*) n FROM groups')['n'],1)
    def test_group_administrators_verified_without_moderation_grant(self):
        pid=self.create();command=self.svc.binding(2,pid)['command'];self.update(command,2,-1007,True)
        self.assertIn('getChatAdministrators',[c['method'] for c in self.api.calls])
        self.assertNotIn('getChatMember',[c['method'] for c in self.api.calls])
    def test_invalid_bind_does_not_fetch_group_admins(self):
        self.update('/bind invalid',102,-1007,True)
        self.assertNotIn('getChatAdministrators',[c['method'] for c in self.api.calls])
    def test_project_representative_can_approve_group_without_crm_admin(self):
        pid=self.create();command=self.svc.binding(2,pid)['command'];self.api.admins.add((-1007,101));self.update(command,101,-1007,True)
        self.assertEqual(self.s.one('SELECT consent_actor FROM groups')['consent_actor'],101)
        self.assertEqual(self.s.actor(101)['role'],'guest')
        with self.assertRaises(AppError):self.s.project(101,pid)
    def test_guest_group_binding_rechecks_internal_creator_authority(self):
        pid=self.create();command=self.svc.binding(2,pid)['command'];self.api.admins.add((-1007,101));self.s.membership(1,self.team,2,['read_general']);self.update(command,101,-1007,True)
        self.assertIsNone(self.s.one('SELECT * FROM groups'))
    def test_group_removal_deactivates(self):
        pid=self.create();self.update(self.svc.binding(2,pid)['command'],2,-1007,True)
        self.engine.ingest([{'update_id':500,'my_chat_member':{'chat':{'id':-1007},'new_chat_member':{'status':'kicked'}}}]);self.engine.drain()
        self.assertFalse(self.s.one('SELECT active FROM groups')['active'])
    def test_group_migration_updates_destination(self):
        pid=self.create();self.update(self.svc.binding(2,pid)['command'],2,-1007,True)
        self.engine.ingest([{'update_id':500,'message':{'chat':{'id':-1007,'type':'group'},'migrate_to_chat_id':-1008}}]);self.engine.drain()
        self.assertEqual(self.s.one('SELECT chat_id FROM groups')['chat_id'],-1008)
    def test_persisted_flow_survives_restart(self):
        self.start_form();self.update('Saved');self.s.close();self.s=Store(self.path,1,clock=lambda:self.now)
        self.bot.s=self.s;self.assertEqual(self.bot.flow(101)['answers']['name'],'Saved')
    def test_processed_update_payload_scrubbed(self):
        self.update('/start');self.assertEqual(self.s.one('SELECT payload FROM inbox')['payload'],'{}')
    def test_large_review_is_split_without_truncation(self):
        self.bot.send(101,'A'*9000,[[{'text':'Submit','callback_data':'test'}]])
        self.engine.drain();messages=self.api.chat(101)
        self.assertEqual(''.join(m['text'] for m in messages),'A'*9000)
        self.assertFalse(messages[0]['reply_markup']);self.assertTrue(messages[-1]['reply_markup'])
    def test_other_bot_commands_not_retained(self):
        u=self.update('/bind@AnotherBot secret',102,-1007,True)
        self.assertIsNone(self.s.one('SELECT update_id FROM inbox WHERE update_id=?',(u['update_id'],)))
    def test_all_bot_buttons_within_telegram_limits(self):
        self.complete('both')
        for message in self.api.messages:
            self.assertLessEqual(len(message['text']),4096)
            for row in message.get('reply_markup',{}).get('inline_keyboard',[]):
                for b in row:
                    if 'callback_data' in b: self.assertLessEqual(len(b['callback_data'].encode()),64)
