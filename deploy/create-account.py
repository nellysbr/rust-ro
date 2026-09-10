#!/usr/bin/env python3
"""Create a game account using local PostgreSQL; never accepts passwords in argv."""
import getpass
import re
import subprocess
import sys

if len(sys.argv) != 2 or not re.fullmatch(r'[A-Za-z0-9_-]{1,23}', sys.argv[1]):
    raise SystemExit('Uso: sudo python3 deploy/create-account.py <nome de login>')
username = sys.argv[1]
password = getpass.getpass('Senha do jogo (max. 23 caracteres ASCII): ')
if not password or len(password) > 23 or not password.isascii() or any(ord(c) < 32 for c in password):
    raise SystemExit('Senha invalida')
if getpass.getpass('Confirme a senha: ') != password:
    raise SystemExit('Senhas diferentes')
quoted = password.replace("'", "''")
query = f"""BEGIN;
LOCK TABLE ragnarok.login IN EXCLUSIVE MODE;
INSERT INTO ragnarok.login (account_id, userid, user_pass, sex, email, group_id, character_slots)
SELECT GREATEST(COALESCE(MAX(account_id), 1999999) + 1, 2000000), '{username}', '{quoted}', 'M', '', 0, 9 FROM ragnarok.login;
COMMIT;
"""
subprocess.run(['runuser', '-u', 'postgres', '--', 'psql', '-X', '-v', 'ON_ERROR_STOP=1', '-d', 'ragnarok'],
               input=query, text=True, check=True, stdout=subprocess.DEVNULL)
print('Conta criada:', username)
