# Log analyser

Analyse de logs d'authentification Linux, organisée en modules :

```text
data/                          Fichiers auth.log et archives .gz
ingestion/read.py              Lecture et décompression des fichiers
processing/extract_transform.py Extraction, nettoyage de date et transformation
processing/geolocation.py      Recherche du pays d'une IP publique
storage/stocking.py             Stockage PostgreSQL
serving/dashboard.py           Comptages et graphiques matplotlib
main.py                        Pipeline complet jusqu'aux graphiques
```

Chaque module est travaillé séparément, testé puis commité avant de passer au
suivant. Les modules sont validés séparément. L'ingestion lit tous les fichiers,
et `serving` génère les trois graphiques demandés. `main.py` assemble les modules.
Le pipeline est vérifié localement avec une API simulée et avec les pays réels
obtenus auprès d'IPinfo Lite. La table PostgreSQL correspond aux occurrences des
quatre fichiers sources, y compris leurs répétitions réelles.

## Règles du code

- Les variables locales sont initialisées au début de chaque fonction.
- Chaque fonction possède un seul `return`, placé à la fin.
- `processing` utilise uniquement la bibliothèque standard de Python.
- `storage` utilise `psycopg2`, déjà installé dans l'environnement du projet.
- `serving` utilise `matplotlib`, déjà installé et demandé pour les graphiques.
- Aucun paquet supplémentaire n'est installé.
- Chaque fichier possède un `__main__` avec des variables locales fixes pour
  tester ses fonctions sans lancer le pipeline.

## Ingestion : `ingest(path)`

La fonction lit tous les fichiers du dossier dans l'ordre de leurs noms. Elle
décompresse les archives `.gz`, lit les autres fichiers en texte UTF-8 et ajoute
leurs lignes à une liste commune avec `rows.extend(...)`. Le seul `return` se
trouve après la boucle : aucun fichier n'est abandonné après le premier.

Les sous-dossiers sont ignorés. Une erreur de lecture est journalisée avec le
nom du fichier concerné, puis la lecture des fichiers suivants continue. Un
dossier vide ou inaccessible donne une liste vide ; l'erreur d'accès est
journalisée dans ce dernier cas.

La vérification sur les quatre fichiers actuels retrouve 65 565 lignes et
inclut la connexion réussie d'`adminesisa` présente dans `auth.log.2`.

## Extraction et transformation

### `extract(row)`

Reçoit une ligne et retourne ses champs sous forme de dictionnaire :
`month`, `day`, `time`, `host`, `service`, `pid`, `message`.
Le message complet est conservé. Le jour et le PID sont convertis en entiers ;
un PID absent vaut `None`. Une ligne non reconnue retourne `None` et produit un
avertissement.

### `clean_date(month, day, time, year)`

Convertit les éléments de date en objet `datetime`, directement utilisable par
le stockage PostgreSQL. Les dates impossibles, comme le 31 février, sont
rejetées et signalées dans les logs.

Les fichiers `auth.log` ne contiennent ni année ni fuseau horaire. L'appelant
doit donc fournir l'année ; la fonction ne la devine pas. Le résultat est une
date sans fuseau horaire ajouté. L'année 2026 a été confirmée pour tous les logs
de ce projet et est fournie explicitement par `main.py`.

### `transform(record, year)`

Reçoit les champs extraits et l'année. Retourne une tentative SSH contenant
les champs d'origine et les champs préparés pour la future table `connection` :

| Champ | Valeur |
| --- | --- |
| `status` | `failed` ou `success` |
| `date` | Objet `datetime` valide |
| `user` | Utilisateur, éventuellement vide pour un utilisateur invalide |
| `country` | `None` tant que le pays n'a pas été obtenu |
| `ip` | Adresse IPv4 ou IPv6 validée |
| `port` | Entier entre 1 et 65535 |
| `method` | Méthode d'authentification, par exemple `password` ou `publickey` |
| `invalid_user` | Booléen indiquant un échec avec utilisateur invalide |
| `count` | Nombre de tentatives représentées par la ligne, 1 par défaut |

Les lignes CRON, les notifications `Invalid user`, les erreurs PAM et les
fermetures de connexion sont ignorées pour le comptage. Seuls les messages SSH
`Failed ... for ...` et `Accepted ... for ...` deviennent des tentatives. Cela
évite de compter plusieurs lignes relatives au même événement d'authentification.

Une tentative mal formée, une IP ou un port invalide, ou une date impossible
retourne `None` et produit un avertissement.

Les messages `message repeated N times: [ ... ]` sont dépliés avant de reconnaître
la tentative. Leur champ `count` vaut N ; le message original déjà présent dans
les logs compte séparément. `main.py` insère une ligne PostgreSQL par tentative
représentée, sans changer le schéma de la table.

Avec les répétitions, les fichiers contiennent 16 361 tentatives échouées,
une réussite et 3 253 échecs avec utilisateur invalide. Le total de 9 092 obtenu
auparavant concernait uniquement les lignes d'échec directes, sans les résumés.

## Géolocalisation

### `geo_location(ip)`

Utilise `urllib.request` et `json`, sans dépendance externe. Pour une IP publique,
la fonction appelle `https://ipinfo.io/<ip>/json` avec un timeout de 10 secondes.
Elle retourne le dictionnaire JSON si celui-ci contient un pays.

Si `IPINFO_TOKEN` est défini, elle utilise plutôt
`https://api.ipinfo.io/lite/<ip>`, avec le jeton dans l'en-tête `Authorization`.
Le champ Lite `country_code` est remis dans `location["country"]` pour garder
la compatibilité avec le stockage. Le lien Lite seul n'est pas une clé : il faut
un jeton personnel obtenu dans son compte IPinfo, comme indiqué dans la
[documentation IPinfo](https://ipinfo.io/developers/lite-api).

```powershell
$env:IPINFO_TOKEN = "votre_jeton_personnel"
.\.venv\Scripts\python.exe main.py
```

Une requête contient une seule IP. Les appels sont séquentiels, avec réutilisation
des pays déjà connus ; aucune liste d'IP n'est envoyée dans une même requête.

Une adresse non publique n'entraîne aucun appel réseau. Une adresse invalide,
une erreur HTTP, un timeout, une réponse JSON incorrecte ou un pays absent
donne `None`. Les erreurs sont journalisées. La disponibilité du service réel
n'est pas prouvée par le test simulé.

Les HTTP 401, 403 et 429 sont propagés au point d'entrée : le traitement s'arrête au lieu de
continuer à insérer des pays inconnus à cause du quota. Les pays déjà enregistrés
sont réutilisés lors de la reprise. L'API publique sans compte est limitée à
1 000 appels par jour, selon la
[documentation IPinfo](https://support.ipinfo.io/hc/en-us/articles/30792479436562-What-Is-the-Difference-Between-Using-the-Authenticated-Free-Plan-and-the-Public-API-With-No-Account).

Dans `main.py`, le champ `country` de la connexion est rempli
avec `location["country"]` si une localisation existe. Sinon, il restera `None`
et pourra apparaître dans une catégorie « inconnu » sur le dashboard.

Ce branchement est maintenant dans `main.py` : pour chaque tentative extraite,
`geo_location(connection["ip"])` fournit le pays, puis
`stocking.insert_connection(db_connection, connection)` enregistre la connexion
avec ce pays. Un dictionnaire local évite les appels répétés pour la même IP.
L'année utilisée est 2026, confirmée pour tous les logs. Aucune fonction ni
aucun module supplémentaire n'est ajouté. L'exécution réelle de l'API reste
à autoriser ; les tests utilisent des réponses simulées.
Les tests du branchement vérifient aussi l'enregistrement du pays dans
PostgreSQL, avec une table temporaire. Aucun pays simulé n'est gardé dans la
table publique.

## Stockage PostgreSQL

La base locale `log_analyser` a été préparée sur `localhost:5432`. Le module
travaille dans cette base, avec une table nommée `connection`. Sur une autre
machine, la base doit exister avant le lancement du module.

### Configuration locale

Le fichier `storage/database.example.json` décrit les paramètres attendus :
`host`, `port`, `dbname`, `user`, `password`. Créer le fichier
`storage/database.local.json` à partir de ce modèle et y renseigner les valeurs
locales. Ce poste possède déjà ce fichier ; il est ignoré par Git.
Le mot de passe ne figure ni dans le code du module ni dans le modèle versionné.

### Fonctions

| Fonction | Résultat |
| --- | --- |
| `connect_database(config)` | Connexion ouverte, ou `None` si elle échoue |
| `create_table(db_connection)` | `True` si la table existe ou a été créée, sinon `False` |
| `insert_connection(db_connection, record)` | Identifiant de la ligne validée, ou `None` en cas d'erreur |
| `read_connections(db_connection)` | Liste de dictionnaires, `[]` si la table est vide, `None` en cas d'erreur |

La table contient `id`, `status`, `date`, `user`, `country`, `ip` et
`invalid_user`. La date est stockée en `TIMESTAMP WITHOUT TIME ZONE`, l'IP en
`INET` et le marqueur d'utilisateur invalide en booléen. Le statut doit être
`failed` ou `success`. Un pays inconnu est enregistré en `NULL`.

Les données sont transmises par paramètres SQL. Le champ `user` est cité dans
les requêtes car ce nom a aussi un sens particulier en SQL. Une création
répétée ne supprime pas les données ; les tentatives répétées restent des lignes
distinctes. Les champs supplémentaires du traitement, comme le port ou la
méthode d'authentification, ne sont pas stockés dans cette table.

Chaque opération gère sa transaction : une réussite est validée, une erreur SQL
déclenche un rollback. L'insertion ne retourne un identifiant qu'après la
réussite du commit. L'appelant doit fermer la connexion avec `.close()`.

Pour voir les données dans l'outil de requêtes de pgAdmin, une fois connecté à
la base `log_analyser` :

```sql
SELECT id, status, date, "user", country, ip, invalid_user
FROM public.connection
ORDER BY id;
```

Les exemples du `__main__` et les tests automatisés sont isolés dans une table
temporaire. La table publique conserve les événements importés par l'application.

## Serving : les graphiques matplotlib

`serving/dashboard.py` reçoit les dictionnaires de connexions que le stockage
peut renvoyer avec `read_connections`. Le module ne contacte ni PostgreSQL
ni le service de géolocalisation.

| Fonction | Résultat |
| --- | --- |
| `count_failed_by_country(connections)` | Nombre de lignes `failed` par pays |
| `count_success_by_user(connections)` | Nombre de lignes `success` par utilisateur |
| `count_invalid_user_failures(connections)` | Nombre de lignes `failed` avec `invalid_user=True`, par nom invalide |
| `create_dashboard(failed_by_country, success_by_user, invalid_user_failures)` | Figure matplotlib contenant les trois graphiques |

Les pays absents ou vides sont regroupés sous `Inconnu`. Les codes pays sont
normalisés en majuscules. Un nom d'utilisateur vide est affiché sous
`(utilisateur vide)`. Les tentatives répétées restent comptées séparément.

Chaque compteur retourne un dictionnaire, ou `None` si son entrée n'est pas
une liste ou un tuple. Les lignes incorrectes sont signalées dans les journaux
et ignorées. Une liste vide donne un dictionnaire vide ; une erreur de lecture
du stockage (`None`) ne devient donc pas un faux résultat sans événement.

Les trois graphiques utilisent des barres verticales avec `Axes.bar()` de
matplotlib. Les nombres sont affichés au-dessus des barres et les graduations
sont entières. Chaque graphique affiche son total. Une série vide porte le
message `Aucune tentative`.

Tous les pays et tous les utilisateurs ayant réussi sont représentés. Pour
garder le troisième graphique lisible, les dix noms invalides les plus fréquents
sont affichés, puis les autres sont additionnés dans une barre
`Autres utilisateurs`. Le compteur conserve tous les noms et le total du
graphique inclut tous les échecs avec utilisateur invalide.

`create_dashboard` retourne une figure gérée par `pyplot`, sans modifier les
comptes reçus ni appeler `show`. L'appelant peut l'enregistrer avec
`.savefig(...)`. `main.py` fournit les connexions relues depuis PostgreSQL,
enregistre les graphiques dans `reports/dashboard.png`, ferme la connexion à
la base, puis ouvre la fenêtre matplotlib avec `plt.show(block=True)`.
Fermer cette fenêtre termine le programme.

## Tests locaux des modules

Depuis le dossier `log_analyser`, avec l'environnement existant :

```powershell
.\.venv\Scripts\python.exe -m ingestion.read
.\.venv\Scripts\python.exe -m processing.extract_transform
.\.venv\Scripts\python.exe -m processing.geolocation
.\.venv\Scripts\python.exe -m storage.stocking
.\.venv\Scripts\python.exe -m serving.dashboard
```

Le `__main__` d'ingestion utilise le chemin local fixe du dossier `data`, puis
affiche le nombre total de lignes et les dix premières. Il fonctionne aussi
lorsque le fichier est lancé depuis un autre dossier, sans exécuter le pipeline.

Le `__main__` de `processing.extract_transform` teste `extract`, `clean_date` et `transform`
avec une ligne, des champs de date et un dictionnaire fixes. Il vérifie les
résultats avec des assertions, puis les affiche.

Celui de `processing.geolocation` teste `geo_location` avec une IP et une réponse JSON locales fixes.
La réponse HTTP est simulée avec `unittest.mock` : ce test ne contacte pas
Internet. Aucun argument de commande n'est nécessaire. Importer ces fichiers
n'exécute pas leurs blocs de test.

Le `__main__` de `storage.stocking` teste les quatre fonctions avec des données
fixes : un échec avec utilisateur invalide et une réussite. La connexion et les
requêtes utilisent PostgreSQL réel. La table publique est créée ou vérifiée,
puis une table temporaire du même nom reçoit les exemples. Cette table
temporaire disparaît quand la connexion se ferme ; aucun exemple n'est conservé
dans `public.connection`.

Le `__main__` de `serving.dashboard` teste les quatre fonctions avec des
variables locales fixes. Le jeu d'exemple contient cinq échecs, trois réussites
et quatre échecs avec utilisateur invalide. Les assertions vérifient les
compteurs, puis le module enregistre `reports/dashboard_test.png` avec les trois
graphiques. Cette image porte la mention « données de test » ; elle ne représente
pas les événements réels de la base. Aucun argument ni accès réseau n'est requis.

Les vérifications supplémentaires utilisent aussi des entrées fixes : réussites,
échecs, utilisateurs invalides, dates impossibles, années bissextiles, adresses
IPv4 et IPv6, ports incorrects et erreurs réseau simulées.

Validation d'ingestion : 12 tests réussis sans paquet externe. Ils vérifient
la collecte des fichiers texte et gzip, l'encodage UTF-8, les archives invalides,
les erreurs d'accès, les journaux, les quatre fichiers réels et la présence de la
connexion réussie. Les variables initialisées au début et le retour unique à la
fin sont également vérifiés.

Validation de `processing` : 24 tests réussis avec les paquets externes désactivés
(`python -S`). Les règles sur l'initialisation des variables et le retour unique
en fin de fonction ont également été vérifiées.

Validation de `storage` : 26 tests réussis. Ils couvrent notamment la persistance
entre deux connexions PostgreSQL, les retours arrière après erreur SQL, un échec
au moment du commit, les adresses IPv4 et IPv6, les pays inconnus, les paramètres
SQL, les journaux et les règles de structure des fonctions. Les données de ces
vérifications sont isolées et retirées à la fin des essais.

Validation de `serving` : 25 tests réussis, dont les comptes exacts, les barres
verticales matplotlib, les graduations entières, les pays inconnus, les entrées
incorrectes, les séries vides, les utilisateurs invalides regroupés sans perte
du total et l'export PNG. La structure des fonctions et l'absence d'installation
supplémentaire sont également vérifiées. Le rendu a été inspecté visuellement.

## Test du pipeline via main.py

```powershell
.\.venv\Scripts\python.exe main.py
```

Ce lancement contacte IPinfo pour les IP publiques sans pays connu. Il réutilise
les fonctions existantes : ingestion, extraction, date, géolocalisation,
insertion, lecture puis comptage et graphiques matplotlib.

Les événements déjà présents sont reconnus pour reprendre un import partiel
sans les réinsérer. Les pays manquants sont complétés par IP quand l'API fournit
une réponse. Les occurrences répétées dans les sources restent conservées.
Un verrou PostgreSQL empêche deux lancements de ce pipeline d'importer en même
temps ; il est libéré à la fermeture de la connexion.

Dix-sept tests du pipeline passent avec une API simulée et PostgreSQL temporaire.
Ils vérifient la reprise depuis un import partiel, les pays enregistrés, l'arrêt
sur HTTP 401/403/429, les erreurs de connexion, Lite, le verrou d'import et les
graphiques. Au-delà de quinze catégories, les trois graphiques sont disposés
verticalement pour garder les pays lisibles. Les totaux retrouvés
sont 16 361 échecs, une réussite pour `adminesisa` et 3 253 échecs avec utilisateur
invalide. L'aperçu `reports/dashboard_pipeline_test.png` est marqué comme test ;
ses pays ne sont pas des résultats réels de géolocalisation.

## Vérification avec les pays réels

Les 1 853 IP publiques ont été interrogées auprès d'IPinfo Lite, une IP par
requête. Leurs pays sont enregistrés dans PostgreSQL : 88 pays distincts sont
présents. L'IP privée `10.10.33.81` n'a pas de pays et n'est pas envoyée à l'API.

La table `public.connection` contient les 16 362 occurrences attendues :
16 361 échecs, une réussite pour `adminesisa` et 3 253 échecs avec utilisateur
invalide. La comparaison avec les quatre fichiers sources ne trouve aucune
occurrence manquante ni supplémentaire.

Les 10 824 copies supplémentaires détectées lors de la vérification ont été
archivées dans `public.connection_duplicate_archive_20261110`, puis retirées
de la table active dans une seule transaction. Les 439 lignes initiales et les
véritables répétitions des logs sont conservées. Le plan et le résultat de
l'opération sont disponibles localement dans
`reports/duplicate_repair_plan.json` et `reports/duplicate_repair_result.json`.

La relance de `main.py` sur cette base a produit zéro insertion et zéro requête
HTTP, contrôlées avec un appel réseau interdit pendant ce test. Le graphique
final `reports/dashboard.png` est généré depuis les données réelles de la base.
Son rendu et les trois totaux ont été vérifiés. L'ouverture de la fenêtre
matplotlib a aussi été testée avec les données fixes du module puis via
`main.py`, après fermeture de la connexion PostgreSQL.

## Journaux

Les fonctions utilisent le logger de leur module. Les lancements locaux
configurent l'affichage des messages et leur écriture dans :

```text
logs/ingestion.log
logs/extract_transform.log
logs/geolocation.log
logs/stocking.log
logs/dashboard.log
logs/pipeline.log
```

Ces fichiers locaux sont ignorés par Git. `main.py` configure aussi les journaux
du pipeline avec le nom du module dans chaque message.
Les graphiques générés dans `reports/` sont également ignorés par Git.

La consigne de rendu reste : aucun push après mardi 10.
