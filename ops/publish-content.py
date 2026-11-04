#!/usr/bin/env python3
"""Publish the event pages without altering the registration service or data."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

stage = Path(sys.argv[1]).resolve()
web_root = Path('/var/www/mychangliapp')
target = web_root / 'events/kiro-2026'
backups = Path('/opt/kiro-hackathon/backups')
backup = backups / ('content-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
new_dir = target.parent / ('.kiro-content-new-' + str(os.getpid()))
old_dir = target.parent / ('.kiro-content-old-' + str(os.getpid()))
manifest = json.loads((stage / 'baseline.json').read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_current():
    actual = {str(p.relative_to(target)) for p in target.rglob('*') if p.is_file()}
    if actual != set(manifest):
        raise RuntimeError('Published event file list changed; refusing to overwrite')
    for name, expected in manifest.items():
        if digest(target / name) != expected:
            raise RuntimeError('Published event file changed; refusing to overwrite: ' + name)


if os.geteuid() != 0 or not target.is_dir() or not backups.is_dir():
    raise SystemExit('Existing event site and authorized server access are required')
if any(path.exists() for path in (backup, new_dir, old_dir)):
    raise SystemExit('Update staging path already exists')
verify_current()
for required in ('index.html', 'register.html', 'styles.css', 'app.js', 'assets/campus-pixel-robot.png'):
    if not (stage / 'dist' / required).is_file():
        raise SystemExit('Missing staged website file: ' + required)
backup.mkdir(mode=0o700)
shutil.copytree(target, backup / 'website')
shutil.copytree(stage / 'dist', new_dir)
owner = web_root.stat()
for path in [new_dir] + list(new_dir.rglob('*')):
    os.chown(path, owner.st_uid, owner.st_gid)
    os.chmod(path, 0o755 if path.is_dir() else 0o644)
try:
    verify_current()
except Exception:
    shutil.rmtree(new_dir)
    raise
moved = False
published = False
try:
    os.rename(target, old_dir)
    moved = True
    os.rename(new_dir, target)
    published = True
except Exception:
    if published and target.exists():
        shutil.rmtree(target)
    if moved and old_dir.exists():
        os.rename(old_dir, target)
    if new_dir.exists():
        shutil.rmtree(new_dir)
    raise
try:
    shutil.rmtree(old_dir)
except OSError:
    print('Previous staging copy retained; backup is available.')
print('Updated event pages; registration service and data were left intact.')
