# Ragzin na AWS Lightsail

Servidor pre-re Rust + PostgreSQL nativo + systemd. Sem Docker Compose.
A branch principal atual e `master`; a pipeline tambem aceita `main`.

## Instancia

- Debian 13, x86_64, 2 vCPUs / 4 GB RAM como ponto de partida.
- IPv4 atual: `54.20.161.142`. Reserve um IP estatico no Lightsail para preservar o endereco ao recriar a instancia.
- Firewall Lightsail: SSH TCP 22 para administracao e TCP 6901 para o jogo.
- PostgreSQL TCP 5432 deve continuar em loopback; nao abrir no Lightsail.
- O usuario Linux `ragzin` executa o runner. O jogo roda como `ragzin-game`, usuario de sistema sem shell e sem sudo/docker.

## Recriar o ambiente

Instale PostgreSQL, Python 3, git e sudo pelos pacotes do Debian. Crie o usuario `ragzin` antes do bootstrap.
Como administrador:

```bash
git clone --depth 1 https://github.com/nellysbr/rust-ro.git
cd rust-ro
sudo python3 deploy/bootstrap.py SEU_IPV4_PUBLICO
```

O bootstrap gera uma senha aleatoria do banco em `/etc/ragzin/server.env` (root, 600), cria o role e banco `ragnarok`, configura o `search_path` e importa os dados estaticos de itens/monstros. Contas e personagens de exemplo do upstream nao sao importados. O dump inicial so e importado se o schema nao existe e o banco nao possui tabelas; nunca e executado em deploys.

Reexecutar preserva configuracao, senha e banco existentes. As duas extensoes de schema exigidas pelo codigo sao verificadas no bootstrap. Mudancas futuras de schema precisam de migracao revisada e backup: a pipeline nao aplica arquivos SQL automaticamente.

Configuracao persistente: `/etc/ragzin/config.json`. Campos relevantes:

```json
{
  "server": {"public_ip": "54.20.161.142", "port": 6901, "packetver": 20120307},
  "proxy": {"enabled": false},
  "database": {"host": "127.0.0.1", "port": 5432, "db": "ragnarok", "username": "ragnarok"}
}
```

Esse fragmento mostra apenas os campos alterados; o bootstrap gera o arquivo completo usando `config.template.json`.

## GitHub Actions

Em `nellysbr/rust-ro` → Settings → Actions → Runners, adicione um runner Linux x64 **somente para este repositorio**, como usuario Linux `ragzin`. Adicione a label **`ragzin`** alem das labels automaticas `self-hosted`, `Linux`, `X64`. Use o token temporario fornecido pelo GitHub apenas durante o registro; nao coloque o token no repo.

Na pasta do runner, apos o registro:

```bash
sudo ./svc.sh install ragzin
sudo ./svc.sh start
```

**Secrets exigidos: nenhum. Variables exigidas: nenhuma.** O runner esta no proprio host, e a senha do banco permanece nele. Nao e necessario cadastrar a chave PEM, credenciais AWS ou a senha do usuario Linux no GitHub.

A pipeline:

1. Executa build `--locked --release` e testes em `ubuntu-24.04` hospedado pelo GitHub, com a toolchain fixada no repo.
2. Empacota binario, configuracoes estaticas e identificacao do commit.
3. Somente em push de `master`/`main` ou execucao manual nessas branches, baixa o artefato no runner `ragzin`.
4. O instalador local valida o arquivo, para o jogo com SIGINT (salva personagens pelo fluxo existente), faz backup do PostgreSQL, troca a release e inicia o servico.
5. Se a nova release nao ficar saudavel, volta ao binario anterior e informa falha no Actions.

PRs usam apenas runner hospedado pelo GitHub. Como o repositorio e publico, mantenha Settings → Actions → General → Approval for running fork pull request workflows em **Require approval for all external contributors**; revise alteracoes de workflow antes de aprovar execucoes externas. Deploys sao serializados e nao cancelam um reinicio em andamento. O instalador privilegiado pertence a root; a pipeline nao o substitui. Para atualizar o instalador ou as units, um administrador deve revisar as mudancas e reexecutar o bootstrap.

Um deploy desconecta jogadores por alguns segundos; nao e atualizacao sem interrupcao. Evite fazer push durante uma sessao importante. O teste de prontidao verifica processo e porta; a validacao completa de jogo depende do cliente.

## Contas e cliente

Crie uma conta por jogador (contas do jogo sao diferentes de usuarios Linux):

```bash
sudo python3 deploy/create-account.py ragzin
sudo python3 deploy/create-account.py amigo
```

As senhas sao solicitadas sem eco e nao entram no historico. O protocolo/upstream armazena a senha do jogo em texto no banco; use senhas exclusivas para este ambiente de estudo.

No `config.json` local do cliente, preserve os demais campos e configure:

```json
"login_servers": [
  {"name": "Ragzin", "host": "54.20.161.142", "port": 6901, "packetver": 20120307}
]
```

O servidor unificado anuncia o mesmo IPv4 e porta nas transicoes login → personagens → mapa. `proxy.enabled=false` autentica todas as contas locais sem encaminhar para rAthena/Hercules.

## Operacao, backup e recuperacao

```bash
sudo systemctl status ragzin
sudo journalctl -u ragzin -n 100 --no-pager
sudo systemctl restart ragzin
sudo /usr/local/sbin/ragzin-backup
sudo systemctl list-timers ragzin-backup.timer
cat /srv/ragzin/current/REVISION
```

Backups diarios as 06:00 UTC, com retencao de 14 dias em `/var/backups/ragzin/`. Tambem ha backup antes de cada deploy. Releases ficam em `/srv/ragzin/releases/<SHA>`. Artefatos ficam no GitHub por 14 dias; o codigo no Git permite reconstruir depois desse prazo.

Antes de destruir a instancia, copie para um lugar privado **fora da instancia**:

- Um backup `.dump` recente de `/var/backups/ragzin/`.
- `/etc/ragzin/config.json` e `/etc/ragzin/server.env`.
- O SHA de `/srv/ragzin/current/REVISION`.

Backups apenas no disco da instancia nao sobrevivem a exclusao dela. Nunca commite dumps, senhas ou chaves PEM.

Para restaurar em uma instancia nova: execute o bootstrap, mantenha o jogo parado e importe o dump com o role ja criado:

```bash
sudo systemctl stop ragzin
sudo -u postgres pg_restore --exit-on-error --clean --if-exists --dbname=ragnarok /CAMINHO_LEGIVEL_PELO_POSTGRES/backup.dump
```

Atualize `server.public_ip` no config se o IP mudou, registre o novo runner e execute a pipeline manualmente na branch principal. Preserve/recupere as contas a partir do dump.

Para rollback manual do codigo, reexecute um workflow de commit anterior cujo artefato ainda exista ou envie novamente seu pacote e rode `sudo /usr/local/sbin/ragzin-deploy SHA`. O rollback de codigo nao restaura o banco automaticamente.

## Validacao local

```bash
cp config.template.json config.json
DATABASE_PASSWORD=test cargo test --locked --release --package server --bin server
cargo test --locked --release --package configuration
python3 -m unittest discover -s deploy/tests -v
cargo build --locked --release --package server --bin server
bash deploy/package.sh
```
