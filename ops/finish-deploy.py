#!/usr/bin/env python3
"""Finish an interrupted initial install without altering its data directory."""
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from urllib.request import urlopen

stage = Path(sys.argv[1]).resolve()
target = Path('/var/www/mychangliapp/events/kiro-2026')
app = Path('/opt/kiro-hackathon')
config = Path('/etc/nginx/sites-available/mychangli-website')
backup = app / 'backups/mychangli-website.before-event.conf'
marker = '# kiro-hackathon-2026'
needle = '    location / {\n'
block = '''    # kiro-hackathon-2026
    location ^~ /events/kiro-2026/api/ {
        client_max_body_size 8k;
        client_body_timeout 10s;
        proxy_pass http://127.0.0.1:8826/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 3s;
        proxy_read_timeout 15s;
    }

'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).digest()


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Failed: ' + ' '.join(args) + ': ' + result.stderr[-1000:])


def atomic_write(content, mode):
    fd, tmp = tempfile.mkstemp(prefix='.kiro-nginx-', dir=str(config.parent))
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(content)
        os.chmod(tmp, mode)
        os.replace(tmp, config)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


if os.geteuid() != 0:
    raise SystemExit('Run with the authorized local server helper')
for name in ('index.html', 'styles.css', 'app.js'):
    if digest(stage / 'dist' / name) != digest(target / name):
        raise SystemExit('Installed website file differs from staged source: ' + name)
if digest(stage / 'server/server.py') != digest(app / 'server.py'):
    raise SystemExit('Installed registration service differs from staged source')
run('systemctl', 'is-active', 'kiro-hackathon.service')
with urlopen('http://127.0.0.1:8826/api/status', timeout=5) as response:
    if response.status != 200 or b'"registration_open": true' not in response.read():
        raise SystemExit('Registration service is not ready')
original = config.read_text()
if original != backup.read_text() or original.count(needle) != 1 or marker in original:
    raise SystemExit('Website configuration changed; refusing to overwrite it')
mode = stat.S_IMODE(config.stat().st_mode)
updated = original.replace(needle, block + needle)
atomic_write(updated, mode)
try:
    run('/usr/sbin/nginx', '-t')
    run('systemctl', 'reload', 'nginx')
except Exception:
    if config.read_text() == updated:
        atomic_write(original, mode)
        subprocess.run(['/usr/sbin/nginx', '-t'], capture_output=True)
        subprocess.run(['systemctl', 'reload', 'nginx'], capture_output=True)
    raise
print('Event website and registration endpoint installed successfully.')
