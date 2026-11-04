import csv
import io
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
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / 'registrations.sqlite3'
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.origin = 'http://127.0.0.1:' + str(self.port)
        env = dict(os.environ, KIRO_PREVIEW='1', KIRO_REGISTRATION_OPEN='1', KIRO_PORT=str(self.port), KIRO_DATABASE=str(self.database), KIRO_ALLOWED_ORIGINS=self.origin)
        self.proc = subprocess.Popen([sys.executable, str(ROOT / 'server/server.py')], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(100):
            try:
                self.request('/api/status')
                break
            except OSError:
                time.sleep(.05)
        else:
            self.fail('preview server did not start')

    def tearDown(self):
        self.proc.terminate()
        self.proc.communicate(timeout=5)
        self.temp.cleanup()

    def request(self, path, data=None, origin=None):
        headers = {}
        body = None
        if data is not None:
            headers['Content-Type'] = 'application/json'
            headers['Origin'] = origin or self.origin
            body = json.dumps(data).encode()
        try:
            response = urlopen(Request(self.origin + path, data=body, headers=headers), timeout=3)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.read()

    def test_page_status_and_real_registration(self):
        status, html = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn('CHANGSHA'.encode(), html)
        status, body = self.request('/api/status')
        self.assertTrue(json.loads(body)['registration_open'])
        payload = {'name':'测试同学', 'affiliation':'测试院系', 'contact':'test@example.invalid', 'message':'一起做项目', 'track':'校园奇妙物', 'team_status':'已有队伍', 'team_name':'测试队', 'role':'设计', 'consent':True, 'website':''}
        status, body = self.request('/api/registrations', payload)
        self.assertEqual(status, 201)
        self.assertTrue(json.loads(body)['ok'])
        with sqlite3.connect(self.database) as db:
            row = db.execute('SELECT name, affiliation, contact, message, track, team_status, team_name, role FROM registrations').fetchone()
        self.assertEqual(row, ('测试同学', '测试院系', 'test@example.invalid', '一起做项目', '校园奇妙物', '已有队伍', '测试队', '设计'))
        self.assertEqual(self.database.stat().st_mode & 0o777, 0o600)

    def test_validation_origin_and_honeypot(self):
        base = {'name':'Test', 'affiliation':'School', 'contact':'test@example.invalid', 'message':'', 'consent':True, 'website':''}
        self.assertEqual(self.request('/api/registrations', dict(base, consent=False))[0], 400)
        self.assertEqual(self.request('/api/registrations', dict(base, name=''))[0], 400)
        self.assertEqual(self.request('/api/registrations', dict(base, message='x' * 501))[0], 400)
        self.assertEqual(self.request('/api/registrations', dict(base, track='不存在的赛道'))[0], 400)
        self.assertEqual(self.request('/api/registrations', base, origin='https://untrusted.example')[0], 403)
        self.assertEqual(self.request('/api/registrations', dict(base, website='spam.example'))[0], 200)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM registrations').fetchone()[0], 0)

    def test_export_escapes_spreadsheet_formulas(self):
        payload = {'name':'=unsafe', 'affiliation':'School', 'contact':'test@example.invalid', 'message':'', 'consent':True, 'website':''}
        self.assertEqual(self.request('/api/registrations', payload)[0], 201)
        env = dict(os.environ, KIRO_DATABASE=str(self.database))
        result = subprocess.run([sys.executable, str(ROOT / 'server/server.py'), 'export'], env=env, capture_output=True, text=True, check=True)
        rows = list(csv.reader(io.StringIO(result.stdout)))
        self.assertEqual(rows[1][1], "'=unsafe")

    def test_existing_registrations_survive_schema_upgrade(self):
        old = Path(self.temp.name) / 'old.sqlite3'
        with sqlite3.connect(old) as db:
            db.execute('CREATE TABLE registrations (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, name TEXT NOT NULL, affiliation TEXT NOT NULL, contact TEXT NOT NULL, message TEXT NOT NULL)')
            db.execute('INSERT INTO registrations VALUES (1, ?, ?, ?, ?, ?)', ('2026-01-01', 'Previously registered', 'School', 'test@example.invalid', 'Idea'))
        spec = importlib.util.spec_from_file_location('registration_server', ROOT / 'server/server.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.DATABASE = old
        db = module.connect()
        try:
            row = db.execute('SELECT name, track, team_status, team_name, role FROM registrations').fetchone()
            self.assertEqual(row, ('Previously registered', '', '', '', ''))
        finally:
            db.close()


if __name__ == '__main__':
    unittest.main()
