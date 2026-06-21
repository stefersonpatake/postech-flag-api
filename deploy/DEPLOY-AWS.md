# Deploy AWS — FlagAPI (produção)

Guia de deploy da FlagAPI em **EC2 (Amazon Linux, `ec2-user`)** sem Docker, com banco
**RDS PostgreSQL** e credenciais no **AWS Secrets Manager**. Inclui o histórico de
problemas enfrentados e como resolvê-los.

## Arquitetura

- **EC2**: roda a app via `systemd` (`flagapi.service`), com `gunicorn` numa virtualenv local.
- **`APP_ENV=PROD`** (setado pelo systemd) faz o `config.py` buscar as credenciais do banco
  no Secrets Manager (secret `postgres-flagapi`, região `us-east-1`) em vez de usar `.env`.
- **RDS PostgreSQL** (`flagapi`), acessível só dentro da VPC.

## Setup inicial (uma vez)

1. **Criar a venv e instalar dependências:**
   ```bash
   cd /home/ec2-user/postech-flag-api
   python3 -m venv venv
   ./venv/bin/pip install -r requirements.txt
   ```

2. **Anexar IAM Role à EC2** (necessária para o boto3 ler o Secrets Manager):
   - Console → EC2 → Instância → Actions → Security → *Modify IAM role* → **`LabRole`**.

3. **Criar role e database no RDS** (conectando como master `postgres` via psql):
   ```sql
   CREATE ROLE flagapi WITH LOGIN PASSWORD '<password do secret postgres-flagapi>';
   GRANT flagapi TO postgres;          -- necessário no PostgreSQL 16+ para o passo seguinte
   CREATE DATABASE flagapi OWNER flagapi;
   -- opcional, depois de criar: REVOKE flagapi FROM postgres;
   ```

4. **Instalar e habilitar o service:**
   ```bash
   sudo mv flagapi.service /etc/systemd/system/flagapi.service
   sudo systemctl daemon-reload
   sudo systemctl enable flagapi      # sobe no boot
   sudo systemctl start flagapi
   sudo systemctl status flagapi
   ```
   O service tem dois `ExecStartPre`: `pip install -r requirements.txt` e
   `flask --app app init-db` (cria a tabela `flags`, idempotente).

## Verificação

```bash
curl -s http://localhost:5000/health      # {"status":"ok"}
curl -s http://localhost:5000/flags       # []  (lista vazia)
```

## Problemas enfrentados e correções

| # | Sintoma | Causa | Correção |
|---|---------|-------|----------|
| 1 | `role "flagapi_user" does not exist` (local/Docker) | Volume Postgres antigo já inicializado com outras credenciais | `docker compose down -v` e subir de novo |
| 2 | `NoCredentialsError: Unable to locate credentials` | EC2 sem IAM Role; boto3 não acha credenciais | Anexar a `LabRole` à instância (no Learner Lab não dá pra criar policy/role: `iam:TagPolicy` negado) |
| 3 | `connection ... port 5432 failed: timeout expired` | NACL da subnet do RDS só liberava a 5432 para `10.0.1.0/24` e `10.0.2.0/24`; EC2 está em `10.0.3.0/24` | Adicionar no NACL do RDS: inbound `TCP 5432` e outbound `TCP 1024-65535` para `10.0.3.0/24` (NACL é *stateless*: entrada E resposta) |
| 4 | `password authentication failed for user "flagapi"` | Role `flagapi` e database `flagapi` não existiam (RDS master é `postgres`) | `CREATE ROLE flagapi` (senha = a do secret) + `CREATE DATABASE flagapi OWNER flagapi` |
| 5 | Tabela `flags` ausente | gunicorn via systemd pula o `entrypoint.sh` que fazia a init | `ExecStartPre=... flask --app app init-db` no service |

## Notas

- **Security Groups** (já configurados): SG do RDS libera inbound 5432 vindo do SG do EC2;
  egress do EC2 é all-traffic. O bloqueio do problema #3 era no **NACL**, não no SG.
- **Toda subnet nova** que precise acessar o RDS deve ser adicionada ao NACL do RDS (inbound 5432 + outbound efêmeras).
- A senha do role `flagapi` no RDS **deve ser idêntica** ao campo `password` do secret `postgres-flagapi`.
- `SECRET_NAME` (`postgres-flagapi`) e `REGION_NAME` (`us-east-1`) estão fixos no `config.py`.
- psql 15 contra server 18 dá erro cosmético no `\l`/`\du` (`column daticulocale does not exist`);
  use queries em `pg_database`/`pg_roles` se precisar inspecionar.
