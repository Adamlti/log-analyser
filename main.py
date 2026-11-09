import json
import logging
from collections import Counter
from pathlib import Path

from ingestion import read
from processing import extract_transform, geolocation
from serving import dashboard
from storage import stocking


if __name__ == "__main__":
    project_path = Path(__file__).resolve().parent
    config_path = project_path / "storage" / "database.local.json"
    year = 2026
    config = None
    stream = None
    db_connection = None
    rows = []
    row = None
    record = None
    connection = None
    location = None
    countries = {}
    existing_attempts = Counter()
    updated_ips = set()
    key = None
    cursor = None
    inserted = 0
    stored_connections = None
    failed_counts = None
    success_counts = None
    invalid_counts = None
    figure = None
    report_path = project_path / "reports" / "dashboard.png"
    log_directory = project_path / "logs"

    log_directory.mkdir(exist_ok=True)
    logging.basicConfig(
        filename=log_directory / "pipeline.log", encoding="utf-8",
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    with config_path.open(encoding="utf-8") as stream:
        config = json.load(stream)
    db_connection = stocking.connect_database(config)
    if db_connection is None:
        raise SystemExit("Connexion PostgreSQL impossible")

    try:
        if not stocking.create_table(db_connection):
            raise SystemExit("Création de la table connection impossible")
        stored_connections = stocking.read_connections(db_connection)
        if stored_connections is None:
            raise SystemExit("Lecture de la table connection impossible")
        for connection in stored_connections:
            key = (
                connection["status"], connection["date"], connection["user"],
                connection["ip"], connection["invalid_user"],
            )
            existing_attempts[key] += 1
            if connection["country"]:
                countries[connection["ip"]] = connection["country"]
        rows = read.ingest(project_path / "data")
        for row in rows:
            record = extract_transform.extract(row)
            if record is None:
                continue
            connection = extract_transform.transform(record, year)
            if connection is None:
                continue
            if connection["ip"] not in countries:
                location = geolocation.geo_location(connection["ip"])
                countries[connection["ip"]] = location["country"] if location else None
            connection["country"] = countries[connection["ip"]]
            if connection["country"] and connection["ip"] not in updated_ips:
                with db_connection:
                    with db_connection.cursor() as cursor:
                        cursor.execute(
                            "UPDATE connection SET country = %s WHERE ip = %s AND country IS NULL",
                            (connection["country"], connection["ip"]),
                        )
                updated_ips.add(connection["ip"])
            key = (
                connection["status"], connection["date"], connection["user"],
                connection["ip"], connection["invalid_user"],
            )
            if existing_attempts[key] > 0:
                existing_attempts[key] -= 1
                continue
            if stocking.insert_connection(db_connection, connection) is not None:
                inserted += 1
        print("Connexions enregistrées :", inserted)
        stored_connections = stocking.read_connections(db_connection)
        if stored_connections is None:
            raise SystemExit("Lecture de la table connection impossible")
        failed_counts = dashboard.count_failed_by_country(stored_connections)
        success_counts = dashboard.count_success_by_user(stored_connections)
        invalid_counts = dashboard.count_invalid_user_failures(stored_connections)
        figure = dashboard.create_dashboard(failed_counts, success_counts, invalid_counts)
        if figure is None:
            raise SystemExit("Création des graphiques impossible")
        report_path.parent.mkdir(exist_ok=True)
        figure.savefig(report_path, dpi=140)
        print("Échecs par pays :", failed_counts)
        print("Réussites par utilisateur :", success_counts)
        print("Échecs avec invalid user :", sum(invalid_counts.values()))
        print("Graphiques :", report_path)
    except (OSError, ValueError):
        logging.exception("Le pipeline n'a pas pu se terminer")
        raise
    finally:
        db_connection.close()
