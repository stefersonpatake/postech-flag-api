import json
import os

import boto3
from botocore.exceptions import ClientError

SECRET_NAME = "postgres-flagapi"
REGION_NAME = "us-east-1"

""" Mapeia chaves do segredo da AWS -> nomes de variáveis usadas pela app. """
SECRET_KEY_MAP = {
    "host": "DB_HOST",
    "username": "DB_USER",
    "password": "DB_PASSWORD",
    "port": "DB_PORT",
}

def _load_secret_into_env():
    print("Buscando segredo no Secrets Manager...")

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


def load_aws_config():
    print("APP_ENV:", os.getenv("APP_ENV", "local"))
    print("DB_HOST:", os.getenv("DB_HOST"))
    
    """ Se APP_ENV != 'local' e !DB_HOST, busca no Secrets Manager e sobrescreve os.getenv(...). """
    """ Isso garante que irá executar apenas 1 vez no boot, e não a cada request. """
    if os.getenv("APP_ENV", "local").lower() != "local" and os.getenv("DB_HOST") is None:
        _load_secret_into_env()