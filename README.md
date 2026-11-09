# Log analyser

Analyse de logs d'authentification Linux, organisée en modules :

```text
data/                          Fichiers auth.log et archives .gz
ingestion/read.py              Lecture et décompression des fichiers
processing/extract_transform.py Extraction, nettoyage de date et transformation
processing/geolocation.py      Recherche du pays d'une IP publique
storage/                       Futur stockage PostgreSQL
serving/                       Futurs graphiques matplotlib
main.py                        Futur assemblage du pipeline complet
```

Chaque module est travaillé séparément, testé puis commité avant de passer au
suivant. L'étape actuelle porte uniquement sur `processing` ; l'ingestion
existante est conservée.

## Règles du code

- Les variables locales sont initialisées au début de chaque fonction.
- Chaque fonction possède un seul `return`, placé à la fin.
- `processing` utilise uniquement la bibliothèque standard de Python.
- Aucun paquet supplémentaire n'est installé.
- Chaque fichier possède un `__main__` avec des variables locales fixes pour
  tester ses fonctions sans lancer le pipeline.

## Extraction et transformation

### `extract(row)`

Reçoit une ligne et retourne ses champs sous forme de dictionnaire :
`month`, `day`, `time`, `host`, `service`, `pid`, `message`.
Le message complet est conservé. Le jour et le PID sont convertis en entiers ;
un PID absent vaut `None`. Une ligne non reconnue retourne `None` et produit un
avertissement.

### `clean_date(month, day, time, year)`

Convertit les éléments de date en objet `datetime`, directement utilisable par
le futur stockage PostgreSQL. Les dates impossibles, comme le 31 février, sont
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

## Tests locaux des modules

Depuis le dossier `log_analyser`, avec l'environnement existant :

```powershell
.\.venv\Scripts\python.exe -m processing.extract_transform
.\.venv\Scripts\python.exe -m processing.geolocation
```

Le premier `__main__` teste séparément `extract`, `clean_date` et `transform`
avec une ligne, des champs de date et un dictionnaire fixes. Il vérifie les
résultats avec des assertions, puis les affiche.

Le second teste `geo_location` avec une IP et une réponse JSON locales fixes.
La réponse HTTP est simulée avec `unittest.mock` : ce test ne contacte pas
Internet. Aucun argument de commande n'est nécessaire. Importer ces fichiers
n'exécute pas leurs blocs de test.

Les vérifications supplémentaires utilisent aussi des entrées fixes : réussites,
échecs, utilisateurs invalides, dates impossibles, années bissextiles, adresses
IPv4 et IPv6, ports incorrects et erreurs réseau simulées.

Dernière validation : 24 tests réussis avec les paquets externes désactivés
(`python -S`). Les règles sur l'initialisation des variables et le retour unique
en fin de fonction ont également été vérifiées.

## Journaux

Les fonctions utilisent le logger de leur module. Les lancements locaux
configurent l'affichage des messages et leur écriture dans :

```text
logs/extract_transform.log
logs/geolocation.log
```

Ces fichiers locaux sont ignorés par Git. Le futur point d'entrée `main.py`
devra aussi configurer la journalisation pour les appels du pipeline complet.

## Étapes suivantes

- Stocker les connexions dans une table PostgreSQL nommée `connection`.
- Créer les graphiques matplotlib : échecs par pays, réussites par utilisateur
  et échecs avec `invalid user`.
- Assembler les modules puis tester le pipeline via `main.py`.

Le travail s'arrête après la validation et le commit de `processing`, avant
de commencer le stockage. La consigne de rendu reste : aucun push après mardi 10.
