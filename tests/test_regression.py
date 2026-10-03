import concurrent.futures
import subprocess
import sys
from pathlib import Path
from extensions.maintenance import copy_database
from ownership.core import AppError
from tests.helpers import Fixture

class MaintenanceTests(Fixture):
    def test_backup_and_restore_new_file(self):
        self.create();backup=self.path.parent/'backup.sqlite3';restored=self.path.parent/'restored.sqlite3'
        counts=copy_database(self.path,backup);self.assertEqual(counts['projects'],1);self.assertEqual(copy_database(backup,restored),counts)
    def test_backup_refuses_overwrite(self):
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):copy_database(self.path,self.path)
        self.assertEqual(self.path.read_bytes(),before)
    def test_backup_requires_existing_parent_and_source(self):
        with self.assertRaises(ValueError):copy_database(self.path,self.path.parent/'missing'/'backup.sqlite3')
        with self.assertRaises(ValueError):copy_database(self.path.parent/'missing.sqlite3',self.path.parent/'backup.sqlite3')
    def test_unknown_schema_fails_closed(self):
        from ownership.core import Store
        self.s.db.execute('PRAGMA user_version=99')
        with self.assertRaises(RuntimeError):Store(self.path,1)
    def test_database_owner_mismatch_fails_closed(self):
        from ownership.core import Store
        with self.assertRaises(RuntimeError):Store(self.path,100)
    def test_live_runner_no_configuration_fails_closed(self):
        import os
        env={k:v for k,v in os.environ.items() if k not in ('BOT_TOKEN','OWNER_TG_ID','BOT_USERNAME','APP_URL')}
        result=subprocess.run([sys.executable,'-m','ownership','--env',str(self.path.parent/'missing.env')],capture_output=True,text=True,env=env)
        self.assertNotEqual(result.returncode,0);self.assertIn('OWNER_TG_ID',result.stderr)
    def test_demo_runner_refuses_public_bind(self):
        result=subprocess.run([sys.executable,'-m','ownership','--demo','--host','0.0.0.0'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('loopback',result.stderr)

class RegressionTests(Fixture):
    def test_edit_after_separate_general_and_raise_routes(self):
        r1=self.s.route(2,self.team,'General','general',2);r2=self.s.route(2,self.team,'Raise','raise',2)
        pid=self.create(route=r1,purpose='general');self.create(route=r2,purpose='raise')
        self.update('/projects');self.callback('edit:'+str(pid))
        self.assertEqual(self.flow()['purpose'],'both');self.assertEqual(self.flow()['pid'],pid)
    def test_permission_recheck_rejects_confirm_after_financial_revoke(self):
        from ownership.service import DEFAULT_TEMPLATE
        self.create();self.optin();c=self.svc.campaign(2,self.team,'Topic','When',DEFAULT_TEMPLATE,{'retry':'yes'})
        self.s.membership(1,self.team,2,['read_general','send'])
        with self.assertRaises(AppError):self.svc.confirm(2,c['id'])
        self.assertEqual(self.s.one('SELECT state FROM campaigns')['state'],'draft')
    def test_financial_export_audit_does_not_leak_filter_count(self):
        self.create();self.s.csv_export(2,self.team,{'raise_status':'unsuccessful'})
        self.assertNotIn('csv_exported',[a['action'] for a in self.svc.audit(3,self.team)])
    def test_financial_invite_response_audit_does_not_leak(self):
        from ownership.service import DEFAULT_TEMPLATE
        self.create();self.optin();c=self.svc.campaign(2,self.team,'Topic','When',DEFAULT_TEMPLATE,{'retry':'yes'});self.svc.confirm(2,c['id']);self.bot.rsvp(101,c['recipients'][0]['token'],'yes')
        self.assertNotIn('invitation_response',[a['action'] for a in self.svc.audit(3,self.team)])
    def test_data_transaction_rollback_no_partial_project(self):
        with self.assertRaises(RuntimeError):
            with self.s.tx():
                self.create();raise RuntimeError('Simulated failure after project insert')
        self.assertEqual(self.s.one('SELECT COUNT(*) n FROM projects')['n'],0)
    def test_concurrent_same_submission_creates_single_project(self):
        with concurrent.futures.ThreadPoolExecutor(4) as pool:ids=list(pool.map(lambda _:self.create(),range(8)))
        self.assertEqual(len(set(ids)),1);self.assertEqual(self.s.one('SELECT COUNT(*) n FROM cases')['n'],2)
    def test_long_unicode_messages_respect_conservative_telegram_limit(self):
        from ownership.core import text_units
        text='\U0001f600'*3000;self.bot.send(101,text);self.engine.drain();messages=self.api.chat(101)
        self.assertEqual(''.join(m['text'] for m in messages),text)
        self.assertTrue(all(text_units(m['text'])<=3800 for m in messages))
    def test_no_emoji_in_dashboard_design(self):
        import re
        root=Path(__file__).parents[1]/'ownership'/'static'
        emoji=re.compile('[\U0001f300-\U0001faff\u2600-\u27bf]')
        for name in ('index.html','app.js','style.css','emulator.html','emulator.js'):
            with self.subTest(file=name):self.assertIsNone(emoji.search((root/name).read_text()))
    def test_schema_integrity_after_combined_operations(self):
        pid=self.create();self.s.note(2,pid,'raise','Internal');self.s.note(2,pid,'general','Question',True)
        self.assertEqual(self.s.one('PRAGMA integrity_check')['integrity_check'],'ok');self.assertEqual(self.s.rows('PRAGMA foreign_key_check'),[])
