import os
import json
from datetime import datetime
from app.extensions import celery, redis, db
from app import create_app
from celery import current_task
from app.utils import FileReader, NLPProcessor, Whoosh
from fasteners import InterProcessLock
from app.models.fichier import FICHIER

@celery.task(name='app.tasks.process_file')
def process_file(file_path, filename, folder_id, file_id, user_tags, current_user, file, folder, action):
    app = create_app(is_worker=True)
    with app.app_context():
        try:
            worker_name = current_task.request.hostname
            if redis.llen('files_queue') > 0 and redis.lindex('files_queue', 1) is not None:
                next_file = redis.lindex('files_queue', 1).decode('utf-8')
            else:
                next_file = None
            redis.publish('worker_status', json.dumps({'worker': worker_name, 'status': 'processing', 'file': filename, 'next_file': next_file}))
            redis.set(f'worker:{worker_name}', json.dumps({'worker': worker_name, 'status': 'processing', 'file': filename, 'next_file': next_file}))
            file_text = FileReader().read(file_path, filename.split(".")[-1])
            file_tags = f'{' '.join(NLPProcessor().tokenize(file_text))} {user_tags}'
            with InterProcessLock(f'{app.storage_path}/storage/index/whoosh.lock'):
                Whoosh().add_document(filename, file_text, folder_id, file_tags, file_id)
            database_file = FICHIER.query.get(file_id)
            database_file.est_Indexe_Fichier = 1
            db.session.commit()
            FileReader().screenshot(file_path, filename.split(".")[-1], folder_id, file_id)
            date_str = file['date_Fichier'].split(':')[0] + ':' + file['date_Fichier'].split(':')[1]
            file['date_Fichier'] = datetime.strptime(date_str, '%d/%m/%Y %H:%M').strftime('%d/%m/%Y %H:%M')
            redis.publish('file_processed', json.dumps({'filename': filename, 'folder_id': folder_id, 'file_id': file_id, 'user': current_user, 'file': file, 'folder': folder, 'action': action}))
        except Exception as _:
            with InterProcessLock(f'{app.storage_path}/storage/index/whoosh.lock'):
                Whoosh().delete_document(file_id)
            database_file = FICHIER.query.get(file_id)
            db.session.delete(database_file)
            db.session.commit()
            os.remove(file_path)
        finally:
            redis.lpop('files_queue')
            redis.publish('worker_status', json.dumps({'worker': worker_name, 'status': 'idle', 'file': None, 'next_file': None}))
            redis.publish('process_status', json.dumps({}))
            redis.delete(f'worker:{worker_name}')

@celery.task(name='app.tasks.verify_index')
def verify_index(current_user_dict):
    app = create_app(is_worker=True)
    with app.app_context():
        with InterProcessLock(f"{app.storage_path}/storage/index/whoosh.lock"):
            whoosh_documents = Whoosh().get_all_documents()
        database_documents = FICHIER.query.all()
        for whoosh_document in whoosh_documents:
            if str(whoosh_document["id"]) not in [
                str(database_document.id_Fichier)
                for database_document in database_documents
            ]:
                Whoosh().delete_document(whoosh_document["id"])
        for database_document in database_documents:
            file_path = os.path.join(
                app.storage_path,
                "storage",
                "files",
                str(database_document.id_Dossier),
                f"{database_document.id_Fichier}.{database_document.extension_Fichier}",
            )
            if os.path.exists(file_path):
                with InterProcessLock(f"{app.storage_path}/storage/index/whoosh.lock"):
                    if not Whoosh().document_exists(str(database_document.id_Fichier)):
                        process_file.apply_async(
                            args=[
                                os.path.join(
                                    app.storage_path,
                                    "storage",
                                    "files",
                                    str(database_document.id_Dossier),
                                    f"{database_document.id_Fichier}.{database_document.extension_Fichier}",
                                ),
                                database_document.nom_Fichier,
                                str(database_document.id_Dossier),
                                str(database_document.id_Fichier),
                                "",
                                current_user_dict,
                                database_document.to_dict(),
                                database_document.DOSSIER_.to_dict(),
                                False,
                            ]
                        )
            else:
                with InterProcessLock(f"{app.storage_path}/storage/index/whoosh.lock"):
                    Whoosh().delete_document(str(database_document.id_Fichier))
                db.session.delete(database_document)
                db.session.commit()
        redis.publish('index_verification_success', json.dumps({'message': 'La vérification de l\'index a été effectuée avec succès.',
                                                                'user': current_user_dict['id_Utilisateur']}))