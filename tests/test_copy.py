"""Practical guide copy, unchanged app logic and complete offline packaging."""
import hashlib
from pathlib import Path
import re
import unittest

from ownership.guide import SECTIONS
from tools.package import standalone_guide

ROOT = Path(__file__).resolve().parents[1]
POLICY = re.compile(r'\bEnglish\b|language selector|no AI services|no AI feature|emoji controls', re.I)


class CopyTests(unittest.TestCase):
    def test_public_docs_focus_on_work_without_policy_repetition(self):
        for name in ('README.md', 'docs/HELP.md', 'docs/ARCHITECTURE.md', 'docs/RELEASE.md',
                     'extensions/DEPLOY.md', 'extensions/UPDATES.md', 'ownership/static/guide.html'):
            with self.subTest(path=name):
                # Technical compatibility module paths aren't user-facing claims.
                text = (ROOT/name).read_text().replace('ownership/english.py', 'compatibility module')
                self.assertIsNone(POLICY.search(text))

    def test_native_guide_has_no_policy_repetition(self):
        for key, (_, _, text) in SECTIONS.items():
            with self.subTest(section=key):
                self.assertIsNone(POLICY.search(text))

    def test_dashboard_changes_are_only_the_two_requested_copy_revisions(self):
        text = (ROOT/'ownership/static/app.js').read_text()
        self.assertIsNone(POLICY.search(text))
        text = text.replace('Edit bot messages and question wording.',
                            'Edit English messages and question wording used by the bot.')
        text = text.replace("Each preview replaces these fields with the recipient's project details and your topic and time.",
                            'The message uses no AI and is personalized using these fields.')
        self.assertEqual(hashlib.sha256(text.encode()).hexdigest(),
                         '9c10fcf5907ba451eb3db92837a0b794ee2b8d0b60fa3fa9f20907d34f89e6cf')

    def test_readme_maps_roles_surfaces_and_the_workflow(self):
        text = (ROOT/'README.md').read_text()
        for value in ('Project representative', 'Superadmin', 'Access code', 'Telegram bot',
                      'Web dashboard', 'select a workspace', 'review submitted Cases',
                      'One persistent SQLite database', "doesn't expose someone's personal workspace"):
            with self.subTest(value=value):
                self.assertIn(value, text)

    def test_offline_guide_matches_source_and_embeds_styles_and_images(self):
        document = standalone_guide()
        self.assertEqual((ROOT/'docs/USER_GUIDE.html').read_text(), document)
        self.assertNotIn('/assets/', document)
        self.assertNotIn('<link rel="stylesheet"', document)
        for name in ('style.css', 'branding.css'):
            self.assertIn((ROOT/'ownership/static'/name).read_text(), document)
        self.assertIn('src="data:image/jpeg;base64,', document)
        self.assertIn('href="data:image/jpeg;base64,', document)
        self.assertIn('Telegram and the web dashboard use the same records', document)

    def test_interface_styles_are_unchanged(self):
        expected = {
            'style.css': '3867c107dd4b388c3e65e504e9100709458ecbd92e17e089ae22b11779452c1e',
            'guidance.css': 'bf7a193ad891e453f68ebe6941bcbcb887ba3dedb62cf538fd0418ddd647fb2e',
            'branding.css': '120eb76720122ec94d78dad83080789ccfeafc928dd7804a94a1f89627bb28a3',
        }
        for name, digest in expected.items():
            with self.subTest(path=name):
                self.assertEqual(hashlib.sha256((ROOT/'ownership/static'/name).read_bytes()).hexdigest(), digest)

    def test_native_guide_keeps_access_and_confirmation_instructions(self):
        self.assertIn('It does not grant admin access', SECTIONS['start'][2])
        self.assertIn('Financial details require Raise read permission', SECTIONS['cases'][2])
        self.assertIn('before confirming', SECTIONS['invitations'][2])
        self.assertIn('configured HTTPS address', SECTIONS['browser'][2])
        self.assertIn('does not delete your case', SECTIONS['replies'][2])
