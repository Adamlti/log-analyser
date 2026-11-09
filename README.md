# Log analyser

Analyse de logs d'authentification Linux, organisée en modules :

```text
data/                          Fichiers auth.log et archives .gz
ingestion/read.py              Lecture et décompression des fichiers
processing/extract_transform.py Extraction, nettoyage de date et transformation
processing/geolocation.py      Recherche du pays d'une IP publique
storage/stocking.py             Stockage PostgreSQL
serving/                       Futurs graphiques matplotlib
main.py                        Futur assemblage du pipeline complet
```

Chaque module est travaillé séparément, testé puis commité avant de passer au
suivant. `processing` et `storage` sont validés. La correction de l'ingestion
assure maintenant la lecture de tous les fichiers, avant le futur assemblage
du pipeline.

## Règles du code

- Les variables locales sont initialisées au début de chaque fonction.
- Chaque fonction possède un seul `return`, placé à la fin.
- `processing` utilise uniquement la bibliothèque standard de Python.
- `storage` utilise `psycopg2`, déjà installé dans l'environnement du projet.
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
date sans fuseau horaire ajouté. L'année 2026 dans le `__main__` est uniquement
une valeur de test à adapter à l'année réelle des logs.

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

Les lignes CRON, les notifications `Invalid user`, les erreurs PAM et les
fermetures de connexion sont ignorées pour le comptage. Seuls les messages SSH
`Failed ... for ...` et `Accepted ... for ...` deviennent des tentatives. Cela
évite de compter plusieurs lignes relatives au même événement d'authentification.

Une tentative mal formée, une IP ou un port invalide, ou une date impossible
retourne `None` et produit un avertissement.

## Géolocalisation

### `geo_location(ip)`

Utilise `urllib.request` et `json`, sans dépendance externe. Pour une IP publique,
la fonction appelle `https://ipinfo.io/<ip>/json` avec un timeout de 10 secondes.
Elle retourne le dictionnaire JSON si celui-ci contient un pays.

Une adresse non publique n'entraîne aucun appel réseau. Une adresse invalide,
une erreur HTTP, un timeout, une réponse JSON incorrecte ou un pays absent
donne `None`. Les erreurs sont journalisées. La disponibilité du service réel
n'est pas prouvée par le test simulé.

Lors de la future intégration, le champ `country` de la connexion sera rempli
avec `location["country"]` si une localisation existe. Sinon, il restera `None`
et pourra apparaître dans une catégorie « inconnu » sur le dashboard.

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

La table publique reste vide tant que de vraies données n'ont pas été insérées :
les exemples du `__main__` sont isolés dans une table temporaire.

## Tests locaux des modules

Depuis le dossier `log_analyser`, avec l'environnement existant :

```powershell
.\.venv\Scripts\python.exe -m ingestion.read
.\.venv\Scripts\python.exe -m processing.extract_transform
.\.venv\Scripts\python.exe -m processing.geolocation
.\.venv\Scripts\python.exe -m storage.stocking
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

## Journaux

Les fonctions utilisent le logger de leur module. Les lancements locaux
configurent l'affichage des messages et leur écriture dans :

```text
logs/ingestion.log
logs/extract_transform.log
logs/geolocation.log
logs/stocking.log
```

Ces fichiers locaux sont ignorés par Git. Le futur point d'entrée `main.py`
devra aussi configurer la journalisation pour les appels du pipeline complet.

## Étapes suivantes

- Créer les graphiques matplotlib : échecs par pays, réussites par utilisateur
  et échecs avec `invalid user`.
- Assembler les modules puis tester le pipeline via `main.py`.

Le travail s'arrête après la validation et le commit de `storage`, avant de
commencer `serving`. La consigne de rendu reste : aucun push après mardi 10.
