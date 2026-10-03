import json
import threading
from ownership.core import AppError, PERMISSIONS
from ownership.service import DEFAULT_TEMPLATE
from ownership.telegram import Engine, TelegramClient, TelegramError, UncertainDelivery
from ownership.simulator import FakeAPIServer
from tests.helpers import Fixture

class CampaignTests(Fixture):
    def preview(self,filters=None): return self.svc.campaign(2,self.team,'Gaming','Friday 18:00 UTC',DEFAULT_TEMPLATE,filters or {})
    def test_no_messages_during_preview(self):
        self.create();self.optin();c=self.preview();self.assertEqual(len(c['recipients']),1);self.assertEqual(self.s.one('SELECT COUNT(*) n FROM outbox')['n'],0)
    def test_unconsented_dm_skipped(self):
        self.create();c=self.preview();self.assertEqual(c['recipients'],[]);self.assertEqual(len(c['skipped']),1)
    def test_group_preferred_to_dm_not_both(self):
        pid=self.create();self.optin();self.update(self.svc.binding(2,pid)['command'],2,-1007,True)
        c=self.preview();self.assertEqual(len(c['recipients']),1);self.assertEqual(c['recipients'][0]['kind'],'group')
    def test_one_message_per_destination_across_projects(self):
        self.create();self.create(name='Second project');self.optin();c=self.preview();self.assertEqual(len(c['recipients']),1);self.assertEqual(len(c['skipped']),1)
    def test_preview_text_and_recipients_are_frozen(self):
        pid=self.create();self.optin();c=self.preview();old=c['recipients'][0]['text'];self.create(name='Renamed by new submission')
        self.assertEqual(self.svc.campaign_detail(2,c['id'])['recipients'][0]['text'],old)
    def test_bad_template_placeholders_rejected(self):
        for text in ('{project.__class__}','{project!r}','{project:>10}','{secret}','broken {'):
            with self.subTest(text=text),self.assertRaises(AppError): self.svc.campaign(2,self.team,'Topic','Time',text,{})
    def test_confirm_is_idempotent_conflict_not_duplicate(self):
        self.create();self.optin();c=self.preview();self.svc.confirm(2,c['id'])
        with self.assertRaises(AppError) as ctx:self.svc.confirm(2,c['id'])
        self.assertEqual(ctx.exception.status,409);self.assertEqual(self.s.one('SELECT COUNT(*) n FROM outbox')['n'],1)
    def test_cancel_pending_only(self):
        self.create();self.optin();c=self.preview();self.svc.confirm(2,c['id']);self.svc.cancel(2,c['id']);self.engine.drain()
        self.assertEqual(self.s.one('SELECT state FROM outbox')['state'],'cancelled');self.assertEqual(self.api.messages,[])
    def test_opt_out_after_preview_prevents_delivery(self):
        self.create();self.optin();c=self.preview();self.svc.confirm(2,c['id']);self.s.db.execute('UPDATE users SET invites=0 WHERE id=101');self.engine.drain()
        self.assertEqual(self.s.one('SELECT state FROM outbox')['state'],'cancelled')
    def test_admin_revocation_cancels_queued_delivery(self):
        self.create();self.optin();c=self.preview();self.svc.confirm(2,c['id']);self.s.membership(1,self.team,2,['read_general']);self.engine.drain()
        self.assertEqual(self.s.one('SELECT state FROM outbox')['state'],'cancelled')
    def test_raise_read_revocation_cancels_financial_campaign(self):
        self.create();self.optin();c=self.preview({'raise_status':'unsuccessful'});self.svc.confirm(2,c['id']);self.s.membership(1,self.team,2,['read_general','send']);self.engine.drain()
        self.assertEqual(self.s.one('SELECT state FROM outbox')['state'],'cancelled')
    def test_financial_campaign_hidden_from_general_admin(self):
        self.create();self.optin();c=self.preview({'raise_status':'unsuccessful'});self.s.membership(1,self.team,3,['read_general','send'])
        self.assertEqual(self.svc.campaigns(3,self.team),[])
        with self.assertRaises(AppError):self.svc.campaign_detail(3,c['id'])
    def test_financial_campaign_audit_is_redacted(self):
        self.create();self.optin();self.preview({'raise_status':'unsuccessful'})
        self.assertNotIn('campaign_preview',[a['action'] for a in self.svc.audit(3,self.team)])
    def test_reply_requires_representative(self):
        self.create();self.optin();c=self.preview();self.svc.confirm(2,c['id']);token=c['recipients'][0]['token']
        with self.assertRaises(AppError):self.bot.rsvp(102,token,'yes')
        self.bot.rsvp(101,token,'yes');self.assertEqual(self.svc.campaign_detail(2,c['id'])['recipients'][0]['response'],'yes')
    def test_disconnected_group_cancels_queued_job(self):
        pid=self.create();self.update(self.svc.binding(2,pid)['command'],2,-1007,True);c=self.preview();self.svc.confirm(2,c['id']);self.svc.group(2,pid,True);self.engine.drain()
        self.assertEqual(self.s.one("SELECT state FROM outbox WHERE dedupe LIKE 'campaign:%'")['state'],'cancelled')
    def test_no_group_auto_dm_fallback_after_preview(self):
        pid=self.create();self.optin();self.update(self.svc.binding(2,pid)['command'],2,-1007,True);c=self.preview();self.svc.confirm(2,c['id']);self.svc.group(2,pid,True);before=len(self.api.chat(101));self.engine.drain()
        self.assertEqual(len(self.api.chat(101)),before)
    def test_migrated_group_pending_invite_moves_to_same_group_new_id(self):
        pid=self.create();self.update(self.svc.binding(2,pid)['command'],2,-1007,True);c=self.preview();self.svc.confirm(2,c['id'])
        self.engine.ingest([{'update_id':500,'message':{'chat':{'id':-1007,'type':'group'},'migrate_to_chat_id':-1008}}]);self.engine.drain()
        r=self.svc.campaign_detail(2,c['id'])['recipients'][0]
        self.assertEqual(r['chat_id'],-1008);self.assertEqual(r['delivery_state'],'sent');self.assertTrue(self.api.chat(-1008))

class DeliveryTests(Fixture):
    def queue(self):
        with self.s.tx():return self.s.queue('sendMessage',{'chat_id':101,'text':'Test'},'test')
    def test_success_records_message_id(self):
        self.queue();self.engine.dispatch_one();r=self.s.one('SELECT * FROM outbox');self.assertEqual(r['state'],'sent');self.assertIsNotNone(r['telegram_message_id'])
    def test_429_respects_retry_after(self):
        self.queue();self.api.failures=[429];self.engine.dispatch_one();r=self.s.one('SELECT * FROM outbox');self.assertEqual(r['state'],'pending');self.assertEqual(r['next_at'],self.now+3)
        self.assertFalse(self.engine.dispatch_one());self.now+=3;self.engine.dispatch_one();self.assertEqual(self.s.one('SELECT state FROM outbox')['state'],'sent')
    def test_uncertain_timeout_is_not_retried(self):
        self.queue();self.api.failures=['timeout'];self.engine.dispatch_one();self.assertEqual(self.s.one('SELECT state FROM outbox')['state'],'uncertain');self.assertFalse(self.engine.dispatch_one())
    def test_403_disables_destination(self):
        self.queue();self.optin();self.api.failures=[403];self.engine.dispatch_one();self.assertEqual(self.s.one('SELECT state FROM outbox')['state'],'failed');self.assertFalse(self.s.actor(101)['invites'])
    def test_5xx_not_blindly_retried(self):
        self.queue();self.api.failures=[502];self.engine.dispatch_one();self.assertEqual(self.s.one('SELECT state FROM outbox')['state'],'uncertain')
    def test_restart_marks_inflight_uncertain(self):
        self.queue();self.s.db.execute("UPDATE outbox SET state='sending'");Engine(self.s,self.bot,self.api,False);self.assertEqual(self.s.one('SELECT state FROM outbox')['state'],'uncertain')
    def test_queue_dedupe_returns_original_id(self):
        oid=self.queue();self.assertEqual(self.queue(),oid);self.assertEqual(self.s.one('SELECT COUNT(*) n FROM outbox')['n'],1)
    def test_revoked_financial_note_never_sent(self):
        pid=self.create();self.s.note(2,pid,'raise','Sensitive question',True);self.s.membership(1,self.team,2,['read_general','send']);self.engine.drain();self.assertEqual(self.api.chat(101),[])
    def test_rate_limit_per_chat(self):
        engine=Engine(self.s,self.bot,self.api,True);self.queue();self.s.queue('sendMessage',{'chat_id':101,'text':'Second'},'second')
        self.assertTrue(engine.dispatch_one());self.assertFalse(engine.dispatch_one());self.now+=2;self.assertTrue(engine.dispatch_one())
    def test_group_rate_more_conservative_than_private_chat(self):
        engine=Engine(self.s,self.bot,self.api,True);self.s.queue('sendMessage',{'chat_id':-1007,'text':'First'});self.s.queue('sendMessage',{'chat_id':-1007,'text':'Second'})
        self.assertTrue(engine.dispatch_one());self.now+=2;self.assertFalse(engine.dispatch_one());self.now+=2;self.assertTrue(engine.dispatch_one())
    def test_real_transport_to_fake_telegram_http(self):
        server=FakeAPIServer(self.api);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            client=TelegramClient('DEMO',f'http://127.0.0.1:{server.server_port}',True)
            result=client.call('sendMessage',{'chat_id':101,'text':'HTTP transport'});self.assertEqual(result['text'],'HTTP transport')
            self.api.failures=[429]
            with self.assertRaises(TelegramError) as ctx:client.call('sendMessage',{'chat_id':101,'text':'Retry'})
            self.assertEqual(ctx.exception.retry_after,3)
            self.api.failures=['timeout']
            with self.assertRaises(UncertainDelivery):client.call('sendMessage',{'chat_id':101,'text':'Unknown'})
        finally:server.shutdown();server.server_close();thread.join(2)
    def test_transport_rejects_nonofficial_remote_url(self):
        with self.assertRaises(ValueError):TelegramClient('secret','http://attacker.example',True)
