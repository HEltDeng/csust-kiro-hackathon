#!/usr/bin/env python3
"""Stage and publish the unified campus project using the authorized local helper."""
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys
import tarfile
import tempfile

repo = Path(__file__).resolve().parent.parent
project = repo.parent.parent
helper = '/Applications/MyChuannong Server Auth.app/Contents/MacOS/LocalServerAuth'
login_file = project / '管理工具' / 'K校园计划后台登录信息.txt'
sys.path.insert(0, str(repo / 'server'))
from management import password_hash


def run(args, **kwargs):
    result = subprocess.run(args, check=False, capture_output=True, **kwargs)
    if result.returncode:
        detail = result.stderr.decode('utf-8', 'replace')[-1200:]
        raise RuntimeError('Command failed: ' + args[0] + ' ' + detail)
    return result.stdout


def credential():
    login_file.parent.mkdir(parents=True, exist_ok=True)
    if not login_file.exists():
        password = secrets.token_urlsafe(24)
        content = ('K 校园计划管理后台\nhttps://mychangliapp.cn/events/kiro-2026/admin/\n账号：admin\n初始密码：' + password + '\n\n请妥善保管，登录后可在“账户安全”中修改密码。\n').encode('utf-8')
        fd = os.open(login_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as file:
            file.write(content)
    if login_file.stat().st_mode & 0o077:
        raise RuntimeError('Administrator login file has unsafe permissions')
    content = login_file.read_text(encoding='utf-8')
    found = re.search(r'^初始密码：([^\n]+)$', content, re.M)
    if not found:
        raise RuntimeError('Existing administrator login file has an unexpected format')
    salt, hashed = password_hash(found.group(1))
    return {'username':'admin', 'salt':salt, 'password_hash':hashed}


manifest_script = '''
import hashlib,json
from pathlib import Path
root=Path('/var/www/mychangliapp')
target=root/'events/kiro-2026'
app=Path('/opt/kiro-hackathon')
paths={'nginx':Path('/etc/nginx/sites-available/mychangli-website'),'service':Path('/etc/systemd/system/kiro-hackathon.service'),'server':app/'server.py','management':app/'management.py','legacy_index':root/'index.html'}
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
print(json.dumps({'files':{k:digest(v) for k,v in paths.items()},'event_files':{str(p.relative_to(target)):digest(p) for p in target.rglob('*') if p.is_file()}}))
'''

if run([helper, 'status']).decode().strip() != 'PRESENT_LOCAL_ONLY':
    raise SystemExit('本机服务器凭据不可用，请在授权应用中设置。')
credentials = credential()
stage = run(['ssh', '-o', 'BatchMode=yes', 'mychangli', 'mktemp -d /tmp/k-campus-XXXXXX']).decode().strip()
if not re.fullmatch(r'/tmp/k-campus-[A-Za-z0-9]{6}', stage):
    raise SystemExit('Unexpected remote staging path; refusing deployment')
try:
    baseline_raw = run(['ssh', '-o', 'BatchMode=yes', 'mychangli', 'python3 -c ' + shlex.quote(manifest_script)])
    baseline = json.loads(baseline_raw)
    with tempfile.TemporaryDirectory(prefix='k-campus-publish-') as temp:
        archive = Path(temp) / 'payload.tar'
        with tarfile.open(archive, 'w') as tar:
            tar.add(repo / 'dist', arcname='dist')
            for relative in ('server/server.py', 'server/management.py', 'ops/deploy-campus.py'):
                tar.add(repo / relative, arcname=relative)
            for name, content in (('baseline.json', baseline), ('admin-bootstrap.json', credentials)):
                data = json.dumps(content, ensure_ascii=False).encode()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o600
                tar.addfile(info, BytesIO(data))
        run(['scp', '-q', str(archive), 'mychangli:' + stage + '/payload.tar'])
    run(['ssh', '-o', 'BatchMode=yes', 'mychangli', 'tar -xf ' + shlex.quote(stage + '/payload.tar') + ' -C ' + shlex.quote(stage)])
    result = run([helper, 'run', '/usr/bin/python3', stage + '/ops/deploy-campus.py', stage])
    print(result.decode('utf-8', 'replace').strip())
    print('Administrator login information is stored locally in the project management tools folder.')
finally:
    subprocess.run(['ssh', '-o', 'BatchMode=yes', 'mychangli', 'rm -rf -- ' + shlex.quote(stage)], capture_output=True)
