"""Créer la table connection et stocker les tentatives d'authentification"""

import json
import logging
from datetime import datetime
from ipaddress import ip_address
from pathlib import Path

import psycopg2


logger = logging.getLogger(__name__)


def connect_database(config):
    """Ouvrir PostgreSQL avec les paramètres locaux fournis."""
    db_connection = None

    try:
        db_connection = psycopg2.connect(
            host=config["host"],
            port=config["port"],
            dbname=config["dbname"],
            user=config["user"],
            password=config["password"],
            connect_timeout=5,
        )
    except (psycopg2.Error, KeyError, TypeError, ValueError):
        logger.exception("Connexion PostgreSQL impossible")

    return db_connection


def create_table(db_connection):
    """Créer la table si elle n'existe pas, sans effacer les données."""
    created = False
    cursor = None
    query = """
        CREATE TABLE IF NOT EXISTS connection (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            status TEXT NOT NULL CHECK (status IN ('failed', 'success')),
            date TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            "user" TEXT NOT NULL,
            country TEXT,
            ip INET NOT NULL,
            invalid_user BOOLEAN NOT NULL DEFAULT FALSE,
            CHECK (NOT invalid_user OR status = 'failed')
        )
    """

    if db_connection is None or db_connection.closed:
        logger.error("Création impossible : connexion PostgreSQL fermée ou absente")
    else:
        try:
            with db_connection:
                with db_connection.cursor() as cursor:
                    cursor.execute(query)
            created = True
        except psycopg2.Error:
            logger.exception("Création de la table connection impossible")

    return created


def insert_connection(db_connection, record):
    """Valider et insérer une tentative, puis retourner son identifiant."""
    connection_id = None
    cursor = None
    parameters = None
    address = None
    invalid_user = False
    query = """
        INSERT INTO connection (status, date, "user", country, ip, invalid_user)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
    """

    try:
        if not isinstance(record, dict):
            raise TypeError("Un dictionnaire de connexion est attendu")
        if record["status"] not in ("failed", "success"):
            raise ValueError("Le statut doit être failed ou success")
        if not isinstance(record["date"], datetime):
            raise TypeError("La date doit être un objet datetime")
        if record["date"].tzinfo is not None:
            raise ValueError("Les logs sources utilisent des dates sans fuseau horaire")
        if not isinstance(record["user"], str):
            raise TypeError("L'utilisateur doit être une chaîne")
        if record.get("country") is not None and not isinstance(record["country"], str):
            raise TypeError("Le pays doit être une chaîne ou None")
        if not isinstance(record["ip"], str):
            raise TypeError("L'adresse IP doit être une chaîne")

        address = str(ip_address(record["ip"]))
        invalid_user = record.get("invalid_user", False)
        if not isinstance(invalid_user, bool):
            raise TypeError("invalid_user doit être un booléen")
        if invalid_user and record["status"] != "failed":
            raise ValueError("Un utilisateur invalide doit correspondre à un échec")

        parameters = (
            record["status"], record["date"], record["user"],
            record.get("country"), address, invalid_user,
        )
    except (KeyError, TypeError, ValueError):
        logger.exception("Données de connexion invalides")

    if parameters is not None:
        if db_connection is None or db_connection.closed:
            logger.error("Insertion impossible : connexion PostgreSQL fermée ou absente")
        else:
            try:
                with db_connection:
                    with db_connection.cursor() as cursor:
                        cursor.execute(query, parameters)
                        connection_id = cursor.fetchone()[0]
            except psycopg2.Error:
                connection_id = None
                logger.exception("Insertion dans connection impossible")

    return connection_id


def read_connections(db_connection):
    """Lire les tentatives pour le futur module serving."""
    connections = None
    cursor = None
    rows = None
    row = None
    columns = ("id", "status", "date", "user", "country", "ip", "invalid_user")
    query = """
        SELECT id, status, date, "user", country, host(ip), invalid_user
        FROM connection
        ORDER BY id
    """

    if db_connection is None or db_connection.closed:
        logger.error("Lecture impossible : connexion PostgreSQL fermée ou absente")
    else:
        try:
            with db_connection:
                with db_connection.cursor() as cursor:
                    cursor.execute(query)
                    rows = cursor.fetchall()
            connections = []
            for row in rows:
                connections.append(dict(zip(columns, row)))
        except psycopg2.Error:
            logger.exception("Lecture de la table connection impossible")

    return connections


if __name__ == "__main__":
    # Valeurs fixes pour tester le stockage, sans lancer les autres modules.
    config_file = Path(__file__).with_name("database.local.json")
    config = None
    db_connection = None
    cursor = None
    config_stream = None
    table_created = False
    failed_id = None
    success_id = None
    stored_connections = None
    test_failed = {
        "status": "failed",
        "date": datetime(2026, 5, 24, 0, 28),
        "user": "demo_invalid",
        "country": "FR",
        "ip": "198.51.100.20",
        "invalid_user": True,
    }
    test_success = {
        "status": "success",
        "date": datetime(2026, 5, 24, 0, 30),
        "user": "demo_admin",
        "country": None,
        "ip": "2001:db8::5",
        "invalid_user": False,
    }
    test_table_query = "CREATE TEMP TABLE connection (LIKE public.connection INCLUDING ALL)"
    log_directory = Path(__file__).resolve().parents[1] / "logs"
    log_file = log_directory / "stocking.log"

    log_directory.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
    )

    try:
        with config_file.open(encoding="utf-8") as config_stream:
            config = json.load(config_stream)
    except (OSError, ValueError):
        logger.exception("Configuration PostgreSQL locale absente ou invalide")
        raise SystemExit("Préparer storage/database.local.json avant le test")

    db_connection = connect_database(config)
    if db_connection is None:
        raise SystemExit("La connexion PostgreSQL a échoué ; consulter logs/stocking.log")

    try:
        table_created = create_table(db_connection)
        assert table_created, "La création de la table a échoué"

        # La table temporaire masque la table publique pendant les essais.
        with db_connection:
            with db_connection.cursor() as cursor:
                cursor.execute(test_table_query)

        failed_id = insert_connection(db_connection, test_failed)
        success_id = insert_connection(db_connection, test_success)
        stored_connections = read_connections(db_connection)

        assert failed_id is not None and success_id is not None
        assert stored_connections is not None and len(stored_connections) == 2
        assert stored_connections[0] == {"id": failed_id, **test_failed}
        assert stored_connections[1] == {"id": success_id, **test_success}
        print("Table publique connection créée ou vérifiée.")
        print("Connexions locales de test :", stored_connections)
        print("Les exemples temporaires disparaissent à la fermeture de la connexion.")
    finally:
        db_connection.close()
