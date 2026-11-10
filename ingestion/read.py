import gzip
import logging
import os
import os.path as pt
import zlib
from pathlib import Path

logger = logging.getLogger(__name__)

def ingest(path: str):
    """Lire tous les fichiers du dossier, y compris les archives gzip."""
    rows = []
    files = []
    file = None
    file_path = None
    openner = None
    f = None
    file_rows = []
    files_read = 0

    if isinstance(path, (str, os.PathLike)):
        try:
            files = sorted(os.listdir(path))
        except (OSError, TypeError):
            logger.exception("Lecture du dossier impossible : %s", path)
    else:
        logger.error("Un chemin de dossier est attendu : %r", path)

    for file in files:
        file_path = pt.join(path, file)
        if pt.isfile(file_path):
            try:
                openner = (
                    gzip.open(file_path, mode="rt", encoding="utf-8")
                    if file.endswith(".gz")
                    else open(file_path, encoding="utf-8")
                )
                with openner as f:
                    file_rows = f.readlines()
                rows.extend(file_rows)
                files_read += 1
                logger.info("Fichier lu : %s (%d lignes)", file, len(file_rows))
            except (OSError, EOFError, UnicodeError, zlib.error):
                logger.exception("Lecture du fichier impossible : %s", file_path)

    logger.info("Lecture terminée : %d fichiers, %d lignes", files_read, len(rows))
    return rows

if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / "data"
    data = []
    log_directory = Path(__file__).resolve().parents[1] / "logs"
    log_file = log_directory / "ingestion.log"

    log_directory.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
    )

    data = ingest(path)
    print("Nombre de lignes lues :", len(data))
    if data:
        print(data[:10])
