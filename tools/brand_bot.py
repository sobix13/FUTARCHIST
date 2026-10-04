"""Set only the supplied bot profile image. Never change bot text or menus."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import secrets
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ownership.__main__ import load_env


def api(token, method, body, content_type):
    request = Request('https://api.telegram.org/bot' + token + '/' + method,
                      data=body, headers={'Content-Type': content_type})
    try:
        with urlopen(request, timeout=25) as response:
            result = json.load(response)
    except HTTPError as error:
        raise ValueError('Telegram returned HTTP ' + str(error.code) + '.') from None
    except (URLError, TimeoutError, OSError):
        raise ValueError('Telegram connection failed. No token is logged.') from None
    except (ValueError, UnicodeError):
        raise ValueError('Telegram returned an invalid response.') from None
    if not isinstance(result, dict) or result.get('ok') is not True:
        raise ValueError('Telegram did not confirm the image update.')
    return result.get('result')


def set_profile(token, expected_bot_id, image):
    identity = api(token, 'getMe', b'{}', 'application/json')
    if not isinstance(identity, dict) or identity.get('id') != expected_bot_id:
        raise ValueError('Bot identity mismatch. No image was changed.')
    image = Path(image)
    data = image.read_bytes()
    if image.suffix.lower() not in ('.jpg', '.jpeg') or not data.startswith(b'\xff\xd8'):
        raise ValueError('Use the original JPG profile image.')
    if len(data) > 5 * 1024 * 1024:
        raise ValueError('Profile image exceeds the upload limit.')
    boundary = 'Futarchist' + secrets.token_hex(16)
    photo = json.dumps({'type': 'static', 'photo': 'attach://profile_image'})
    body = (
        '--' + boundary + '\r\nContent-Disposition: form-data; name="photo"\r\n\r\n'
        + photo + '\r\n--' + boundary
        + '\r\nContent-Disposition: form-data; name="profile_image"; filename="futarchist-logo.jpeg"'
        + '\r\nContent-Type: image/jpeg\r\n\r\n'
    ).encode('ascii') + data + ('\r\n--' + boundary + '--\r\n').encode('ascii')
    result = api(token, 'setMyProfilePhoto', body, 'multipart/form-data; boundary=' + boundary)
    if result is not True:
        raise ValueError('Telegram did not confirm the image update.')
    return {'profile_updated': True, 'bot_id': identity['id'], 'username': identity.get('username'),
            'text_changed': False, 'menus_changed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env', default='.env')
    parser.add_argument('--expected-bot-id', type=int, required=True)
    parser.add_argument('--apply-profile', action='store_true')
    args = parser.parse_args()
    if not args.apply_profile:
        parser.exit(1, 'No change requested. Add --apply-profile to set the image.\n')
    load_env(args.env)
    try:
        token = os.environ.get('BOT_TOKEN', '').strip()
        if not token:
            raise ValueError('BOT_TOKEN is not configured.')
        result = set_profile(token, args.expected_bot_id, ROOT/'ownership/static/assets/futarchist-logo.jpeg')
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
