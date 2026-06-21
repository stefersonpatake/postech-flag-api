# Reconstruir o ambiente de produção na AWS — do zero

Checklist completo para recriar a infraestrutura da FlagAPI na AWS (AWS Academy
Learner Lab), na ordem correta de dependências:

> **VPC/Rede → RDS → Secret → EC2 → Deploy da app**

Os valores entre `< >` são placeholders. Os CIDRs/identificadores abaixo refletem o
ambiente atual (ajuste à vontade, mas mantenha a coerência entre as partes).

---

## 0. Pré-requisitos

- [ ] Acesso ao Learner Lab iniciado (credenciais AWS ativas).
- [ ] Região: **us-east-1** (o `config.py` tem `REGION_NAME = "us-east-1"` fixo).
- [ ] Par de chaves SSH (key pair) para acessar a EC2.
- [ ] A role **`LabRole`** existe (vem pronta no Learner Lab; não tente criar policy/role — `iam:TagPolicy` é negado).

---

## 1. Rede (VPC, subnets, IGW, rotas)

- [ ] **VPC**: criar com CIDR **`10.0.0.0/16`** (ex: `vpc-flagapi`).
- [ ] **Subnets** (mínimo 3; RDS exige 2 AZs diferentes no subnet group):
  - [ ] `app`  → **`10.0.3.0/24`**, AZ `us-east-1a` (onde fica a EC2)
  - [ ] `db-a` → **`10.0.1.0/24`**, AZ `us-east-1a` (onde fica o RDS)
  - [ ] `db-b` → **`10.0.2.0/24`**, AZ `us-east-1b` (segunda AZ p/ o subnet group do RDS)
- [ ] **Internet Gateway**: criar e anexar à VPC.
- [ ] **Route table (pública)** para a subnet `app`:
  - [ ] rota `0.0.0.0/0` → Internet Gateway
  - [ ] associar à subnet `app` (`10.0.3.0/24`)
  - [ ] a EC2 precisa de saída para internet/AWS APIs (Secrets Manager, pip). Dar **IP público** à EC2 ou usar NAT.
- [ ] As subnets do RDS podem ficar privadas (sem rota para IGW) — o RDS não precisa de internet.

### NACLs (firewall de subnet — *stateless*)
> Se usar os NACLs default (allow all), pule esta parte. Os NACLs customizados do
> ambiente atual filtram por porta/CIDR e foram a causa de um `timeout`. Se replicá-los:

- [ ] **NACL da subnet do RDS** — liberar a 5432 **a partir do CIDR da subnet da EC2**:
  - [ ] Inbound: `TCP 5432` ALLOW de `10.0.3.0/24`
  - [ ] Outbound: `TCP 1024-65535` (efêmeras) ALLOW para `10.0.3.0/24`
  - [ ] ⚠️ NACL é stateless: precisa liberar a entrada **e** a resposta separadamente.
- [ ] **NACL da subnet da EC2** — garantir:
  - [ ] Outbound: `TCP 5432` (ou faixa que o cubra) ALLOW para o CIDR do RDS
  - [ ] Inbound: `TCP 1024-65535` ALLOW (resposta do RDS)

### Security Groups
- [ ] **SG da EC2** (`flagapi-sg-ec2`):
  - [ ] Inbound: `TCP 22` (SSH) do seu IP; `TCP 5000` (app) conforme necessidade
  - [ ] Outbound: all traffic (default)
- [ ] **SG do RDS** (`flagapi-sg-rds`):
  - [ ] Inbound: `TCP 5432` com **origem = SG da EC2** (referência de SG, não IP)
  - [ ] ⚠️ Referência de SG só funciona se EC2 e RDS estiverem **na mesma VPC**.

---

## 2. RDS (PostgreSQL)

- [ ] **DB subnet group**: criar abrangendo as subnets `db-a` (10.0.1.0/24) e `db-b` (10.0.2.0/24).
- [ ] **Criar instância** PostgreSQL:
  - [ ] Identifier: **`flagapi`**
  - [ ] Master username: **`postgres`** + definir/anotar a master password
  - [ ] VPC: a criada acima; subnet group: o criado acima
  - [ ] **Public access: No**
  - [ ] VPC security group: **`flagapi-sg-rds`**
  - [ ] (opcional) Initial database name: deixar vazio — o database de app é criado no passo 4.
- [ ] Aguardar status **`available`** e anotar o **endpoint** (`flagapi.xxxx.us-east-1.rds.amazonaws.com`).

---

## 3. Secrets Manager

- [ ] Criar secret **`postgres-flagapi`** (região `us-east-1`), tipo "Other / plaintext", com o JSON:
  ```json
  {
    "username": "flagapi",
    "password": "<SENHA_FORTE_DO_APP>",
    "engine": "postgres",
    "host": "flagapi.xxxx.us-east-1.rds.amazonaws.com",
    "port": 5432,
    "dbInstanceIdentifier": "flagapi"
  }
  ```
  - [ ] `username` = **`flagapi`** (usuário de app, criado no passo 4 — NÃO é o master).
  - [ ] `host` = endpoint real do RDS.
  - [ ] Sem `dbname` → o `config.py` usa `dbInstanceIdentifier` (`flagapi`) como nome do database.
  - [ ] Guardar `<SENHA_FORTE_DO_APP>` — ela tem que ser idêntica à senha do role `flagapi`.

---

## 4. Criar role e database de app no RDS

A EC2 ainda não existe; faça de qualquer máquina com acesso de rede ao RDS (ou da própria
EC2 após o passo 5). Conecte como master `postgres` via psql:

```bash
export RDSHOST="flagapi.xxxx.us-east-1.rds.amazonaws.com"
psql "host=$RDSHOST port=5432 dbname=postgres user=postgres sslmode=require"
```
No prompt:
```sql
CREATE ROLE flagapi WITH LOGIN PASSWORD '<SENHA_FORTE_DO_APP>';  -- = password do secret
GRANT flagapi TO postgres;                 -- PostgreSQL 16+ exige p/ criar DB de outro owner
CREATE DATABASE flagapi OWNER flagapi;
-- REVOKE flagapi FROM postgres;           -- opcional, depois de criar o database
```
- [ ] Role `flagapi` criado com a senha do secret.
- [ ] Database `flagapi` criado (owner `flagapi`).
- [ ] A tabela `flags` NÃO precisa ser criada aqui — o deploy faz isso (passo 6).

> psql 15 contra server 18 dá erro cosmético em `\l`/`\du` (`column daticulocale does not exist`).
> Para inspecionar use `SELECT ... FROM pg_database / pg_roles`.

---

## 5. EC2

- [ ] **Lançar instância** Amazon Linux:
  - [ ] Subnet: `app` (`10.0.3.0/24`); **Auto-assign public IP: Enable**
  - [ ] Security group: **`flagapi-sg-ec2`**
  - [ ] Key pair: o seu
  - [ ] **IAM instance profile: `LabRole`** (Advanced details → IAM instance profile)
- [ ] Conectar via SSH e preparar o ambiente:
  ```bash
  sudo yum update -y
  sudo yum install -y git python3 postgresql15   # psql opcional p/ admin
  git clone <URL_DO_REPO> /home/ec2-user/postech-flag-api
  cd /home/ec2-user/postech-flag-api
  python3 -m venv venv
  ./venv/bin/pip install -r requirements.txt
  ```

### Validar credenciais e rede antes do deploy
- [ ] Secret acessível (IAM Role OK):
  ```bash
  aws secretsmanager get-secret-value --secret-id postgres-flagapi --region us-east-1 \
    --query SecretString --output text
  ```
- [ ] Porta do RDS alcançável (rede/SG/NACL OK):
  ```bash
  timeout 5 bash -c 'cat < /dev/null > /dev/tcp/<RDS_HOST>/5432' && echo ABERTO || echo BLOQUEADO
  ```

---

## 6. Deploy da app (systemd)

- [ ] Copiar/ajustar o unit `deploy/flagapi.service` para `/etc/systemd/system/flagapi.service`
      (confira `WorkingDirectory`, caminho da venv e `Environment=APP_ENV=PROD`):
  ```bash
  sudo cp deploy/flagapi.service /etc/systemd/system/flagapi.service
  sudo systemctl daemon-reload
  sudo systemctl enable flagapi     # sobe no boot
  sudo systemctl start flagapi
  sudo systemctl status flagapi
  ```
  O service roda dois `ExecStartPre`: `pip install -r requirements.txt` e
  `flask --app app init-db` (cria a tabela `flags`, idempotente).

---

## 7. Verificação final

```bash
curl -s http://localhost:5000/health     # {"status":"ok"}
curl -s http://localhost:5000/flags      # []  (lista vazia)

# smoke test de escrita
curl -s -X POST http://localhost:5000/flags \
  -H 'Content-Type: application/json' -d '{"name":"teste","is_enabled":true}'
curl -s http://localhost:5000/flags      # [{"name":"teste","is_enabled":true}]
```
- [ ] `/health` retorna ok
- [ ] `/flags` lista (vazia ou com dados)
- [ ] criar/ler flag funciona

Se algo falhar: `sudo journalctl -u flagapi -n 50 --no-pager`

---

## Ordem de dependências (resumo)

```
VPC + subnets + IGW + rotas
        │
        ├─ NACLs + Security Groups
        │
        ▼
RDS (subnet group → instância → SG do RDS)
        │
        ▼
Secret postgres-flagapi (precisa do endpoint do RDS)
        │
        ▼
Role + database flagapi no RDS (psql como postgres)
        │
        ▼
EC2 (subnet app + LabRole + SG) → clone + venv
        │
        ▼
systemd flagapi.service (ExecStartPre cria a tabela) → verificação
```

Para os problemas comuns e suas correções, ver [DEPLOY-AWS.md](DEPLOY-AWS.md).
