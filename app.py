import os

from flask import Flask, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
from config import load_aws_config
from config import log

app = Flask(__name__)

load_aws_config()

DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
DB_PORT = os.getenv("DB_PORT", "5432")


def get_db_connection():
    conn = psycopg2.connect(
        host=DB_HOST,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        port=DB_PORT,
        connect_timeout=5,  # falha rápido em vez de travar o worker
    )
    return conn


def init_db():
    log("Tentando inicializar a tabela 'flags'...")
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS flags (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) UNIQUE NOT NULL,
                is_enabled BOOLEAN NOT NULL DEFAULT false,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.commit()
        cur.close()
        conn.close()
        log("Tabela 'flags' inicializada com sucesso.")
    except psycopg2.OperationalError as e:
        log(f"Erro de conexão ao inicializar o banco de dados: {e}")
    except Exception as e:
        log(f"Um erro inesperado ocorreu durante a inicialização do DB: {e}")


@app.cli.command("init-db")
def init_db_command():
    init_db()


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"}), 200


@app.route("/flags", methods=["POST"])
def create_flag():
    data = request.get_json()
    if not data or "name" not in data:
        return jsonify({"error": "O campo 'name' é obrigatório"}), 400

    name = data["name"]
    is_enabled = data.get("is_enabled", False)

    conn = cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO flags (name, is_enabled) VALUES (%s, %s)",
            (name, is_enabled),
        )
        conn.commit()
    except psycopg2.IntegrityError:
        return jsonify({"error": f"A flag '{name}' já existe"}), 409
    except Exception as e:
        return jsonify(
            {"error": "Erro interno no servidor ao criar a flag", "details": str(e)}
        ), 500
    finally:
        if cur is not None and not cur.closed:
            cur.close()
        if conn is not None and not conn.closed:
            conn.close()

    return jsonify({"message": f"Flag '{name}' criada com sucesso"}), 201


@app.route("/flags", methods=["GET"])
def get_flags():
    conn = cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT name, is_enabled FROM flags ORDER BY name")
        flags = cur.fetchall()
    except Exception as e:
        return jsonify(
            {"error": "Erro interno no servidor ao buscar as flags", "details": str(e)}
        ), 500
    finally:
        if cur is not None and not cur.closed:
            cur.close()
        if conn is not None and not conn.closed:
            conn.close()

    return jsonify(flags), 200


@app.route("/flags/<string:name>", methods=["GET"])
def get_flag_status(name):
    conn = cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT name, is_enabled FROM flags WHERE name = %s", (name,))
        flag = cur.fetchone()
    except Exception as e:
        return jsonify(
            {"error": "Erro interno no servidor ao buscar a flag", "details": str(e)}
        ), 500
    finally:
        if cur is not None and not cur.closed:
            cur.close()
        if conn is not None and not conn.closed:
            conn.close()

    if flag:
        return jsonify(flag), 200
    return jsonify({"error": "Flag não encontrada"}), 404


@app.route("/flags/<string:name>", methods=["PUT"])
def update_flag(name):
    data = request.get_json()
    if data is None or "is_enabled" not in data or not isinstance(data["is_enabled"], bool):
        return jsonify({"error": "O campo 'is_enabled' (booleano) é obrigatório"}), 400

    is_enabled = data["is_enabled"]

    conn = cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE flags SET is_enabled = %s WHERE name = %s", (is_enabled, name)
        )

        if cur.rowcount == 0:
            return jsonify({"error": "Flag não encontrada"}), 404

        conn.commit()
    except Exception as e:
        return jsonify(
            {"error": "Erro interno no servidor ao atualizar a flag", "details": str(e)}
        ), 500
    finally:
        if cur is not None and not cur.closed:
            cur.close()
        if conn is not None and not conn.closed:
            conn.close()

    return jsonify({"message": f"Flag '{name}' atualizada"}), 200


@app.route("/flags/<string:name>", methods=["DELETE"])
def delete_flag(name):
    conn = cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM flags WHERE name = %s", (name,))

        if cur.rowcount == 0:
            return jsonify({"error": "Flag não encontrada"}), 404

        conn.commit()
    except Exception as e:
        return jsonify(
            {"error": "Erro interno no servidor ao excluir a flag", "details": str(e)}
        ), 500
    finally:
        if cur is not None and not cur.closed:
            cur.close()
        if conn is not None and not conn.closed:
            conn.close()

    return jsonify({"message": f"Flag '{name}' excluída"}), 200


if __name__ == "__main__":
    log("Iniciando a aplicação...")
    app.run(host="0.0.0.0", port=5000)