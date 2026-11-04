#!/usr/bin/env python3
"""Remove exactly one named synthetic QA record after an end-to-end test."""
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
from urllib.request import urlopen

name = sys.argv[1]
if not re.fullmatch(r'TEST-KIRO-\d+', name):
    raise SystemExit('Not a synthetic QA identifier')
database = Path('/var/lib/kiro-hackathon/registrations.sqlite3')
if not database.is_file():
    raise SystemExit('Registration database missing')
subprocess.run(['systemctl', 'stop', 'kiro-hackathon.service'], check=True, capture_output=True)
try:
    with sqlite3.connect(str(database), timeout=10) as db:
        key = (name, '网站测试', 'test@example.invalid')
        count = db.execute('SELECT COUNT(*) FROM registrations WHERE name = ? AND affiliation = ? AND contact = ?', key).fetchone()[0]
        if count != 1:
            raise RuntimeError('Expected one matching test record; refusing deletion')
        if len(sys.argv) > 2 and sys.argv[2] == '--detailed':
            row = db.execute('SELECT track, team_status, team_name, role, message FROM registrations WHERE name = ? AND affiliation = ? AND contact = ?', key).fetchone()
            expected = ('校园开挂术', '已有队伍', '网站测试队', '设计', '这是一条验证报名流程的临时测试。')
            if row != expected:
                raise RuntimeError('Detailed test data did not match; refusing deletion')
        db.execute('DELETE FROM registrations WHERE name = ? AND affiliation = ? AND contact = ?', key)
    owner = database.stat()
    for suffix in ('-wal', '-shm'):
        item = Path(str(database) + suffix)
        if item.exists():
            os.chown(item, owner.st_uid, owner.st_gid)
            os.chmod(item, 0o600)
finally:
    subprocess.run(['systemctl', 'start', 'kiro-hackathon.service'], check=True, capture_output=True)
deadline = time.monotonic() + 10
while True:
    try:
        with urlopen('http://127.0.0.1:8826/api/status', timeout=1) as response:
            if response.status == 200:
                break
    except OSError:
        if time.monotonic() >= deadline:
            raise
        time.sleep(.2)
print('Synthetic test registration removed; service restarted and ready.')
