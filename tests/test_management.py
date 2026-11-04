import hashlib
import http.cookiejar
import importlib.util
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'server'))
import management


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.database = self.state / 'registrations.sqlite3'
        self.username = 'admin'
        self.password = 'a-test-password-with-enough-length'
        salt, password_hash = management.password_hash(self.password)
        (self.state / 'admin-bootstrap.json').write_text(json.dumps({'username':self.username, 'salt':salt, 'password_hash':password_hash}))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.origin = 'http://127.0.0.1:' + str(self.port)
        env = dict(os.environ, KIRO_PREVIEW='1', KIRO_REGISTRATION_OPEN='1', KIRO_PORT=str(self.port), KIRO_DATABASE=str(self.database), KIRO_ALLOWED_ORIGINS=self.origin)
        self.proc = subprocess.Popen([sys.executable, str(ROOT / 'server/server.py')], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        for _ in range(100):
            try:
                self.request('/api/status')
                break
            except OSError:
                time.sleep(.05)
        else:
            self.fail('preview server did not start')
        self.csrf = ''

    def tearDown(self):
        self.proc.terminate()
        self.proc.communicate(timeout=5)
        self.tmp.cleanup()

    def request(self, path, data=None, origin=None, csrf=None):
        headers = {}
        body = None
        if data is not None:
            headers = {'Content-Type':'application/json', 'Origin':origin if origin is not None else self.origin}
            if csrf is not None:
                headers['X-CSRF-Token'] = csrf
            body = json.dumps(data).encode('utf-8')
        try:
            response = self.opener.open(Request(self.origin + path, data=body, headers=headers), timeout=5)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            return response.status, json.loads(raw) if response.headers.get_content_type() == 'application/json' else raw

    def login(self):
        code, result = self.request('/api/admin/login', {'username':self.username, 'password':self.password})
        self.assertEqual(code, 200)
        self.csrf = result['csrf']
        return result

    def register(self):
        payload = {'name':'测试同学','affiliation':'测试院系','contact':'only-test@example.invalid','message':'原创想法','track':'校园奇妙物','team_status':'个人报名','consent':True,'website':''}
        self.assertEqual(self.request('/api/registrations', payload)[0], 201)

    def test_private_records_require_login_and_csrf(self):
        self.register()
        self.assertEqual(self.request('/api/admin/registrations')[0], 401)
        self.assertEqual(self.request('/api/admin/login', {'username':'admin', 'password':'wrong'})[0], 401)
        self.login()
        code, result = self.request('/api/admin/registrations')
        self.assertEqual(code, 200)
        self.assertEqual(result['registrations'][0]['name'], '测试同学')
        self.assertEqual(self.request('/api/admin/announcement', {'title':'Test','body':'Test','published':True})[0], 403)
        self.assertEqual(self.request('/api/admin/announcement', {'title':'Test','body':'Test','published':True}, origin='https://outside.example', csrf=self.csrf)[0], 403)
        self.assertEqual(self.request('/api/admin/logout', {}, csrf=self.csrf)[0], 200)
        self.assertEqual(self.request('/api/admin/registrations')[0], 401)
        self.assertFalse((self.state / 'admin-bootstrap.json').exists())

    def test_publish_edit_and_unpublish_announcement(self):
        self.login()
        payload = {'id':None,'title':'公告 <script>alert(1)</script>', 'body':'活动安排\n第二行','published':False}
        code, result = self.request('/api/admin/announcement', payload, csrf=self.csrf)
        self.assertEqual(code, 200)
        payload['id'] = result['id']
        self.assertEqual(self.request('/api/announcements')[1]['announcements'], [])
        payload['published'] = True
        self.assertEqual(self.request('/api/admin/announcement', payload, csrf=self.csrf)[0], 200)
        public = self.request('/api/announcements')[1]['announcements']
        self.assertEqual(len(public), 1)
        self.assertEqual(public[0]['body'], '活动安排\n第二行')
        payload['published'] = False
        self.assertEqual(self.request('/api/admin/announcement', payload, csrf=self.csrf)[0], 200)
        self.assertEqual(self.request('/api/announcements')[1]['announcements'], [])

    def test_mail_settings_are_private_and_forward_requires_configuration(self):
        self.register()
        self.login()
        self.assertEqual(self.request('/api/admin/forward', {'id':1,'recipient':'receiver@example.org'}, csrf=self.csrf)[0], 409)
        mail = {'host':'smtp.example.org','port':465,'security':'ssl','username':'sender@example.org','from_address':'sender@example.org','from_name':'K Campus','password':'test-authorization-code'}
        self.assertEqual(self.request('/api/admin/mail-settings', mail, csrf=self.csrf)[0], 200)
        code, result = self.request('/api/admin/mail-settings')
        self.assertEqual(code, 200)
        self.assertTrue(result['password_configured'])
        self.assertNotIn('test-authorization-code', json.dumps(result))
        self.assertEqual((self.state / 'mail-settings.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.request('/api/admin/forward', {'id':1,'recipient':'invalid\naddress'}, csrf=self.csrf)[0], 400)

    def test_password_change_revokes_sessions(self):
        self.login()
        result = self.request('/api/admin/password', {'current':self.password, 'new':'new-secure-password-123'}, csrf=self.csrf)
        self.assertEqual(result[0], 200)
        self.assertEqual(self.request('/api/admin/session')[0], 401)
        self.assertEqual(self.request('/api/admin/login', {'username':self.username,'password':self.password})[0], 401)
        self.password = 'new-secure-password-123'
        self.login()

    def test_forward_constructs_message_and_uses_tls(self):
        self.register()
        mail = {'host':'smtp.example.org','port':465,'security':'ssl','username':'sender@example.org','from_address':'sender@example.org','from_name':'K Campus','password':'test-authorization-code'}
        (self.state / 'mail-settings.json').write_text(json.dumps(mail))
        class Handler:
            def __init__(self):
                self.result = None
            def respond(self, code, body, *args):
                self.result = (code, body)
        handler = Handler()
        manager = management.Management(lambda: sqlite3.connect(self.database), self.state, {self.origin}, True)
        manager.read_json = lambda h: {'id':1,'recipient':'receiver@example.org'}
        with patch('management.smtplib.SMTP_SSL') as smtp:
            client = smtp.return_value
            manager.forward(handler)
        self.assertEqual(handler.result[0], 200)
        smtp.assert_called_once()
        client.login.assert_called_once_with(mail['username'], mail['password'])
        message = client.send_message.call_args.args[0]
        self.assertEqual(message['To'], 'receiver@example.org')
        self.assertIn('测试同学', message.get_content())


if __name__ == '__main__':
    unittest.main()
