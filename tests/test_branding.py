"""Image-only branding, public asset isolation and profile-upload safeguards."""
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import urlopen
from tests.test_http import HTTPFixture
from tools.brand_bot import api, set_profile

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT/'ownership/static'


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []

    def handle_data(self, value):
        self.items.append(value)


class BrandingFilesTests(unittest.TestCase):
    def test_original_image_bytes_are_unchanged(self):
        originals = {
            'futarchist-banner.jpeg': 'c5f3c21be5773c66f12998332f1b1447597a3ae3c2c0facb0271ced03595efff',
            'futarchist-logo.jpeg': 'e4df17b4da53a457662b721794f5d193f771e41dfc909cbd314cfc09319ed8e2',
        }
        for name, expected in originals.items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((STATIC/'assets'/name).read_bytes()).hexdigest(), expected)

    def test_existing_login_and_dashboard_text_is_unchanged(self):
        originals = {
            'index.html': '20feccd60a0407232fa3b3433aece599d552798ed587c593412537ee227ec994',
        }
        for name, expected in originals.items():
            parser = TextParser()
            parser.feed((STATIC/name).read_text())
            text = ' '.join(' '.join(parser.items).split())
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), expected)

    def test_image_styles_do_not_set_fonts_colors_or_hide_controls(self):
        css = re.sub(r'/\*.*?\*/', '', (STATIC/'branding.css').read_text(), flags=re.S)
        self.assertFalse(re.search(r'\b(?:color|background|font|opacity|visibility|filter)\b', css))
        self.assertNotIn('display: none', css)
        self.assertNotIn('position: fixed', css)
        self.assertIn('object-fit: contain', css)
        self.assertIn('@media (max-width: 700px)', css)

    def test_app_and_guide_use_original_images_and_keep_ecosystem_credit(self):
        app = (STATIC/'index.html').read_text()
        guide = (STATIC/'guide.html').read_text()
        self.assertEqual(app.count('class="identity-banner"'), 2)
        self.assertEqual(app.count('class="brand-picture"'), 2)
        for page in (app, guide):
            self.assertIn('/assets/futarchist-logo.jpeg', page)
            self.assertIn('/assets/futarchist-banner.jpeg', page)
            self.assertNotIn('/assets/futardio.png', page)
            self.assertIn('/assets/ownership.jpeg', page)
            self.assertIn('Built by Ownership', page)
        self.assertIn('/assets/metadao.png', app)


class BrandingHTTPTests(HTTPFixture):
    def test_brand_images_are_public_exact_jpegs(self):
        for name in ('futarchist-banner.jpeg', 'futarchist-logo.jpeg'):
            with self.subTest(name=name), urlopen(self.base+'/assets/'+name, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers['Content-Type'], 'image/jpeg')
                self.assertEqual(response.read(), (STATIC/'assets'/name).read_bytes())

    def test_brand_styles_are_public_and_do_not_expose_private_files(self):
        code, text, headers = self.request('/branding.css', raw=True)
        self.assertEqual(code, 200)
        self.assertEqual(headers['Content-Type'], 'text/css; charset=utf-8')
        self.assertEqual(text, (STATIC/'branding.css').read_text())
        for path in ('/assets/.env', '/assets/../core.py', '/api/me'):
            with self.subTest(path=path):
                self.assertIn(self.request(path)[0], (401, 404))


class ProfileToolTests(unittest.TestCase):
    def test_profile_upload_checks_identity_and_changes_only_photo(self):
        image = STATIC/'assets/futarchist-logo.jpeg'
        calls = []

        def open_request(request, timeout):
            calls.append(request)
            result = {'id': 8911627546, 'username': 'FutarchistBot'} if request.full_url.endswith('/getMe') else True
            return io.BytesIO(json.dumps({'ok': True, 'result': result}).encode())

        with patch('tools.brand_bot.urlopen', side_effect=open_request):
            result = set_profile('123:PRIVATE_TEST', 8911627546, image)
        self.assertEqual([r.full_url.rsplit('/', 1)[-1] for r in calls], ['getMe', 'setMyProfilePhoto'])
        self.assertIn(image.read_bytes(), calls[1].data)
        self.assertIn(b'attach://profile_image', calls[1].data)
        self.assertTrue(result['profile_updated'])
        self.assertFalse(result['text_changed'])
        self.assertFalse(result['menus_changed'])

    def test_wrong_bot_id_stops_before_upload(self):
        with patch('tools.brand_bot.api', return_value={'id': 100}) as call:
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                set_profile('TEST', 8911627546, STATIC/'assets/futarchist-logo.jpeg')
            self.assertEqual(call.call_count, 1)

    def test_invalid_file_stops_before_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory)/'not-an-image.jpeg'
            image.write_bytes(b'not a jpeg')
            with patch('tools.brand_bot.api', return_value={'id': 1}) as call:
                with self.assertRaisesRegex(ValueError, 'original JPG'):
                    set_profile('TEST', 1, image)
                self.assertEqual(call.call_count, 1)

    def test_connection_error_never_exposes_token(self):
        token = '123:PRIVATE_TEST'
        with patch('tools.brand_bot.urlopen', side_effect=URLError('https://example/bot'+token)):
            with self.assertRaises(ValueError) as error:
                api(token, 'getMe', b'{}', 'application/json')
        self.assertNotIn(token, str(error.exception))

    def test_api_error_is_not_reported_as_success(self):
        with patch('tools.brand_bot.urlopen', return_value=io.BytesIO(b'{"ok":false}')):
            with self.assertRaisesRegex(ValueError, 'did not confirm'):
                api('TEST', 'getMe', b'{}', 'application/json')
