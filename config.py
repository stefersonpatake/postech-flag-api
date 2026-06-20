import json
import os

from dotenv import load_dotenv
import boto3
from botocore.exceptions import ClientError

SECRET_NAME = "postgres-flagapi"
REGION_NAME = "us-east-1"

# Mapeia chaves do segredo da AWS -> nomes de variáveis usadas pela app.
SECRET_KEY_MAP = {
    "host": "DB_HOST",
    "username": "DB_USER",
    "password": "DB_PASSWORD",
    "port": "DB_PORT",
}


def _load_secret_into_env():
    """Busca o segredo no Secrets Manager e injeta os valores em os.environ."""
    client = boto3.session.Session().client(
        service_name="secretsmanager",
        region_name=REGION_NAME,
    )

    try:
        response = client.get_secret_value(SecretId=SECRET_NAME)
    except ClientError as e:
        raise RuntimeError(f"Falha ao buscar o segredo '{SECRET_NAME}': {e}") from e

    secret = json.loads(response["SecretString"])

    for secret_key, env_var in SECRET_KEY_MAP.items():
        value = secret.get(secret_key)
        if value is not None:
            os.environ[env_var] = str(value)

    # Nome do banco: dbname tem prioridade sobre dbInstanceIdentifier.
    db_name = secret.get("dbname") or secret.get("dbInstanceIdentifier")
    if db_name:
        os.environ["DB_NAME"] = str(db_name)


def load_config():
    """
    Popula o ambiente a partir de UMA fonte:
      - sempre carrega o .env primeiro (defaults / dev local);
      - se APP_ENV != 'local', busca o Secrets Manager e sobrescreve.
    Depois disso o resto do código usa só os.getenv(...).
    """
    # override=False: variáveis que já existem no ambiente real têm prioridade.
    load_dotenv(override=False)

    if os.getenv("APP_ENV", "local").lower() != "local":
        _load_secret_into_env()