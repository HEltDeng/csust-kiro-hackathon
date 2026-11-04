#!/usr/bin/env python3
"""Update the event site while retaining registrations and a rollback copy."""
from contextlib import closing
from datetime import datetime
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

stage = Path(sys.argv[1]).resolve()
old_stage = Path(sys.argv[2]).resolve()
web_root = Path('/var/www/mychangliapp')
target = web_root / 'events/kiro-2026'
app = Path('/opt/kiro-hackathon')
database = Path('/var/lib/kiro-hackathon/registrations.sqlite3')
backup = app / 'backups' / ('update-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
new_dir = target.parent / ('.kiro-2026-new-' + str(os.getpid()))
old_dir = target.parent / ('.kiro-2026-old-' + str(os.getpid()))


def digest(path):
    return hashlib.sha256(path.read_bytes()).digest()


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Failed: ' + ' '.join(args) + ': ' + result.stderr[-1000:])


def wait_ready():
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with urlopen('http://127.0.0.1:8826/api/status', timeout=1) as response:
                if response.status == 200 and b'"registration_open": true' in response.read():
                    return
        except (OSError, URLError):
            time.sleep(.2)
    raise RuntimeError('Registration service failed readiness check')


def check_existing_site():
    present = {p.relative_to(target) for p in target.rglob('*') if p.is_file()}
    expected = {p.relative_to(old_stage / 'dist') for p in (old_stage / 'dist').rglob('*') if p.is_file()}
    if present != expected:
        raise RuntimeError('Existing site file list changed; refusing to overwrite')
    for name in expected:
        if digest(target / name) != digest(old_stage / 'dist' / name):
            raise RuntimeError('Existing site changed; refusing to overwrite: ' + str(name))


if os.geteuid() != 0 or not database.is_file():
    raise SystemExit('Authorized service and existing database are required')
if any(path.exists() for path in (backup, new_dir, old_dir)):
    raise SystemExit('Update staging path already exists')
check_existing_site()
if digest(app / 'server.py') != digest(old_stage / 'server/server.py'):
    raise SystemExit('Existing service changed; refusing to overwrite')
run('systemctl', 'is-active', 'kiro-hackathon.service')
backup.mkdir(mode=0o700)
shutil.copy2(app / 'server.py', backup / 'server.py')
shutil.copytree(target, backup / 'website')
shutil.copytree(stage / 'dist', new_dir)
owner = web_root.stat()
for path in [new_dir] + list(new_dir.rglob('*')):
    os.chown(path, owner.st_uid, owner.st_gid)
    os.chmod(path, 0o755 if path.is_dir() else 0o644)
stopped = False
server_changed = False
old_moved = False
new_live = False
try:
    run('systemctl', 'stop', 'kiro-hackathon.service')
    stopped = True
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(str(backup / 'registrations.sqlite3'))) as dst:
            src.backup(dst)
    os.chmod(backup / 'registrations.sqlite3', 0o600)
    owner_info = database.stat()
    for suffix in ('-wal', '-shm'):
        sidecar = Path(str(database) + suffix)
        if sidecar.exists():
            os.chown(sidecar, owner_info.st_uid, owner_info.st_gid)
            os.chmod(sidecar, 0o600)
    replacement = app / '.server.py.new'
    shutil.copyfile(stage / 'server/server.py', replacement)
    os.chmod(replacement, 0o755)
    os.replace(replacement, app / 'server.py')
    server_changed = True
    run('systemctl', 'start', 'kiro-hackathon.service')
    stopped = False
    wait_ready()
    check_existing_site()
    os.rename(target, old_dir)
    old_moved = True
    os.rename(new_dir, target)
    new_live = True
    old_moved = False
    try:
        shutil.rmtree(old_dir)
    except OSError:
        print('Previous website staging copy retained for later cleanup.')
    print('Updated website and registration service; existing registrations retained.')
except Exception:
    if new_live and target.exists():
        shutil.rmtree(target)
    if old_moved and old_dir.exists():
        os.rename(old_dir, target)
    if server_changed:
        shutil.copy2(backup / 'server.py', app / 'server.py')
        subprocess.run(['systemctl', 'restart', 'kiro-hackathon.service'], capture_output=True)
    elif stopped:
        subprocess.run(['systemctl', 'start', 'kiro-hackathon.service'], capture_output=True)
    if new_dir.exists():
        shutil.rmtree(new_dir)
    raise
