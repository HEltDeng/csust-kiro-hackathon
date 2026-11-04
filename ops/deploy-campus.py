#!/usr/bin/env python3
"""Deploy one K Campus application, retaining legacy site files and registrations."""
from contextlib import closing
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

stage = Path(sys.argv[1]).resolve()
web_root = Path('/var/www/mychangliapp')
target = web_root / 'events/kiro-2026'
app = Path('/opt/kiro-hackathon')
nginx = Path('/etc/nginx/sites-available/mychangli-website')
unit = Path('/etc/systemd/system/kiro-hackathon.service')
database = Path('/var/lib/kiro-hackathon/registrations.sqlite3')
backup = app / 'backups' / ('campus-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
new_dir = target.parent / ('.k-campus-new-' + str(os.getpid()))
old_dir = target.parent / ('.k-campus-old-' + str(os.getpid()))
bootstrap = database.parent / 'admin-bootstrap.json'
baseline = json.loads((stage / 'baseline.json').read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def verify_baseline():
    files = {'nginx': nginx, 'service': unit, 'server': app / 'server.py', 'management': app / 'management.py', 'legacy_index': web_root / 'index.html'}
    for key, path in files.items():
        if digest(path) != baseline['files'][key]:
            raise RuntimeError('Existing ' + key + ' changed; refusing to overwrite')
    actual = {str(p.relative_to(target)): digest(p) for p in target.rglob('*') if p.is_file()}
    if actual != baseline['event_files']:
        raise RuntimeError('Existing event site changed; refusing to overwrite')


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError('Command failed: ' + ' '.join(args) + ' ' + result.stderr[-1000:])


def ready():
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        try:
            with urlopen('http://127.0.0.1:8826/api/status', timeout=1) as response:
                if response.status == 200 and json.loads(response.read())['registration_open']:
                    with urlopen('http://127.0.0.1:8826/api/announcements', timeout=1) as public:
                        if public.status == 200:
                            return
        except (OSError, URLError, KeyError, ValueError):
            time.sleep(.2)
    raise RuntimeError('New service did not become ready')


def replace_file(source, destination, mode=0o644):
    tmp = destination.with_name('.' + destination.name + '.campus-' + str(os.getpid()))
    shutil.copyfile(source, tmp)
    os.chmod(tmp, mode)
    os.replace(tmp, destination)


def nginx_config():
    config = nginx.read_text()
    marker = '    # k-campus-home-and-admin\n'
    if marker not in config:
        anchor = '    # kiro-hackathon-2026\n'
        if config.count(anchor) != 1:
            raise RuntimeError('Expected event nginx configuration was not found')
        extra = '''    # k-campus-home-and-admin
    location = / { return 302 /events/kiro-2026/; }
    location = /index.html { return 302 /events/kiro-2026/; }
    location ^~ /events/kiro-2026/admin/ {
        try_files $uri $uri/ =404;
        add_header Cache-Control "no-store" always;
        add_header X-Frame-Options "DENY" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Content-Security-Policy "default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'" always;
        add_header X-Robots-Tag "noindex, nofollow" always;
    }

'''
        config = config.replace(anchor, extra + anchor, 1)
    start = config.index('    # kiro-hackathon-2026\n')
    end = config.index('\n    location / {', start)
    part = config[start:end]
    part = part.replace('client_max_body_size 8k;', 'client_max_body_size 32k;')
    part = part.replace('proxy_read_timeout 15s;', 'proxy_read_timeout 60s;')
    return config[:start] + part + config[end:]


def has_admin():
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='admin_account'").fetchone()
        return bool(table and db.execute('SELECT 1 FROM admin_account WHERE id=1').fetchone())


if os.geteuid() != 0 or not database.is_file() or not target.is_dir() or not nginx.is_file():
    raise SystemExit('Existing event application and authorized server access are required')
if any(path.exists() for path in (backup, new_dir, old_dir)):
    raise SystemExit('A staging or backup path already exists')
for required in ('dist/index.html', 'dist/register.html', 'dist/admin/index.html', 'dist/admin/admin.css', 'dist/admin/admin.js', 'dist/assets/kiro-icon.svg', 'dist/assets/kiro-ghost.svg', 'server/server.py', 'server/management.py'):
    if not (stage / required).is_file():
        raise SystemExit('Missing staged file: ' + required)
for source in ('server/server.py', 'server/management.py'):
    compile((stage / source).read_text(), source, 'exec')
verify_baseline()
run('systemctl', 'is-active', 'kiro-hackathon.service')
needs_admin = not has_admin()
if needs_admin and (not (stage / 'admin-bootstrap.json').is_file() or bootstrap.exists()):
    raise SystemExit('Initial administrator credentials are missing or already being provisioned')
updated_nginx = nginx_config()
backup.mkdir(mode=0o700)
shutil.copy2(nginx, backup / 'nginx.conf')
shutil.copy2(unit, backup / 'service.conf')
shutil.copy2(app / 'server.py', backup / 'server.py')
if (app / 'management.py').exists():
    shutil.copy2(app / 'management.py', backup / 'management.py')
shutil.copy2(web_root / 'index.html', backup / 'legacy-index.html')
shutil.copytree(target, backup / 'website')
with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as src:
    with closing(sqlite3.connect(str(backup / 'registrations.sqlite3'))) as dst:
        src.backup(dst)
os.chmod(backup / 'registrations.sqlite3', 0o600)
shutil.copytree(stage / 'dist', new_dir)
owner = web_root.stat()
for path in [new_dir] + list(new_dir.rglob('*')):
    os.chown(path, owner.st_uid, owner.st_gid)
    os.chmod(path, 0o755 if path.is_dir() else 0o644)
verify_baseline()

server_changed = False
website_swapped = False
nginx_changed = False
try:
    if needs_admin:
        account = json.loads((stage / 'admin-bootstrap.json').read_text())
        if set(account) != {'username', 'salt', 'password_hash'}:
            raise RuntimeError('Invalid administrator bootstrap')
        replace_file(stage / 'admin-bootstrap.json', bootstrap, 0o600)
        db_owner = database.stat()
        os.chown(bootstrap, db_owner.st_uid, db_owner.st_gid)
    replace_file(stage / 'server/management.py', app / 'management.py')
    replace_file(stage / 'server/server.py', app / 'server.py', 0o755)
    server_changed = True
    run('systemctl', 'restart', 'kiro-hackathon.service')
    ready()
    if needs_admin and not has_admin():
        raise RuntimeError('Administrator account was not initialized')
    os.rename(target, old_dir)
    os.rename(new_dir, target)
    website_swapped = True
    nginx_temp = stage / 'nginx.conf'
    nginx_temp.write_text(updated_nginx)
    replace_file(nginx_temp, nginx)
    nginx_changed = True
    run('/usr/sbin/nginx', '-t', '-q')
    run('systemctl', 'reload', 'nginx')
    if digest(web_root / 'index.html') != baseline['files']['legacy_index']:
        raise RuntimeError('Legacy homepage unexpectedly changed')
    shutil.rmtree(old_dir)
    print('Campus site and management service deployed; old homepage code and registration data retained.')
except Exception:
    if nginx_changed:
        replace_file(backup / 'nginx.conf', nginx)
        subprocess.run(['/usr/sbin/nginx', '-t', '-q'], capture_output=True)
        subprocess.run(['systemctl', 'reload', 'nginx'], capture_output=True)
    if website_swapped and old_dir.exists():
        os.rename(target, new_dir)
        os.rename(old_dir, target)
    elif old_dir.exists() and not target.exists():
        os.rename(old_dir, target)
    if server_changed:
        replace_file(backup / 'server.py', app / 'server.py', 0o755)
        if (backup / 'management.py').exists():
            replace_file(backup / 'management.py', app / 'management.py')
        elif (app / 'management.py').exists():
            (app / 'management.py').unlink()
        subprocess.run(['systemctl', 'restart', 'kiro-hackathon.service'], capture_output=True)
    if bootstrap.exists() and needs_admin:
        bootstrap.unlink()
    if new_dir.exists():
        shutil.rmtree(new_dir)
    raise
