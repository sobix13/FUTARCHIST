"""English UI regressions and safe upgrades from legacy saved defaults."""
import json
import re
from ownership.core import Store
from ownership.english import CODE_PREFIX, OLD_INBOX, SPACE_PREFIX
from ownership.forms import FIELDS, LABELS
from ownership.management import Management, TEXT_DEFAULTS
from tests.helpers import Fixture

LEGACY_QUESTION = '\u0627\u0633\u0645 \u067e\u0631\u0648\u0698\u0647\u200c\u062a\u0648\u0646 \u0686\u06cc\u0647\u061f'
LEGACY_ACTIVE = '\u0641\u0639\u0627\u0644'


class EnglishTests(Fixture):
    def reopen_legacy(self):
        self.s.db.execute("DELETE FROM settings WHERE key='ui_english_v1'")
        self.s.close()
        self.s = Store(self.path,1,clock=lambda:self.now,gated=False)

    def test_home_ignores_legacy_language_preference_and_has_no_selector(self):
        self.s.db.execute("INSERT INTO settings VALUES('lang:101','fa')")
        self.update('/start')
        message = self.api.chat(101)[-1]
        self.assertIn('Enter the access code',message['text'])
        buttons = [button for row in message['reply_markup']['inline_keyboard'] for button in row]
        self.assertFalse(any(button['callback_data'].startswith('lang') for button in buttons))
        self.assertFalse(re.search(r'[\u0600-\u06ff]',json.dumps(message,ensure_ascii=False)))

    def test_custom_question_is_used_in_english_form(self):
        Management(self.s).set_text(1,'question:name','What should we call your team?',0)
        self.update('/start intake_'+self.route['token'])
        self.action('consent');self.action('purpose:general')
        self.assertIn('What should we call your team?',self.api.chat(101)[-1]['text'])

    def test_question_editor_exposes_full_default_prompt(self):
        settings = {row['key']:row['value'] for row in Management(self.s).texts(1)}
        for key,field in FIELDS.items():
            self.assertEqual(settings['question:'+key],field[0])
            self.assertGreater(len(settings['question:'+key]),1)

    def test_legacy_defaults_and_generated_labels_migrate_without_losing_answers(self):
        manager = Management(self.s)
        manager.set_text(1,'question:name',LEGACY_QUESTION,0)
        inbox = self.s.one("SELECT id FROM spaces WHERE creator=1 AND kind='personal'")['id']
        personal = self.s.one("SELECT id FROM spaces WHERE creator=2 AND kind='personal'")['id']
        self.s.db.execute('UPDATE spaces SET name=? WHERE id=?',(OLD_INBOX,inbox))
        self.s.db.execute('UPDATE spaces SET name=? WHERE id=?',(SPACE_PREFIX+'Nima',personal))
        self.s.db.execute('UPDATE routes SET name=? WHERE creator=2 AND space_id=?',(CODE_PREFIX+'Nima',personal))
        self.s.db.execute("INSERT INTO settings VALUES('lang:101','fa')")
        answers = {'name':LEGACY_ACTIVE,'index':3}
        self.bot.save(101,answers)
        self.reopen_legacy()
        self.assertEqual(Management(self.s).text('question:name'),FIELDS['name'][0])
        self.assertEqual(self.s.one("SELECT version FROM text_settings WHERE key='question:name'")['version'],2)
        self.assertEqual(self.s.one('SELECT name FROM spaces WHERE id=?',(inbox,))['name'],'Superadmin inbox')
        self.assertEqual(self.s.one('SELECT name FROM spaces WHERE id=?',(personal,))['name'],'Workspace Nima')
        self.assertEqual(self.s.one('SELECT name FROM routes WHERE creator=2 AND space_id=?',(personal,))['name'],'Intake code Nima')
        self.assertIsNone(self.s.one("SELECT value FROM settings WHERE key='lang:101'"))
        self.assertEqual(json.loads(self.s.one('SELECT data FROM flows WHERE user_id=101')['data']),answers)

    def test_upgrade_preserves_custom_copy_names_and_records(self):
        manager = Management(self.s)
        manager.set_text(1,'welcome',LEGACY_ACTIVE,0)
        manager.set_text(1,'help','Welcome to our review desk. Use /support for help.',0)
        self.s.db.execute('UPDATE spaces SET name=? WHERE id=?',(LEGACY_ACTIVE,self.team))
        self.s.db.execute('UPDATE routes SET name=? WHERE id=?',(LEGACY_ACTIVE,self.route['id']))
        project = self.create(name=LEGACY_ACTIVE,motivation='A private project description')
        record = dict(self.s.one('SELECT * FROM projects WHERE id=?',(project,)))
        self.reopen_legacy()
        self.assertEqual(Management(self.s).text('welcome'),LEGACY_ACTIVE)
        self.assertEqual(Management(self.s).text('help'),'Welcome to our review desk. Use /support for help.')
        self.assertEqual(self.s.one('SELECT name FROM spaces WHERE id=?',(self.team,))['name'],LEGACY_ACTIVE)
        self.assertEqual(self.s.one('SELECT name FROM routes WHERE id=?',(self.route['id'],))['name'],LEGACY_ACTIVE)
        self.assertEqual(dict(self.s.one('SELECT * FROM projects WHERE id=?',(project,))),record)

    def test_cached_admin_form_titles_migrate_but_entered_values_survive(self):
        flow = {'nonce':'existing','form':{'fields':[{'title':LEGACY_QUESTION}],
                'answers':{'name':LEGACY_ACTIVE}},'selected':self.team}
        self.bot.native.save(2,flow)
        self.reopen_legacy()
        migrated = json.loads(self.s.one('SELECT data FROM native_flows WHERE user_id=2')['data'])
        self.assertEqual(migrated['form']['fields'][0]['title'],FIELDS['name'][0])
        self.assertEqual(migrated['form']['answers'],flow['form']['answers'])
        self.assertEqual(migrated['nonce'],'existing')

    def test_upgrade_is_idempotent_and_keeps_new_custom_edits(self):
        manager = Management(self.s)
        manager.set_text(1,'question:name',LEGACY_QUESTION,0)
        self.reopen_legacy()
        manager = Management(self.s)
        manager.set_text(1,'question:name','Give us your project name.',2)
        self.s.close();self.s = Store(self.path,1,clock=lambda:self.now,gated=False)
        row = self.s.one("SELECT value,version FROM text_settings WHERE key='question:name'")
        self.assertEqual(row['value'],'Give us your project name.')
        self.assertEqual(row['version'],3)

    def test_builtin_form_choices_and_copy_are_english(self):
        values = list(TEXT_DEFAULTS.values())+list(LABELS.values())+[field[0] for field in FIELDS.values()]
        self.assertTrue(all(isinstance(value,str) for value in values))
        self.assertFalse(re.search(r'[\u0600-\u06ff]','\n'.join(values)))
