# <u>Hadès</u>

## <u>Sommaire</u>

- [Hadès](#hadès)
  - [Sommaire](#sommaire)
  - [Démarrer Hadès](#démarrer-hadès)
    - [Prérequis](#prérequis)
    - [Configuration](#configuration)
    - [Lancer le docker-compose](#lancer-le-docker-compose)
  - [Se connecter à l'application](#se-connecter-à-lapplication)
    - [Compte de test](#compte-de-test)
  - [Structure de l'application](#structure-de-lapplication)
    - [Répertoire `app`](#répertoire-app)
    - [Répertoire `app/models`](#répertoire-appmodels)
    - [Répertoire `app/storage`](#répertoire-appstorage)
    - [Répertoire `app/static`](#répertoire-appstatic)
    - [Répertoire `app/templates`](#répertoire-apptemplates)
    - [Répertoires `app/*`](#répertoires-app)
  - [Équipe de développement](#équipe-de-développement)

## <u>Démarrer Hadès</u>

### Prérequis

- Docker 26 ou supérieur
- Clonez le dépôt git : `git clone https://github.com/etave/Hades.git`

### Configuration

Pour configurer l'application, il faut créer un fichier `.env` à la racine du projet et y ajouter les variables d'environnement suivantes :

```
STORAGE_PATH=<chemin du répertoire de stockage>
SECRET_KEY=<clé secrète>
MAIL_SERVER=<serveur SMTP>
MAIL_PORT=<port SMTP>
MAIL_USERNAME=<adresse email>
MAIL_PASSWORD=<mot de passe>
```

### Lancer le docker-compose

Pour lancer l'application, il suffit de se rendre à la racine du projet et d'exécuter les commandes suivantes :

```bash
docker compose build
docker compose up --scale web=<nombre de Gunicorn> --scale worker=<nombre de Celery>
```


## <u>Se connecter à l'application</u>

Pour se connecter à l'application, il faut se rendre sur l'adresse `http://0.0.0.0` et entrer les identifiants d'un compte utilisateur.

### Compte de test

À la première utilisation, il existe un compte administrateur déjà fonctionnel. 

| Identifiant | Mot de passe | Rôle |
| ----------- | ------------ | ---- |
| admin@admin.fr | O]SxR=rBv% | ADMIN |


## <u>Structure de l'application</u>

### Répertoire `app`

Le répertoire `app` contient l'ensemble du code source de l'application.
Il contient les répertoires suivants :

- Le fichier `__init__.py` contient l'usine de l'application.
- Le fichier `celery.py` contient la création d'un worker Celery.
- Le fichier `decorators.py` contient l'ensemble des décorateurs utilisé sur les routes. 
- Le fichier `extensions.py` contient les extensions de l'application (SocketIO, Redis, Compress, etc.).
- Le fichier `mail.py` contient les fonctions permettant l'envoie de mail.
- Le fichier `tasks.py` contient les tâches Celery de l'application.
- Le fichier `utils.py` contient un ensemble de classes et de fonctions utilitaire.

### Répertoire `app/models`

Le répertoire `app/models` contient l'ensemble des modèles de l'application utilisé par SQLAlchemy.

### Répertoire `app/storage`

Le répertoire `app/storage` contient l'ensemble des fichiers de stockage de l'application.
Il est créé automatiquement lors de l'initialisation de l'application.
Il contient les répertoires suivants :

- Le répertoire `app/storage/database` contient la base de données de l'application.
- Le répertoire `app/storage/files` contient l'ensemble des fichiers importés par les utilisateurs.
- Le répertoire `app/storage/index` contient l'index Whoosh de l'application.
- Le répertoire `app/storage/password` contient le fichier pour les mots de passe oubliés.
- Le répertoire `app/storage/redis` contient les données de Redis.
- Le répertoire `app/storage/screenshots` contient les captures d'écran des visualisations.

### Répertoire `app/static`

- Le répertoire `app/static` contient l'ensemble des fichiers statiques de l'application.
- Le répertoire `app/static/css` contient l'ensemble des fichiers css de l'application.
- Le répertoire `app/static/js` contient l'ensemble des fichiers JavaScript de l'application.
- Le répertoire `app/static/img` contient l'ensemble des fichiers image de l'application.
- Le fichier `hades.webmanifest` contient les informations de l'application web.

### Répertoire `app/templates`

- Le répertoire `app/templates/components` contient l'ensemble des fichiers html de composants de l'application.
- Les répertoires `app/templates/*` contiennent l'ensemble des fichiers html de l'application par route.

### Répertoires `app/*`

- Les répertoires `app/*` contiennent l'ensemble des fichiers Python de l'application par route.

## <u>Équipe de développement</u>

[Etave Nathan](https://github.com/etave)  
[Mechain Romain](https://github.com/RomainMechain)