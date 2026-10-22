"""从本地 Git 凭证执行服务器拉取，不在服务器保存 GitHub 凭证。"""
import json
import os
from pathlib import Path
import shlex
import subprocess


REMOTE_SCRIPT = r'''
import base64, json, os, pathlib, subprocess, sys
payload = json.load(sys.stdin)
root = pathlib.Path('/remedi')
if not (root / '.git').is_dir():
    raise SystemExit('/remedi is not a Git checkout')
dirty = subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=no'], text=True)
if dirty.strip():
    raise SystemExit('Server has tracked changes; preserve them before updating')
env = os.environ.copy()
env.update({
    'GIT_TERMINAL_PROMPT': '0',
    'GIT_CONFIG_COUNT': '2',
    'GIT_CONFIG_KEY_0': 'credential.helper',
    'GIT_CONFIG_VALUE_0': '',
    'GIT_CONFIG_KEY_1': 'http.https://github.com/.extraheader',
    'GIT_CONFIG_VALUE_1': 'AUTHORIZATION: basic ' + base64.b64encode(
        (payload['username'] + ':' + payload['password']).encode()).decode(),
})
subprocess.run(['git', '-C', str(root), 'pull', '--ff-only', 'origin', 'main'], env=env, check=True)
head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
if head != payload['expected']:
    raise SystemExit('Server commit differs from local commit; stop before deployment')
print('Verified server commit:', head)
'''


def main():
    root = Path(__file__).resolve().parents[1]
    origin = subprocess.check_output(['git', 'remote', 'get-url', 'origin'], cwd=root, text=True).strip()
    if origin != 'https://github.com/iLian-150/Remedi.git':
        raise SystemExit('Unexpected Git remote; stopping')
    credential = subprocess.run(
        ['git', 'credential', 'fill'], cwd=root, input=f'url={origin}\n\n',
        text=True, capture_output=True,
        env={**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never'},
    )
    values = dict(line.split('=', 1) for line in credential.stdout.splitlines() if '=' in line)
    if credential.returncode or not values.get('password'):
        raise SystemExit('No GitHub credential available in the local Git credential manager')
    payload = {key: values[key] for key in ('username', 'password')}
    payload['expected'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    command = [
        'ssh', '-i', str(Path.home() / '.ssh' / 'codex_deploy_ed25519'),
        '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
        'root@129.153.206.96', 'python3 -c ' + shlex.quote(REMOTE_SCRIPT),
    ]
    return subprocess.run(command, input=json.dumps(payload), text=True).returncode


if __name__ == '__main__':
    raise SystemExit(main())
