# Analyse des logs d'authentification SSH

Ce projet Python analyse des journaux d'authentification Linux. Il repère les tentatives de connexion SSH, distingue les échecs des réussites, recherche le pays des adresses IP publiques et présente les résultats dans trois graphiques.

## Fonctionnement

1. **Lecture** : les quatre fichiers du dossier `data/` sont lus, y compris les archives `.gz`.
2. **Traitement** : les lignes SSH utiles sont extraites. Les dates, adresses IP et ports sont vérifiés. Les répétitions indiquées dans les logs sont prises en compte.
3. **Géolocalisation** : le pays des IP publiques est demandé à IPinfo. Une IP privée ou sans résultat garde un pays inconnu.
4. **Stockage** : les tentatives sont enregistrées dans la table PostgreSQL `connection`.
5. **Visualisation** : le programme crée un graphique pour les échecs par pays, un pour les réussites par utilisateur et un pour les échecs avec utilisateur invalide.

Le point d'entrée est `main.py`. Il réutilise les données déjà enregistrées lors d'un nouveau lancement pour éviter de les importer une seconde fois.

## Organisation du projet

| Chemin | Rôle |
| --- | --- |
| `data/` | Journaux à analyser |
| `ingestion/read.py` | Lecture des fichiers texte et compressés |
| `processing/extract_transform.py` | Extraction et validation des tentatives SSH |
| `processing/geolocation.py` | Recherche du pays d'une adresse IP |
| `storage/stocking.py` | Création de la table et accès à PostgreSQL |
| `serving/dashboard.py` | Comptages et graphiques avec Matplotlib |
| `main.py` | Exécution complète du traitement |

## Installation et lancement

Prérequis : Python 3.13 ou plus récent, PostgreSQL, [uv](https://docs.astral.sh/uv/) et un accès Internet pour la géolocalisation.

1. Créer dans PostgreSQL une base nommée `log_analyser`.
2. Installer les dépendances depuis la racine du projet :

   ```powershell
   uv sync
   ```

3. Copier `storage/database.example.json` vers `storage/database.local.json`, puis renseigner l'utilisateur et le mot de passe PostgreSQL. Ce fichier local n'est pas versionné.

   ```powershell
   Copy-Item storage/database.example.json storage/database.local.json
   ```

4. Définir un jeton IPinfo pour analyser toutes les IP publiques sans dépendre du quota réduit de l'API publique :

   ```powershell
   $env:IPINFO_TOKEN = "votre_jeton_ipinfo"
   ```

5. Lancer le programme :

   ```powershell
   uv run python main.py
   ```

Le programme affiche chaque fichier lu et son nombre de lignes, puis les totaux dans le terminal. Il distingue les tentatives traitées, celles déjà en base et les nouvelles insertions : zéro nouvelle insertion ne signifie pas que les fichiers ont été ignorés. Il enregistre l'image dans `reports/dashboard.png` et ouvre les graphiques dans une fenêtre. Les messages de diagnostic sont affichés dans le terminal et écrits dans `logs/pipeline.log`.

## Résultats sur les fichiers fournis

Les quatre journaux contiennent **65 565 lignes**. L'analyse des tentatives SSH donne **16 362 connexions** : **16 361 échecs** et **une réussite** pour `adminesisa`. Parmi les échecs, **3 253** concernent un utilisateur invalide. La géolocalisation réalisée avec IPinfo Lite a identifié **88 pays** distincts.

| Fichier | Lignes lues | Tentatives SSH, répétitions comprises |
| --- | ---: | ---: |
| `auth.log.1` | 14 812 | 3 353 |
| `auth.log.2` | 17 565 | 3 363 |
| `auth.log.3.gz` | 18 382 | 4 749 |
| `auth.log.4.gz` | 14 806 | 4 897 |
| **Total** | **65 565** | **16 362** |

Les trois graphiques permettent de voir la répartition des échecs par pays, les utilisateurs ayant réussi à se connecter et les noms invalides les plus fréquents.

## Points à connaître

- Les journaux ne contiennent pas l'année : `main.py` utilise **2026**, l'année des fichiers fournis.
- Les dates des journaux n'indiquent pas de fuseau horaire.
- La recherche du pays dépend de la réponse et du quota d'IPinfo ; un pays peut donc rester inconnu.
- Les fichiers générés dans `logs/` et `reports/` ne sont pas versionnés.
