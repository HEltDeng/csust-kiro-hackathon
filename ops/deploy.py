#!/usr/bin/env python3
"""Install the event under its own path on the existing server."""
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen

STAGE = Path(sys.argv[1]).resolve()
WEB_ROOT = Path('/var/www/mychangliapp')
EVENTS = WEB_ROOT / 'events'
TARGET = EVENTS / 'kiro-2026'
APP = Path('/opt/kiro-hackathon')
UNIT = Path('/etc/systemd/system/kiro-hackathon.service')
CONFIG = Path('/etc/nginx/sites-available/mychangli-website')
MARKER = '# kiro-hackathon-2026'
LOCATION = '''    # kiro-hackathon-2026
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


def run(*args):
    completed = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if completed.returncode:
        raise RuntimeError('Failed: ' + ' '.join(args) + ': ' + completed.stderr[-1000:])
    return completed.stdout


def replace_config(content, mode):
    fd, name = tempfile.mkstemp(prefix='.kiro-nginx-', dir=str(CONFIG.parent))
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(content)
        os.chmod(name, mode)
        os.replace(name, CONFIG)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Deployment requires the authorized local server helper')
    if any(path.exists() for path in (TARGET, APP, UNIT)):
        raise RuntimeError('An event path, service, or application already exists; refusing to overwrite')
    if not WEB_ROOT.is_dir() or not CONFIG.is_file():
        raise RuntimeError('Existing website configuration not found')
    for name in ('index.html', 'styles.css', 'app.js'):
        if not (STAGE / 'dist' / name).is_file():
            raise RuntimeError('Missing static site file: ' + name)
    for name in ('server.py', 'kiro-hackathon.service'):
        if not (STAGE / 'server' / name).is_file():
            raise RuntimeError('Missing service file: ' + name)
    original = CONFIG.read_text()
    needle = '    location / {\n'
    if MARKER in original or original.count(needle) != 1 or 'server_name mychangliapp.cn' not in original:
        raise RuntimeError('Existing website configuration differs from the expected structure')
    mode = stat.S_IMODE(CONFIG.stat().st_mode)
    created_events = False
    created_app = False
    created_target = False
    created_unit = False
    config_changed = False
    started = False
    updated = original.replace(needle, LOCATION + needle)
    try:
        APP.mkdir(mode=0o755)
        created_app = True
        (APP / 'backups').mkdir(mode=0o700)
        (APP / 'backups' / 'mychangli-website.before-event.conf').write_text(original)
        shutil.copyfile(STAGE / 'server' / 'server.py', APP / 'server.py')
        os.chmod(APP / 'server.py', 0o755)
        with UNIT.open('x') as target_unit:
            created_unit = True
            target_unit.write((STAGE / 'server' / 'kiro-hackathon.service').read_text())
        os.chmod(UNIT, 0o644)
        run('systemctl', 'daemon-reload')
        run('systemctl', 'enable', '--now', 'kiro-hackathon.service')
        started = True
        deadline = time.monotonic() + 10
        ready = False
        while time.monotonic() < deadline:
            try:
                with urlopen('http://127.0.0.1:8826/api/status', timeout=1) as response:
                    ready = response.status == 200 and b'"registration_open": true' in response.read()
                if ready:
                    break
            except (OSError, URLError):
                pass
            time.sleep(0.2)
        if not ready:
            raise RuntimeError('Registration service did not pass its readiness check')
        if not EVENTS.exists():
            EVENTS.mkdir(mode=0o755)
            os.chown(EVENTS, WEB_ROOT.stat().st_uid, WEB_ROOT.stat().st_gid)
            created_events = True
        if not EVENTS.is_dir() or TARGET.exists():
            raise RuntimeError('Event target changed during deployment')
        TARGET.mkdir(mode=0o755)
        created_target = True
        for name in ('index.html', 'styles.css', 'app.js'):
            shutil.copyfile(STAGE / 'dist' / name, TARGET / name)
        for item in [TARGET] + list(TARGET.iterdir()):
            os.chown(item, WEB_ROOT.stat().st_uid, WEB_ROOT.stat().st_gid)
            os.chmod(item, 0o755 if item.is_dir() else 0o644)
        if CONFIG.read_text() != original:
            raise RuntimeError('Existing website configuration changed during deployment')
        replace_config(updated, mode)
        config_changed = True
        run('/usr/sbin/nginx', '-t')
        run('systemctl', 'reload', 'nginx')
        print('Event site installed; registration service is active.')
    except Exception:
        if config_changed and CONFIG.read_text() == updated:
            replace_config(original, mode)
            subprocess.run(['/usr/sbin/nginx', '-t'], capture_output=True)
            subprocess.run(['systemctl', 'reload', 'nginx'], capture_output=True)
        if started:
            subprocess.run(['systemctl', 'disable', '--now', 'kiro-hackathon.service'], capture_output=True)
        if created_target and TARGET.exists():
            shutil.rmtree(TARGET)
        if created_events:
            try:
                EVENTS.rmdir()
            except OSError:
                pass
        if created_unit and UNIT.exists():
            UNIT.unlink()
            subprocess.run(['systemctl', 'daemon-reload'], capture_output=True)
        if created_app and APP.exists():
            shutil.rmtree(APP)
        # The database directory is retained if a service ever started.
        raise


if __name__ == '__main__':
    main()
