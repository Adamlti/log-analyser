import logging
import re
from datetime import datetime
from ipaddress import ip_address
from pathlib import Path


logger = logging.getLogger(__name__)


def extract(row):
    """Séparer les champs d'une ligne de log et garder son message complet."""
    record = None
    fields = None
    match = None
    pattern = re.compile(
        r"^(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
        r"(?P<day>0?[1-9]|[12]\d|3[01])\s+"
        r"(?P<time>(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d)\s+"
        r"(?P<host>\S+)\s+(?P<service>[^\s:\[]+)"
        r"(?:\[(?P<pid>\d+)\])?:\s*(?P<message>.*)$"
    )

    if isinstance(row, str):
        match = re.search(pattern, row.rstrip("\r\n"))
        if match:
            try:
                fields = match.groupdict()
                fields["day"] = int(fields["day"])
                fields["pid"] = int(fields["pid"]) if fields["pid"] else None
                record = fields
            except ValueError:
                logger.warning("Champs numériques invalides : %r", row)
        else:
            logger.warning("Ligne de log non reconnue : %r", row)
    else:
        logger.warning("Une ligne de texte est attendue : %r", row)

    return record


def clean_date(month, day, time, year):
    """Construire une date valide avec l'année fournie par l'appelant."""
    date = None
    hour = 0
    minute = 0
    second = 0
    months = {
        "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
        "May": 5, "Jun": 6, "Jul": 7, "Aug": 8,
        "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
    }

    try:
        hour, minute, second = map(int, time.split(":"))
        date = datetime(year, months[month], int(day), hour, minute, second)
    except (AttributeError, KeyError, TypeError, ValueError):
        logger.warning(
            "Date invalide : année=%r, mois=%r, jour=%r, heure=%r",
            year, month, day, time,
        )

    return date


def transform(record, year):
    """Préparer une tentative SSH pour la future table connection."""
    connection = None
    message = None
    match = None
    fields = None
    address = None
    port = None
    date = None
    count = 1
    repeated = None
    repeated_pattern = re.compile(
        r"^message repeated (?P<count>\d+) times: \[\s*(?P<message>.*)\]$"
    )
    pattern = re.compile(
        r"^(?P<result>Failed|Accepted)\s+(?P<method>\S+)\s+for\s+"
        r"(?P<invalid_user>invalid user\s+)?(?P<user>.*?)\s+"
        r"from\s+(?P<ip>\S+)\s+port\s+(?P<port>\d+)(?:\s+.*)?$"
    )

    if not isinstance(record, dict):
        logger.warning("Un dictionnaire extrait est attendu : %r", record)
    elif record.get("service") == "sshd":
        message = record.get("message")
        if not isinstance(message, str):
            logger.warning("Message SSH absent ou invalide : %r", record)
        else:
            repeated = re.search(repeated_pattern, message)
            if repeated:
                count = int(repeated["count"])
                message = repeated["message"].strip()
            match = re.search(pattern, message)
            if match is None and message.startswith(("Failed ", "Accepted ")):
                logger.warning("Tentative SSH non reconnue : %r", message)

    if match is not None:
        fields = match.groupdict()
        try:
            address = ip_address(fields["ip"])
            port = int(fields["port"])
            if not 1 <= port <= 65535:
                raise ValueError("Le port doit être entre 1 et 65535")
        except ValueError:
            logger.warning("IP ou port invalide : %r", message)
            fields = None

    if fields is not None:
        date = clean_date(
            record.get("month"), record.get("day"), record.get("time"), year,
        )
        if date is not None:
            connection = {
                **record,
                "status": "failed" if fields["result"] == "Failed" else "success",
                "date": date,
                "user": fields["user"].strip(),
                "country": None,
                "ip": str(address),
                "port": port,
                "method": fields["method"],
                "invalid_user": fields["invalid_user"] is not None,
                "count": count,
            }

    return connection


if __name__ == "__main__":
    test_row = (
        "May 24 00:28:00 ns sshd[1351222]: Failed password for invalid user "
        "test from 45.156.87.204 port 41740 ssh2"
    )
    test_month = "May"
    test_day = 24
    test_time = "00:28:00"
    test_year = 2026  # Année d'exemple, absente des fichiers auth.log.
    test_record = {
        "month": "May", "day": 24, "time": "00:28:00", "host": "ns",
        "service": "sshd", "pid": 1351222,
        "message": "Failed password for invalid user test from 45.156.87.204 port 41740 ssh2",
    }
    extracted = None
    cleaned_date = None
    connection = None
    log_directory = Path(__file__).resolve().parents[1] / "logs"
    log_file = log_directory / "extract_transform.log"

    log_directory.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
    )

    extracted = extract(test_row)
    cleaned_date = clean_date(test_month, test_day, test_time, test_year)
    connection = transform(test_record, test_year)

    assert extracted is not None and extracted["pid"] == 1351222
    assert cleaned_date == datetime(2026, 5, 24, 0, 28, 0)
    assert connection is not None and connection["invalid_user"] is True
    print("Extraction :", extracted)
    print("Date nettoyée :", cleaned_date)
    print("Connexion :", connection)
