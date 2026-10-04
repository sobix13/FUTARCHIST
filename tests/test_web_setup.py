import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from extensions.web_setup import choose_host, detect_ipv4, hostname, public_ipv4, set_origin


class WebSetupTests(unittest.TestCase):
    def test_private_loopback_and_reserved_ips_are_rejected(self):
        for value in ('127.0.0.1','10.1.2.3','192.168.1.1','0.0.0.0','203.0.113.7','::1','invalid'):
            with self.subTest(value=value),self.assertRaises(ValueError):public_ipv4(value)

    def test_public_ipv4_is_normalized(self):
        self.assertEqual(public_ipv4(' 8.8.8.8 '),'8.8.8.8')

    def test_host_rejects_ports_paths_shell_syntax_and_bare_ip(self):
        for value in ('https://example.com','example.com:443','example.com/path','x;id.example.com','*.example.com','8.8.8.8','example.com\nOTHER=value','-x.example.com','example.com.'):
            with self.subTest(value=value),self.assertRaises(ValueError):hostname(value)

    def test_explicit_hostname_is_normalized(self):
        self.assertEqual(choose_host('Panel.Example.com'),'panel.example.com')

    def test_generated_host_requires_dns_to_the_expected_ip(self):
        with patch('extensions.web_setup.socket.getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]):
            self.assertEqual(choose_host(address='8.8.8.8'),'futarchist-8-8-8-8.sslip.io')
        with patch('extensions.web_setup.socket.getaddrinfo',return_value=[(2,1,6,'',('1.1.1.1',443))]),self.assertRaises(ValueError):
            choose_host(address='8.8.8.8')

    def test_existing_ssh_server_address_avoids_external_lookup(self):
        with patch.dict(os.environ,{'SSH_CONNECTION':'1.1.1.1 50000 8.8.8.8 22'},clear=True),patch('extensions.web_setup.urlopen') as fetch:
            self.assertEqual(detect_ipv4(),'8.8.8.8');fetch.assert_not_called()

    def test_origin_update_preserves_credentials_owners_and_file_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'.env'
            original=b'# Private config\nBOT_TOKEN=TEST_TOKEN_VALUE\nOWNER_TG_ID=1\nAPP_URL=\nSUPER_ADMIN_IDS=1,2\nDATABASE_PATH=data/live.sqlite3\n'
            file.write_bytes(original);file.chmod(0o640);before=file.stat()
            self.assertEqual(set_origin(file,'https://panel.example.com'),'https://panel.example.com')
            self.assertEqual(file.read_bytes(),original.replace(b'APP_URL=\n',b'APP_URL=https://panel.example.com\n'))
            self.assertEqual(file.stat().st_mode&0o777,0o640)
            self.assertEqual((file.stat().st_uid,file.stat().st_gid),(before.st_uid,before.st_gid))
            self.assertEqual([p.name for p in Path(folder).iterdir()],['.env'])

    def test_missing_origin_and_crlf_are_handled(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'.env';file.write_bytes(b'OWNER_TG_ID=1\r\nBOT_TOKEN=TEST_TOKEN_VALUE')
            set_origin(file,'panel.example.com')
            self.assertEqual(file.read_bytes(),b'OWNER_TG_ID=1\r\nBOT_TOKEN=TEST_TOKEN_VALUE\r\nAPP_URL=https://panel.example.com\r\n')

    def test_duplicate_origin_is_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'.env';original=b'APP_URL=\nAPP_URL=https://old.example.com\n';file.write_bytes(original)
            with self.assertRaises(ValueError):set_origin(file,'panel.example.com')
            self.assertEqual(file.read_bytes(),original)

    def test_symlink_env_is_rejected_without_touching_target(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'private';target.write_bytes(b'APP_URL=\n');link=Path(folder)/'.env';link.symlink_to(target)
            with self.assertRaises(ValueError):set_origin(link,'panel.example.com')
            self.assertEqual(target.read_bytes(),b'APP_URL=\n')

    def test_invalid_origin_preserves_file(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'.env';original=b'APP_URL=\n';file.write_bytes(original)
            with self.assertRaises(ValueError):set_origin(file,'https://panel.example.com/path')
            self.assertEqual(file.read_bytes(),original)


class WebInstallerTests(unittest.TestCase):
    """Exercise the real shell flow in a temporary tree with fake host services.

    No real certificates, firewall settings, package installs or system units
    are changed. Helper/config validation still uses the real Python code.
    """
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='futarchist-web-flow-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.repo=Path(__file__).resolve().parents[1]
        self.app=self.root/'srv/futarchist'
        self.bin=self.root/'bin';self.bin.mkdir()
        for folder in (self.app/'.venv/bin',self.app/'data',self.app/'extensions',self.root/'etc/systemd/system',self.root/'etc/nginx/conf.d'):
            folder.mkdir(parents=True,exist_ok=True)
        (self.app/'.venv/bin/python').symlink_to(sys.executable)
        for name in ('web_setup.py','futarchist-web.service.example'):
            (self.app/'extensions'/name).write_bytes((self.repo/'extensions'/name).read_bytes())
        self.envfile=self.app/'.env'
        self.original=b'BOT_TOKEN=TEST_TOKEN_VALUE\nBOT_USERNAME=FutarchistBot\nOWNER_TG_ID=1\nSUPER_ADMIN_IDS=1,2\nAPP_URL=\nDATABASE_PATH=data/live.sqlite3\n'
        self.envfile.write_bytes(self.original);self.envfile.chmod(0o640)
        self.site=self.root/'etc/nginx/conf.d/futarchist.conf'
        self.log=self.root/'commands.log'
        self.environment={key:value for key,value in os.environ.items() if key not in ('BOT_TOKEN','BOT_USERNAME','APP_URL','FUTARCHIST_PUBLIC_IPV4','FUTARCHIST_WEB_HOST')}
        self.environment.update(PATH=str(self.bin)+os.pathsep+os.environ['PATH'],PYTHONPATH=str(self.repo),FUTARCHIST_WEB_HOST='panel.example.com',TEST_LOG=str(self.log))
        source=(self.repo/'extensions/setup-web.sh').read_text()
        source=source.replace('[[ $EUID -eq 0 ]]','[[ 1 -eq 1 ]]')
        for path in ('/srv/futarchist','/etc/nginx','/etc/letsencrypt','/etc/systemd/system','/var/lib/futarchist-acme'):
            source=source.replace(path,str(self.root)+path)
        self.script=self.root/'setup.sh';self.script.write_text(source)
        for command in ('apt-get','nginx','ss','certbot','systemctl','curl','runuser','timeout'):
            body='#!/bin/sh\nprintf "%s\\n" '+shlex.quote(command+' ')+'"$*" >>"$TEST_LOG"\n'
            if command=='ss':body+='printf "%s" "${TEST_LISTENER:-}"\n'
            if command=='certbot':body+='[ "${TEST_ACME_FAIL:-0}" != 1 ] || exit 1\n'
            if command=='systemctl':body+='if [ "${TEST_RESTART_FAIL:-0}" = 1 ] && [ "$1" = restart ]; then exit 1; fi\n'
            if command=='curl':body+='if [ "${TEST_PUBLIC_FAIL:-0}" = 1 ]; then printf \'{"demo":true,"bot_name":"WrongApp"}\'; else printf \'{"demo":false,"bot_name":"FutarchistBot"}\'; fi\n'
            if command=='timeout':body+='shift\nexec "$@"\n'
            body+='exit 0\n'
            file=self.bin/command;file.write_text(body);file.chmod(0o755)

    def run_setup(self,**values):
        self.environment.update(values)
        return subprocess.run(['bash',str(self.script)],cwd=self.app,env=self.environment,capture_output=True,text=True,timeout=15)

    def commands(self):return self.log.read_text() if self.log.exists() else ''

    def test_success_enables_web_and_preserves_private_config(self):
        result=self.run_setup()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.envfile.read_bytes(),self.original.replace(b'APP_URL=\n',b'APP_URL=https://panel.example.com\n'))
        self.assertEqual(self.envfile.stat().st_mode&0o777,0o640)
        self.assertIn('proxy_pass http://127.0.0.1:8765',self.site.read_text())
        self.assertIn('enable --now futarchist-web.service',self.commands())
        self.assertIn('restart futarchist-web.service futarchist-bot.service',self.commands())
        self.assertIn('enable --now certbot.timer',self.commands())
        self.assertIn('--configure-bot',self.commands())
        self.assertIn('Dashboard ready: https://panel.example.com',result.stdout)
        self.assertNotIn('TEST_TOKEN_VALUE',result.stdout+result.stderr+self.commands())

    def test_existing_non_nginx_proxy_stops_before_any_changes(self):
        result=self.run_setup(TEST_LISTENER='LISTEN 0 4096 *:443 *:* users:(("caddy",pid=1,fd=3))\n')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('belongs to another service',result.stderr)
        self.assertEqual(self.envfile.read_bytes(),self.original)
        self.assertFalse(self.site.exists())
        self.assertNotIn('apt-get',self.commands())
        self.assertNotIn('systemctl',self.commands())

    def test_certificate_failure_restores_site_without_restarting_bot(self):
        previous='# FUTARCHIST managed\n# Previous working site\n'
        self.site.write_text(previous)
        result=self.run_setup(TEST_ACME_FAIL='1')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.site.read_text(),previous)
        self.assertEqual(self.envfile.read_bytes(),self.original)
        self.assertNotIn('futarchist-bot.service',self.commands())
        self.assertIn('configuration was restored',result.stderr)

    def test_wrong_public_app_does_not_change_origin_or_restart_bot(self):
        result=self.run_setup(TEST_PUBLIC_FAIL='1')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(self.site.exists())
        self.assertEqual(self.envfile.read_bytes(),self.original)
        self.assertNotIn('futarchist-bot.service',self.commands())
        self.assertIn('did not return the live FUTARCHIST app',result.stderr)

    def test_failure_after_origin_change_restores_config_and_service_state(self):
        previous='# FUTARCHIST managed\n# Previous working site\n'
        self.site.write_text(previous)
        result=self.run_setup(TEST_RESTART_FAIL='1')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.site.read_text(),previous)
        self.assertEqual(self.envfile.read_bytes(),self.original)
        self.assertEqual(self.envfile.stat().st_mode&0o777,0o640)
        self.assertIn('try-restart futarchist-web.service futarchist-bot.service',self.commands())
        self.assertNotIn('Dashboard ready:',result.stdout)
