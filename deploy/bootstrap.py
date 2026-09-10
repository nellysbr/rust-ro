#!/usr/bin/env python3
"""Run once as root on Debian 13; repeat runs preserve database and credentials."""
import grp
import ipaddress
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent

def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)

def sql(query, db='postgres', capture=False):
    return run('runuser', '-u', 'postgres', '--', 'psql', '-X', '-v', 'ON_ERROR_STOP=1', '-At', '-d', db,
               input=query, text=True, stdout=subprocess.PIPE if capture else subprocess.DEVNULL).stdout

def directory(path, mode, owner='root', group='root'):
    Path(path).mkdir(parents=True, exist_ok=True)
    os.chown(path, pwd.getpwnam(owner).pw_uid, grp.getgrnam(group).gr_gid)
    os.chmod(path, mode)

def install(source, destination, mode=0o644):
    shutil.copyfile(ROOT / 'deploy' / source, destination)
    os.chown(destination, 0, 0)
    os.chmod(destination, mode)

def clean_initial_dump(text):
    """Keep upstream static game data, excluding all sample players/accounts."""
    result = []
    skip = False
    for line in text.splitlines(keepends=True):
        if line.startswith('COPY '):
            table = line.split()[1]
            skip = table not in {'ragnarok.item_db', 'ragnarok.mob_db'}
        if not skip:
            result.append(line)
        if line.strip() == '\\.':
            skip = False
    return ''.join(result)

def main():
    if os.geteuid() != 0 or len(sys.argv) != 2:
        raise SystemExit('Uso: sudo python3 deploy/bootstrap.py <IPv4 publico>')
    address = str(ipaddress.IPv4Address(sys.argv[1]))
    pwd.getpwnam('ragzin')  # User running the Actions runner must already exist.
    try:
        pwd.getpwnam('ragzin-game')
    except KeyError:
        run('useradd', '--system', '--user-group', '--home-dir', '/nonexistent', '--no-create-home',
            '--shell', '/usr/sbin/nologin', 'ragzin-game')
    run('systemctl', 'enable', '--now', 'postgresql')
    directory('/etc/ragzin', 0o750, group='ragzin-game')
    directory('/srv/ragzin', 0o755)
    directory('/srv/ragzin/releases', 0o755)
    directory('/srv/ragzin/incoming', 0o700, owner='ragzin', group='ragzin')
    directory('/var/backups/ragzin', 0o700)
    env = Path('/etc/ragzin/server.env')
    if not env.exists():
        if sql("SELECT 1 FROM pg_roles WHERE rolname='ragnarok';", capture=True).strip():
            raise SystemExit('Role ragnarok ja existe, mas server.env nao. Configure a senha existente antes de continuar.')
        password = secrets.token_hex(32)
        fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write('DATABASE_PASSWORD=' + password + '\n')
    else:
        password = dict(line.split('=', 1) for line in env.read_text().splitlines() if '=' in line)['DATABASE_PASSWORD']
    if not sql("SELECT 1 FROM pg_roles WHERE rolname='ragnarok';", capture=True).strip():
        escaped = password.replace("'", "''")
        sql("CREATE ROLE ragnarok LOGIN PASSWORD '" + escaped + "';")
    if not sql("SELECT 1 FROM pg_database WHERE datname='ragnarok';", capture=True).strip():
        run('runuser', '-u', 'postgres', '--', 'createdb', '--owner=ragnarok', 'ragnarok')
    sql('ALTER ROLE ragnarok IN DATABASE ragnarok SET search_path = ragnarok, public;')
    schema = sql("SELECT 1 FROM pg_namespace WHERE nspname='ragnarok';", 'ragnarok', capture=True).strip()
    if not schema:
        table_count = sql("SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema');", 'ragnarok', capture=True).strip()
        if table_count != '0':
            raise SystemExit('Banco possui tabelas; bootstrap nao importa o dump em um banco existente.')
        sql(clean_initial_dump((ROOT / 'db/pg.sql').read_text()), 'ragnarok')
    sql((ROOT / 'db/alter_itemdb_add_script_compilation_result_column.sql').read_text(), 'ragnarok')
    if not sql("SELECT to_regclass('ragnarok.status_bonus');", 'ragnarok', capture=True).strip():
        sql((ROOT / 'db/add_status_bonus_table.sql').read_text(), 'ragnarok')
        sql('ALTER TABLE ragnarok.status_bonus OWNER TO ragnarok;', 'ragnarok')
    config_path = Path('/etc/ragzin/config.json')
    if not config_path.exists():
        config = json.loads((ROOT / 'config.template.json').read_text())
        config['server'].update(public_ip=address, port=6901, packetver=20120307,
                                trace_packet=False, enable_visual_debugger=False, accounts=[])
        config['proxy']['enabled'] = False
        config['database'].update(host='127.0.0.1', port=5432, db='ragnarok', username='ragnarok')
        config_path.write_text(json.dumps(config, indent=2) + '\n')
        os.chown(config_path, 0, grp.getgrnam('ragzin-game').gr_gid)
        config_path.chmod(0o640)
    install('ragzin-deploy', '/usr/local/sbin/ragzin-deploy', 0o755)
    install('ragzin-backup', '/usr/local/sbin/ragzin-backup', 0o755)
    for name in ['ragzin.service', 'ragzin-backup.service', 'ragzin-backup.timer']:
        install(name, '/etc/systemd/system/' + name)
    sudoers = Path('/etc/sudoers.d/ragzin-deploy')
    sudoers.write_text('ragzin ALL=(root) NOPASSWD: /usr/local/sbin/ragzin-deploy\n')
    sudoers.chmod(0o440)
    run('visudo', '-cf', str(sudoers))
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', '--now', 'ragzin-backup.timer')
    print('Bootstrap pronto. O jogo sera iniciado pelo primeiro deploy do Actions.')

if __name__ == '__main__':
    main()
