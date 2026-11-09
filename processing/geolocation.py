import json
import logging
from ipaddress import ip_address
from pathlib import Path
from urllib import request as http
from urllib.error import HTTPError, URLError


logger = logging.getLogger(__name__)


def geo_location(ip):
    """Obtenir le pays d'une IP publique avec la bibliothèque standard."""
    location = None
    address = None
    is_public = False
    response = None
    payload = None
    url = None

    if isinstance(ip, str):
        try:
            address = ip_address(ip)
            is_public = address.is_global and not address.is_multicast
        except ValueError:
            logger.warning("Adresse IP invalide : %r", ip)
    else:
        logger.warning("Une adresse IP sous forme de texte est attendue : %r", ip)

    if is_public:
        url = "https://ipinfo.io/" + str(address) + "/json"
        try:
            with http.urlopen(url, timeout=10) as response:
                if response.status == 200:
                    payload = json.load(response)
                    if (
                        isinstance(payload, dict)
                        and isinstance(payload.get("country"), str)
                        and payload["country"]
                    ):
                        location = payload
                    else:
                        logger.warning("Réponse sans pays pour %s", address)
                else:
                    logger.error("Erreur HTTP %s pour %s", response.status, address)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            logger.exception("Échec de géolocalisation pour %s", address)
    elif address is not None:
        logger.info("IP non publique, géolocalisation ignorée : %s", address)

    return location


if __name__ == "__main__":
    from io import BytesIO
    from unittest.mock import patch

    # Réponse locale fixe : ce test ne contacte pas Internet.
    test_ip = "8.8.8.8"
    test_json = b'{"ip": "8.8.8.8", "country": "US"}'
    test_response = BytesIO(test_json)
    location = None
    log_directory = Path(__file__).resolve().parents[1] / "logs"
    log_file = log_directory / "geolocation.log"

    test_response.status = 200
    log_directory.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
    )

    with patch("urllib.request.urlopen", return_value=test_response):
        location = geo_location(test_ip)

    assert location is not None and location["country"] == "US"
    print("Géolocalisation simulée :", location)
