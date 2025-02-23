import os
import json
from flask import Flask, current_app
from config import Config
from app.models.a_acces import A_ACCES
from app.models.a_recherche import A_RECHERCHE
from app.models.dossier import DOSSIER
from app.models.favoris import FAVORIS
from app.models.fichier import FICHIER
from app.models.notification import NOTIFICATION
from app.models.recherche import RECHERCHE
from app.models.role import ROLE
from app.models.sous_dossier import SOUS_DOSSIER
from app.models.utilisateur import UTILISATEUR
from app.utils import check_notitications, get_total_file_count, get_total_file_count_by_id
from app.models.lien import LIEN
from app.extensions import redis, socketio, crsf, login_manager, celery, db, compress

def create_app(config_class = Config, is_worker=False):
    from app.register import bp as register_bp
    from app.notifications import bp as notifications_bp
    from app.login import bp as login_bp
    from app.home import bp as home_bp
    from app.administration import bp as administration_bp
    from app.profile import bp as profile_bp
    from app.file_handler import bp as file_handler_bp
    from app.desktop import bp as desktop_bp
    from app.password_reset import bp as password_reset_bp

    
    storage_path = config_class.STORAGE_PATH
    if not os.path.exists(f'{storage_path}/storage'):
        os.makedirs(f'{storage_path}/storage')
    if not os.path.exists(f'{storage_path}/storage/files'):
        os.makedirs(f'{storage_path}/storage/files')
    if not os.path.exists(f'{storage_path}/storage/screenshots'):
        os.makedirs(f'{storage_path}/storage/screenshots')
    if not os.path.exists(f'{storage_path}/storage/database'):
        os.makedirs(f'{storage_path}/storage/database')
    if not os.path.exists(f'{storage_path}/storage/redis'):
        os.makedirs(f'{storage_path}/storage/redis')
    if not os.path.exists(f'{storage_path}/storage/password'):
        os.makedirs(f'{storage_path}/storage/password')
    json_file_path = f'{storage_path}/storage/password/password.json'
    if not os.path.exists(json_file_path):
        with open(json_file_path, 'w') as json_file:
            json.dump({}, json_file)

    app = Flask(__name__)
    app.config.from_object(config_class)
    app.storage_path = storage_path
    crsf.init_app(app)
    db.init_app(app)
    with app.app_context():
        db.create_all()
        fill_db()

    login_manager.init_app(app)
    login_manager.login_view = 'login.login'

    socketio.init_app(app)

    celery.conf.update(app.config)

    redis.init_app(app)

    compress.init_app(app)

    if not is_worker:
        def handle_worker_status_message(message):
            data = json.loads(message['data'].decode('utf-8'))
            socketio.emit('worker_status', data, namespace='/administration')

        def handle_process_status_message(_):
            with app.app_context():
                total_files = FICHIER.query.count()
                total_files_processed = FICHIER.query.filter(FICHIER.est_Indexe_Fichier == 1).count()
                socketio.emit('total_files', total_files, namespace='/administration')
                socketio.emit('total_files_processed', total_files_processed, namespace='/administration')

        def handle_index_verification_message(message):
            data = json.loads(message['data'].decode('utf-8'))
            socketio.emit('index_verification_success',
                          {'message': data['message']},
                          namespace='/administration',
                          room=f'user_{data['user']}')

        pubsub = redis.pubsub()
        pubsub.subscribe(**{'worker_status': handle_worker_status_message})
        pubsub.subscribe(**{'process_status': handle_process_status_message})
        pubsub.subscribe(**{'file_processed': lambda message: socketio.emit('file_processed', json.loads(message['data'].decode('utf-8')), namespace='/notifications')})
        pubsub.subscribe(**{'index_verification_success': handle_index_verification_message})
        pubsub.run_in_thread(sleep_time=0.5)

    @app.context_processor
    def utility_processor():
        return dict(get_total_file_count=get_total_file_count,
                    get_total_file_count_by_id=get_total_file_count_by_id,
                    check_notitications=check_notitications)

    app.register_blueprint(register_bp, url_prefix='/inscription')
    app.register_blueprint(notifications_bp, url_prefix='/notifications')
    app.register_blueprint(login_bp, url_prefix='/connexion')
    app.register_blueprint(home_bp, url_prefix='/')
    app.register_blueprint(administration_bp, url_prefix='/administration')
    app.register_blueprint(profile_bp, url_prefix='/profil')
    app.register_blueprint(file_handler_bp)
    app.register_blueprint(desktop_bp, url_prefix='/bureau')
    app.register_blueprint(password_reset_bp, url_prefix='/reinitialisation')
    return app

def fill_db():
    if not ROLE.query.all():
        db.session.add(ROLE(nom_Role="ADMIN"))
        db.session.add(ROLE(nom_Role="RCH4"))
        db.session.add(ROLE(nom_Role="RCH3"))
        db.session.add(ROLE(nom_Role="RCH1/2"))
        db.session.commit()

    if not DOSSIER.query.all():
        db.session.add(DOSSIER(nom_Dossier="Décret / Circulaire", priorite_Dossier=1, couleur_Dossier="#ffffcc"))
        db.session.add(DOSSIER(nom_Dossier="GDO / GTO", priorite_Dossier=2, couleur_Dossier="#ffcc99"))
        db.session.add(DOSSIER(nom_Dossier="DTO / NDS", priorite_Dossier=3, couleur_Dossier="#ffcccc"))
        db.session.add(DOSSIER(nom_Dossier="PEX / RETEX / PIO", priorite_Dossier=4, couleur_Dossier="#ff99cc"))
        db.session.add(DOSSIER(nom_Dossier="Support formation", priorite_Dossier=5, couleur_Dossier="#ffccff"))
        db.session.add(DOSSIER(nom_Dossier="Mémoire", priorite_Dossier=6, couleur_Dossier="#cc99ff"))
        db.session.add(DOSSIER(nom_Dossier="Thèse", priorite_Dossier=7, couleur_Dossier="#ccccff"))
        db.session.add(DOSSIER(nom_Dossier="À trier", priorite_Dossier=8, couleur_Dossier="#ccffff"))
        db.session.add(DOSSIER(nom_Dossier="Archives", priorite_Dossier=2147483647, couleur_Dossier="#d3d7d8"))
        db.session.commit()

    if not db.session.query(A_ACCES).all():
        for dossier in DOSSIER.query.all():
            db.session.execute(A_ACCES.insert().values(id_Role=1, id_Dossier=dossier.id_Dossier))
            db.session.execute(A_ACCES.insert().values(id_Role=2, id_Dossier=dossier.id_Dossier))
            db.session.execute(A_ACCES.insert().values(id_Role=3, id_Dossier=dossier.id_Dossier))
            db.session.execute(A_ACCES.insert().values(id_Role=4, id_Dossier=dossier.id_Dossier))
        db.session.commit()

    if not UTILISATEUR.query.all():
        db.session.add(UTILISATEUR(nom_Utilisateur="Administrateur", prenom_Utilisateur="", email_Utilisateur="admin@admin.fr", mdp_Utilisateur="$2b$12$sOih7qRKimxwqJXITajOfO.Twyg.lModCMYSrgxLpxGompCQjjM56", telephone_Utilisateur="", est_Actif_Utilisateur=1, id_Role=1))
        # password: O]SxR=rBv%
        db.session.commit()