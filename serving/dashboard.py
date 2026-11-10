"""Compter les tentatives et créer les trois graphiques matplotlib demandés."""

import logging
from pathlib import Path
from textwrap import fill

from matplotlib import pyplot as plt
from matplotlib.ticker import MaxNLocator


logger = logging.getLogger(__name__)


def count_failed_by_country(connections):
    """Compter les échecs par pays, y compris les pays inconnus."""
    counts = None
    connection = None
    country = None

    if not isinstance(connections, (list, tuple)):
        logger.error("Une liste de connexions est attendue pour les échecs par pays")
    else:
        counts = {}
        for connection in connections:
            if not isinstance(connection, dict):
                logger.warning("Connexion non reconnue : %r", connection)
            elif connection.get("status") not in ("failed", "success"):
                logger.warning("Statut de connexion non reconnu : %r", connection.get("status"))
            elif connection["status"] == "failed":
                country = connection.get("country")
                if country is None or isinstance(country, str):
                    country = country.strip().upper() if country else ""
                    country = country or "Inconnu"
                    counts[country] = counts.get(country, 0) + 1
                else:
                    logger.warning("Pays non reconnu : %r", country)

    return counts


def count_success_by_user(connections):
    """Compter uniquement les authentifications réussies par utilisateur."""
    counts = None
    connection = None
    user = None

    if not isinstance(connections, (list, tuple)):
        logger.error("Une liste de connexions est attendue pour les réussites")
    else:
        counts = {}
        for connection in connections:
            if not isinstance(connection, dict):
                logger.warning("Connexion non reconnue : %r", connection)
            elif connection.get("status") not in ("failed", "success"):
                logger.warning("Statut de connexion non reconnu : %r", connection.get("status"))
            elif connection["status"] == "success":
                user = connection.get("user")
                if isinstance(user, str):
                    user = user or "(utilisateur vide)"
                    counts[user] = counts.get(user, 0) + 1
                else:
                    logger.warning("Utilisateur non reconnu : %r", user)

    return counts


def count_invalid_user_failures(connections):
    """Compter les échecs avec invalid_user=True, par nom d'utilisateur."""
    counts = None
    connection = None
    user = None
    invalid_user = None

    if not isinstance(connections, (list, tuple)):
        logger.error("Une liste de connexions est attendue pour les utilisateurs invalides")
    else:
        counts = {}
        for connection in connections:
            if not isinstance(connection, dict):
                logger.warning("Connexion non reconnue : %r", connection)
            elif connection.get("status") not in ("failed", "success"):
                logger.warning("Statut de connexion non reconnu : %r", connection.get("status"))
            elif connection["status"] == "failed":
                invalid_user = connection.get("invalid_user", False)
                if not isinstance(invalid_user, bool):
                    logger.warning("Marqueur invalid_user non reconnu : %r", invalid_user)
                elif invalid_user:
                    user = connection.get("user")
                    if isinstance(user, str):
                        user = user or "(utilisateur vide)"
                        counts[user] = counts.get(user, 0) + 1
                    else:
                        logger.warning("Utilisateur invalide non reconnu : %r", user)

    return counts


def create_dashboard(failed_by_country, success_by_user, invalid_user_failures):
    """Retourner les trois graphiques ; l'appelant déclenche l'affichage."""
    figure = None
    axes = None
    axis = None
    counts = None
    label = None
    count = None
    title = None
    color = None
    index = 0
    valid_data = True
    labels = []
    values = []
    bars = None
    other_total = 0
    max_categories = 0
    width = 0
    height = 6
    invalid_user_limit = 10
    panels = (
        (failed_by_country, "Échecs par pays", "#BC4749"),
        (success_by_user, "Réussites par utilisateur", "#287F69"),
        (invalid_user_failures, "Échecs avec utilisateur invalide", "#C07B22"),
    )

    for counts, title, color in panels:
        if not isinstance(counts, dict):
            valid_data = False
        else:
            for label, count in counts.items():
                if (
                    not isinstance(label, str)
                    or not isinstance(count, int)
                    or isinstance(count, bool)
                    or count < 0
                ):
                    valid_data = False

    if not valid_data:
        logger.error("Les graphiques attendent trois dictionnaires de comptes entiers positifs ou nuls")
    else:
        max_categories = max(
            len(failed_by_country), len(success_by_user),
            min(len(invalid_user_failures), invalid_user_limit + 1), 1,
        )
        width = max(17, max_categories * 1.5 + 5)
        if max_categories > 15:
            width = max(14, max_categories * 0.24 + 4)
            height = 14
        figure = plt.figure(figsize=(width, height), layout="constrained")
        axes = figure.subplots(3, 1) if max_categories > 15 else figure.subplots(1, 3)
        figure.suptitle("Analyse des connexions SSH", fontsize=18, fontweight="bold")

        for index, axis in enumerate(axes):
            counts = panels[index][0]
            labels = sorted(counts, key=counts.get, reverse=True)
            values = [counts[label] for label in labels]

            # Garder tous les échecs dans le total, même avec beaucoup de noms invalides.
            if index == 2 and len(labels) > invalid_user_limit:
                other_total = sum(values[invalid_user_limit:])
                labels = labels[:invalid_user_limit] + ["Autres utilisateurs"]
                values = values[:invalid_user_limit] + [other_total]

            axis.set_title(panels[index][1] + "\nTotal : " + str(sum(counts.values())), pad=16)
            axis.set_ylabel("Nombre de tentatives")
            axis.yaxis.set_major_locator(MaxNLocator(integer=True))
            axis.set_axisbelow(True)
            axis.grid(axis="y", alpha=0.2)
            axis.spines[["top", "right"]].set_visible(False)
            axis.tick_params(axis="x", length=0)

            if labels:
                bars = axis.bar(range(len(labels)), values, color=panels[index][2], width=0.6)
                axis.set_xticks(range(len(labels)), [fill(label, width=15) for label in labels])
                axis.set_ylim(0, max(max(values) * 1.25, 1))
                axis.bar_label(bars, fmt="%d", padding=3)
            else:
                axis.text(0.5, 0.5, "Aucune tentative", ha="center", va="center", transform=axis.transAxes)
                axis.set_xticks([])
                axis.set_ylim(0, 1)

    return figure


if __name__ == "__main__":
    # Données locales fixes : aucun appel PostgreSQL ou réseau dans ce test.
    test_connections = [
        {"status": "failed", "country": "FR", "user": "root", "invalid_user": False},
        {"status": "failed", "country": "FR", "user": "guest", "invalid_user": True},
        {"status": "failed", "country": None, "user": "guest", "invalid_user": True},
        {"status": "failed", "country": "US", "user": "", "invalid_user": True},
        {"status": "success", "country": "FR", "user": "adminesisa", "invalid_user": False},
        {"status": "success", "country": None, "user": "adminesisa", "invalid_user": False},
        {"status": "success", "country": "US", "user": "demo_admin", "invalid_user": False},
        {"status": "failed", "country": "FR", "user": "guest", "invalid_user": True},
    ]
    test_failed_counts = {"FR": 3, "Inconnu": 1, "US": 1}
    test_success_counts = {"adminesisa": 2, "demo_admin": 1}
    test_invalid_counts = {"guest": 3, "(utilisateur vide)": 1}
    failed_counts = None
    success_counts = None
    invalid_counts = None
    figure = None
    project_directory = Path(__file__).resolve().parents[1]
    report_directory = project_directory / "reports"
    report_file = report_directory / "dashboard_test.png"
    log_directory = project_directory / "logs"
    log_file = log_directory / "dashboard.log"

    log_directory.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
    )

    failed_counts = count_failed_by_country(test_connections)
    success_counts = count_success_by_user(test_connections)
    invalid_counts = count_invalid_user_failures(test_connections)
    assert failed_counts == test_failed_counts
    assert success_counts == test_success_counts
    assert invalid_counts == test_invalid_counts

    figure = create_dashboard(test_failed_counts, test_success_counts, test_invalid_counts)
    assert figure is not None and len(figure.axes) == 3
    figure.suptitle("Analyse des connexions SSH — données de test", fontsize=18, fontweight="bold")
    try:
        report_directory.mkdir(exist_ok=True)
        figure.savefig(report_file, dpi=140)
    except (OSError, ValueError):
        logger.exception("Enregistrement du graphique impossible : %s", report_file)
        raise

    print("Échecs par pays :", failed_counts)
    print("Réussites par utilisateur :", success_counts)
    print("Échecs avec utilisateur invalide :", invalid_counts)
    print("Graphiques enregistrés :", report_file)
