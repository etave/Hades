from datetime import datetime
import os
import json
import uuid
from base64 import b64decode
from app.extensions import redis, socketio, db
from app.administration import bp
from app.tasks import process_file, verify_index
from unidecode import unidecode
from flask import render_template, request, current_app, jsonify
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename
from flask_socketio import join_room
from app.decorators import admin_required, active_required
from app.models.dossier import DOSSIER
from app.models.sous_dossier import SOUS_DOSSIER
from app.models.fichier import FICHIER
from app.models.utilisateur import UTILISATEUR
from app.models.a_acces import A_ACCES
from app.models.role import ROLE
from app.models.lien import LIEN
from app.models.a_recherche import A_RECHERCHE
from app.models.favoris import FAVORIS
from app.utils import Whoosh, check_notitications
from fasteners import InterProcessLock
from app.mail import send_deactivation_email, send_delete_email


@bp.route("/")
@login_required
@active_required
@admin_required
def administration():
    all_folders = DOSSIER.query.all()
    all_root_folders = [folder for folder in all_folders if folder.DOSSIER == []]
    all_root_folders.sort(key=lambda x: x.priorite_Dossier)
    all_users = UTILISATEUR.query.all()
    all_users = [user for user in all_users if user.id_Role is not None]
    if current_user.id_Role == 2:
        all_users = [
            user
            for user in all_users
            if user.id_Role != current_user.id_Role and user.id_Role != 1
        ]
    all_users = [
        user for user in all_users if user.id_Utilisateur != current_user.id_Utilisateur
    ]
    all_roles = ROLE.query.all()
    all_links = LIEN.query.all()
    all_links = sorted(all_links, key=lambda x: x.nom_Lien.lower())
    return render_template(
        "administration/index.html",
        folders=all_root_folders,
        users=all_users,
        roles=all_roles,
        links=all_links,
        is_admin=True,
        is_authenticated=True,
        has_notifications=check_notitications(),
        title="Administration",
    )


@bp.route("/upload", methods=["POST"])
@login_required
@active_required
@admin_required
def upload():
    json_data = request.get_json()
    folder_id = json_data.get("folderId")
    folder = DOSSIER.query.get(folder_id)
    if folder is None:
        return jsonify({"error": "Le classeur sélectionné n'existe pas."}), 404
    file_data = json_data.get("data")
    filename = unidecode(secure_filename(json_data.get("filename"))).lower()
    existing_file = FICHIER.query.filter_by(nom_Fichier=filename).first()
    force = json_data.get("force")
    if existing_file is not None:
        if not existing_file.est_Indexe_Fichier:
            return (
                jsonify(
                    {
                        "filename": filename,
                        "existingFolder": existing_file.DOSSIER_.nom_Dossier,
                        "existingFileAuthorFirstName": existing_file.AUTEUR.prenom_Utilisateur,
                        "existingFileAuthorLastName": existing_file.AUTEUR.nom_Utilisateur,
                        "existingFileDate": existing_file.date_Fichier.strftime(
                            "%d/%m/%Y à %H:%M"
                        ),
                    }
                ),
                422,
            )
        if force:
            delete_file(str(existing_file.id_Fichier))
        else:
            return (
                jsonify(
                    {
                        "filename": filename,
                        "existingFolder": existing_file.DOSSIER_.nom_Dossier,
                        "attemptedFolder": DOSSIER.query.get(folder_id).nom_Dossier,
                        "existingFileAuthorFirstName": existing_file.AUTEUR.prenom_Utilisateur,
                        "existingFileAuthorLastName": existing_file.AUTEUR.nom_Utilisateur,
                        "existingFileDate": existing_file.date_Fichier.strftime(
                            "%d/%m/%Y à %H:%M"
                        ),
                    }
                ),
                409,
            )
    user_tags = unidecode(
        " ".join(json_data.get("tags").replace(" ", ";").split(";"))
    ).lower()
    storage_directory = os.path.join(current_app.storage_path, "storage", "files")
    if not os.path.exists(f"{storage_directory}/{folder_id}"):
        os.makedirs(f"{storage_directory}/{folder_id}")
    file = FICHIER(
        id_Dossier=folder_id,
        nom_Fichier=filename,
        extension_Fichier=filename.split(".")[-1],
        date_Fichier=datetime.now(),
        id_Utilisateur=current_user.id_Utilisateur,
    )
    db.session.add(file)
    db.session.commit()
    file_path = os.path.join(
        storage_directory, folder_id, f"{file.id_Fichier}.{file.extension_Fichier}"
    )
    current_user_dict = current_user.to_dict_secure()
    file_dict = file.to_dict()
    file_dict.update({"id_Utilisateur": str(file.id_Utilisateur)})
    with open(file_path, "wb") as new_file:
        new_file.write(b64decode(file_data.split(",")[1]))
    process_file.apply_async(
        args=[
            file_path,
            filename,
            folder_id,
            str(file.id_Fichier),
            user_tags,
            current_user_dict,
            file_dict,
            file.DOSSIER_.to_dict(),
            force,
        ]
    )
    redis.rpush(
        "files_queue", json.dumps({"file_id": file.id_Fichier, "filename": filename})
    )
    file_dict = file.to_dict()
    file_dict.update(
        {"old_file_id": existing_file.id_Fichier if existing_file is not None else None}
    )
    file_dict.update(
        {
            "old_folder_id": (
                existing_file.id_Dossier if existing_file is not None else None
            )
        }
    )
    return jsonify(file_dict), 200


@socketio.on("join", namespace="/administration")
def on_join(data):
    join_room(data["room"])


@socketio.on("connect", namespace="/administration")
def connect():
    if not (current_user.is_authenticated and current_user.is_admin):
        return
    workers = redis.keys("worker:*") if len(redis.keys("worker:*")) > 0 else []
    for worker in workers:
        socketio.emit(
            "worker_status",
            json.loads(redis.get(worker).decode("utf-8")),
            namespace="/administration",
        )

    socketio.emit(
        "total_files",
        FICHIER.query.count(),
        namespace="/administration",
    )
    socketio.emit(
        "total_files_processed",
        FICHIER.query.filter(FICHIER.est_Indexe_Fichier == 1).count(),
        namespace="/administration",
    )


@socketio.on("search_files", namespace="/administration")
def search_files(data):
    search_query = data.get("query")
    with InterProcessLock(f"{current_app.storage_path}/storage/index/whoosh.lock"):
        search_results = Whoosh().search(search_query, path=f'{data.get("folderId")}')
    socketio.emit(
        "search_results",
        search_results,
        namespace="/administration",
        room=f"user_{current_user.id_Utilisateur}",
    )


@socketio.on("update_user_role", namespace="/administration")
def update_user_role(data):
    if not current_user.est_Actif_Utilisateur:
        socketio.emit(
            "user_role_not_updated",
            {
                **data,
                "error": "Votre compte est désactivé, vous ne pouvez pas modifier les rôles des utilisateurs.",
            },
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    if current_user.id_Utilisateur == data.get("userId"):
        socketio.emit(
            "user_role_not_updated",
            {**data, "error": "Vous ne pouvez pas modifier votre propre rôle."},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    if current_user.id_Role != 1 and current_user.id_Role != 2:
        socketio.emit(
            "user_role_not_updated",
            {
                **data,
                "error": "Vous n'avez pas l'autorisation de modifier les rôles des utilisateurs.",
            },
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    user_id = data.get("userId")
    role_id = data.get("roleId")
    user = UTILISATEUR.query.get(uuid.UUID(user_id))
    if current_user.id_Role == 1 and role_id in ["1", "2", "3", "4"]:
        user.id_Role = role_id
    elif current_user.id_Role == 2 and role_id in ["3", "4"]:
        user.id_Role = role_id
    else:
        data["roleId"] = user.id_Role
        socketio.emit(
            "user_role_not_updated",
            {
                **data,
                "error": "Vous n'avez pas l'autorisation d'affecter ce rôle à cet utilisateur.",
            },
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    db.session.commit()
    socketio.emit(
        "user_role_updated",
        {**data, "message": "Le rôle de l'utilisateur a été modifié avec succès."},
        namespace="/administration",
        room=f"user_{current_user.id_Utilisateur}",
    )


@socketio.on("update_user_status", namespace="/administration")
def update_user_status(data):
    if not current_user.est_Actif_Utilisateur:
        socketio.emit(
            "user_status_not_updated",
            {
                **data,
                "error": "Votre compte est désactivé, vous ne pouvez pas modifier les statuts des utilisateurs.",
            },
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    if current_user.id_Utilisateur == data.get("userId"):
        socketio.emit(
            "user_status_not_updated",
            {**data, "error": "Vous ne pouvez pas modifier votre propre statut."},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    if current_user.id_Role != 1 and current_user.id_Role != 2:
        socketio.emit(
            "user_status_not_updated",
            {
                **data,
                "error": "Vous n'avez pas l'autorisation de modifier les statuts des utilisateurs.",
            },
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    user_id = data.get("userId")
    user = UTILISATEUR.query.get(uuid.UUID(user_id))
    if current_user.id_Role == 1 and user.id_Role in [1, 2, 3, 4]:
        user.est_Actif_Utilisateur = not user.est_Actif_Utilisateur
    elif current_user.id_Role == 2 and user.id_Role in [3, 4]:
        user.est_Actif_Utilisateur = not user.est_Actif_Utilisateur
    else:
        data["status"] = user.est_Actif_Utilisateur
        socketio.emit(
            "user_status_not_updated",
            {
                **data,
                "error": "Vous n'avez pas l'autorisation de modifier le statut de cet utilisateur.",
            },
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    db.session.commit()
    socketio.emit(
        "user_status_updated",
        {**data, "message": "Le statut de l'utilisateur a été modifié avec succès."},
        namespace="/administration",
        room=f"user_{current_user.id_Utilisateur}",
    )
    if not user.est_Actif_Utilisateur:
        try:
            send_deactivation_email(user.email_Utilisateur)
        except Exception as _:
            socketio.emit(
                "user_email_error",
                {
                    **data,
                    "error": "Le statut de l'utilisateur à bien été désactivé, mais l'email de notification n'a pas pu être envoyé.",
                },
                namespace="/administration",
                room=f"user_{current_user.id_Utilisateur}",
            )


@socketio.on("delete_user", namespace="/administration")
def delete_user(data):
    if not current_user.est_Actif_Utilisateur:
        socketio.emit(
            "user_not_deleted",
            {
                **data,
                "error": "Votre compte est désactivé, vous ne pouvez pas supprimer d'utilisateurs.",
            },
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    if current_user.id_Utilisateur == data.get("userId"):
        socketio.emit(
            "user_not_deleted",
            {**data, "error": "Vous ne pouvez pas supprimer votre propre compte."},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    if current_user.id_Role != 1 and current_user.id_Role != 2:
        socketio.emit(
            "user_not_deleted",
            {
                **data,
                "error": "Vous n'avez pas l'autorisation de supprimer des utilisateurs.",
            },
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    user_id = data.get("userId")
    user = UTILISATEUR.query.get(uuid.UUID(user_id))
    try:
        if current_user.id_Role == 1 and user.id_Role in [1, 2, 3, 4]:
            delete_user_database(user_id)
        elif current_user.id_Role == 2 and user.id_Role in [3, 4]:
            delete_user_database(user_id)
        else:
            socketio.emit(
                "user_not_deleted",
                {
                    **data,
                    "error": "Vous n'avez pas l'autorisation de supprimer cet utilisateur.",
                },
                namespace="/administration",
                room=f"user_{current_user.id_Utilisateur}",
            )
            return
    except Exception as e:
        db.session.rollback()
        socketio.emit(
            "user_not_deleted",
            {**data, "error": str(e)},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    socketio.emit(
        "user_deleted",
        {**data, "message": "L'utilisateur a été supprimé avec succès."},
        namespace="/administration",
        room=f"user_{current_user.id_Utilisateur}",
    )
    try:
        send_delete_email(user.email_Utilisateur)
    except Exception as _:
        socketio.emit(
            "user_email_error",
            {
                **data,
                "error": "L'utilisateur à bien été supprimé, mais l'email de notification n'a pas pu être envoyé.",
            },
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )


def delete_user_database(user_id):
    user_id = uuid.UUID(user_id)
    files = FICHIER.query.filter_by(id_Utilisateur=user_id).all()
    for file in files:
        file.id_Utilisateur = current_user.id_Utilisateur
    links = LIEN.query.filter_by(id_Utilisateur=user_id).all()
    for link in links:
        link.id_Utilisateur = current_user.id_Utilisateur
    associated_searches = A_RECHERCHE.query.filter_by(id_Utilisateur=user_id).all()
    for search in associated_searches:
        db.session.delete(search)
    favorites = (
        db.session.query(FAVORIS).filter(FAVORIS.c.id_Utilisateur == user_id).all()
    )
    for favorite in favorites:
        db.session.delete(favorite)
    user = UTILISATEUR.query.get(user_id)
    db.session.delete(user)
    db.session.commit()


@socketio.on("create_folder", namespace="/administration")
def create_folder(data):
    if not current_user.est_Actif_Utilisateur:
        socketio.emit(
            "folder_not_created",
            {
                "error": "Votre compte est désactivé, vous ne pouvez pas créer de classeurs."
            },
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    if current_user.id_Role != 1 and current_user.id_Role != 2:
        socketio.emit(
            "folder_not_created",
            {"error": "Vous n'avez pas l'autorisation de créer des classeurs."},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    folder_name = data.get("folderName")
    parent_folder_id = data.get("parentFolderId")
    folder_roles = data.get("folderRoles", [2, 3, 4])
    folder_color = data.get("folderColor")
    folder_priority = data.get("folderPriority")
    folders_to_update = (
        DOSSIER.query.filter(DOSSIER.priorite_Dossier >= folder_priority)
        .filter(DOSSIER.id_Dossier != 9)
        .all()
    )
    for folder_to_update in folders_to_update:
        folder_to_update.priorite_Dossier += 1
    folder = DOSSIER(
        nom_Dossier=folder_name,
        priorite_Dossier=folder_priority,
        couleur_Dossier=folder_color,
    )
    db.session.add(folder)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        socketio.emit(
            "folder_not_created",
            {"error": str(e)},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    try:
        db.session.execute(
            A_ACCES.insert().values(id_Role=1, id_Dossier=folder.id_Dossier)
        )
        for role in folder_roles:
            db.session.execute(
                A_ACCES.insert().values(id_Role=role, id_Dossier=folder.id_Dossier)
            )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        db.session.delete(folder)
        db.session.commit()
        socketio.emit(
            "folder_not_created",
            {"error": str(e)},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    try:
        if parent_folder_id != 0:
            db.session.execute(
                SOUS_DOSSIER.insert().values(
                    id_Dossier_Parent=parent_folder_id,
                    id_Dossier_Enfant=folder.id_Dossier,
                )
            )
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        db.session.execute(
            A_ACCES.delete()
            .where(A_ACCES.c.id_Role == 1)
            .where(A_ACCES.c.id_Dossier == folder.id_Dossier)
        )
        for role in folder_roles:
            db.session.execute(
                A_ACCES.delete()
                .where(A_ACCES.c.id_Role == role)
                .where(A_ACCES.c.id_Dossier == folder.id_Dossier)
            )
        db.session.delete(folder)
        db.session.commit()
        socketio.emit(
            "folder_not_created",
            {"error": str(e)},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    socketio.emit(
        "folder_created",
        {
            "folderId": folder.id_Dossier,
            "folderName": folder_name,
            "folderColor": folder.couleur_Dossier,
            "parentFolderId": parent_folder_id,
        },
        namespace="/administration",
        room=f"user_{current_user.id_Utilisateur}",
    )


@socketio.on("modify_folder", namespace="/administration")
def modify_folder(data):
    if not current_user.est_Actif_Utilisateur:
        socketio.emit(
            "folder_not_modified",
            {
                "error": "Votre compte est désactivé, vous ne pouvez pas modifier de classeurs."
            },
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    if current_user.id_Role != 1 and current_user.id_Role != 2:
        socketio.emit(
            "folder_not_modified",
            {"error": "Vous n'avez pas l'autorisation de modifier des classeurs."},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    folder_id = data.get("folderId")
    folder_name = data.get("folderName")
    parent_folder_id = data.get("parentFolderId")
    folder_roles = data.get("folderRoles", [2, 3, 4])
    folder_priority = data.get("folderPriority")
    folder_color = data.get("folderColor")
    folder = DOSSIER.query.get(folder_id)
    folder.nom_Dossier = folder_name
    folder.couleur_Dossier = folder_color
    if folder.priorite_Dossier != int(folder_priority):
        if int(folder_priority) > folder.priorite_Dossier:
            folders_to_update = (
                DOSSIER.query.filter(DOSSIER.priorite_Dossier > folder.priorite_Dossier)
                .filter(DOSSIER.priorite_Dossier <= int(folder_priority))
                .filter(DOSSIER.id_Dossier != 9)
                .all()
            )
            for folder_to_update in folders_to_update:
                folder_to_update.priorite_Dossier -= 1
        else:
            folders_to_update = (
                DOSSIER.query.filter(DOSSIER.priorite_Dossier >= int(folder_priority))
                .filter(DOSSIER.priorite_Dossier < folder.priorite_Dossier)
                .filter(DOSSIER.id_Dossier != 9)
                .all()
            )
            for folder_to_update in folders_to_update:
                folder_to_update.priorite_Dossier += 1
        folder.priorite_Dossier = folder_priority
    try:
        if parent_folder_id == folder_id:
            socketio.emit(
                "folder_not_modified",
                {"error": "Un classeur ne peut pas être son propre parent."},
                namespace="/administration",
                room=f"user_{current_user.id_Utilisateur}",
            )
            return
        if parent_folder_id != 0:
            db.session.execute(
                SOUS_DOSSIER.delete().where(
                    SOUS_DOSSIER.c.id_Dossier_Enfant == folder_id
                )
            )
            db.session.execute(
                SOUS_DOSSIER.insert().values(
                    id_Dossier_Parent=parent_folder_id, id_Dossier_Enfant=folder_id
                )
            )
            db.session.commit()
        else:
            db.session.execute(
                SOUS_DOSSIER.delete().where(
                    SOUS_DOSSIER.c.id_Dossier_Enfant == folder_id
                )
            )
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        socketio.emit(
            "folder_not_modified",
            {"error": str(e)},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    try:
        db.session.execute(A_ACCES.delete().where(A_ACCES.c.id_Dossier == folder_id))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        socketio.emit(
            "folder_not_modified",
            {"error": str(e)},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    try:
        db.session.execute(A_ACCES.insert().values(id_Role=1, id_Dossier=folder_id))
        for role in folder_roles:
            db.session.execute(
                A_ACCES.insert().values(id_Role=role, id_Dossier=folder_id)
            )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        socketio.emit(
            "folder_not_modified",
            {"error": str(e)},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    db.session.commit()
    socketio.emit(
        "folder_modified",
        {"folderId": folder_id, "folderName": folder_name, "folderColor": folder_color},
        namespace="/administration",
        room=f"user_{current_user.id_Utilisateur}",
    )


@socketio.on("delete_folder", namespace="/administration")
def delete_folder(data):
    if not current_user.est_Actif_Utilisateur:
        socketio.emit(
            "folder_not_deleted",
            {
                "error": "Votre compte est désactivé, vous ne pouvez pas supprimer de classeurs."
            },
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    if current_user.id_Role != 1 and current_user.id_Role != 2:
        socketio.emit(
            "folder_not_deleted",
            {"error": "Vous n'avez pas l'autorisation de supprimer des classeurs."},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    folder = DOSSIER.query.get(data.get("folderId"))
    if folder.id_Dossier == 9:
        socketio.emit(
            "folder_not_deleted",
            {"error": "Le classeur d'archive ne peut pas être supprimé."},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    if len(folder.DOSSIER_) > 0:
        socketio.emit(
            "folder_not_deleted",
            {"error": "Le classeur contient des sous-classeurs."},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    if len(folder.FICHIER) > 0:
        socketio.emit(
            "folder_not_deleted",
            {"error": "Le classeur contient des fichiers."},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    try:
        db.session.execute(
            SOUS_DOSSIER.delete().where(
                SOUS_DOSSIER.c.id_Dossier_Enfant == folder.id_Dossier
            )
        )
        db.session.execute(
            SOUS_DOSSIER.delete().where(
                SOUS_DOSSIER.c.id_Dossier_Parent == folder.id_Dossier
            )
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        socketio.emit(
            "folder_not_deleted",
            {"error": str(e)},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    try:
        db.session.execute(
            A_ACCES.delete().where(A_ACCES.c.id_Dossier == folder.id_Dossier)
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        socketio.emit(
            "folder_not_deleted",
            {"error": str(e)},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    deleted_priority = folder.priorite_Dossier
    db.session.delete(folder)
    db.session.commit()
    folders_to_update = (
        DOSSIER.query.filter(DOSSIER.priorite_Dossier > deleted_priority)
        .filter(DOSSIER.id_Dossier != 9)
        .all()
    )
    for folder_to_update in folders_to_update:
        folder_to_update.priorite_Dossier -= 1
    db.session.commit()
    socketio.emit(
        "folder_deleted",
        {"folderId": folder.id_Dossier},
        namespace="/administration",
        room=f"user_{current_user.id_Utilisateur}",
    )


@socketio.on("archive_folders", namespace="/administration")
def archive_folders(data):
    if not current_user.est_Actif_Utilisateur:
        socketio.emit(
            "folders_not_archived",
            {
                "error": "Votre compte est désactivé, vous ne pouvez pas archiver de classeurs."
            },
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    if current_user.id_Role != 1 and current_user.id_Role != 2:
        socketio.emit(
            "folders_not_archived",
            {"error": "Vous n'avez pas l'autorisation d'archiver des classeurs."},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    folder_ids = data.get("folderIds")
    try:
        for folder_id in folder_ids:
            database_folder = DOSSIER.query.get(folder_id)
            if folder_id == "9":
                pass
            elif (
                database_folder.DOSSIER != []
                and database_folder.DOSSIER[0].id_Dossier == 0
            ):
                pass
            elif (
                database_folder.DOSSIER != []
                and str(database_folder.DOSSIER[0].id_Dossier) in folder_ids
            ):
                pass
            else:
                if database_folder.DOSSIER != []:
                    db.session.execute(
                        SOUS_DOSSIER.delete().where(
                            SOUS_DOSSIER.c.id_Dossier_Enfant == folder_id
                        )
                    )
                db.session.execute(
                    SOUS_DOSSIER.insert().values(
                        id_Dossier_Parent=9, id_Dossier_Enfant=folder_id
                    )
                )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        socketio.emit(
            "folders_not_archived",
            {"error": str(e)},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    socketio.emit(
        "folders_archived",
        {"folderIds": folder_ids},
        namespace="/administration",
        room=f"user_{current_user.id_Utilisateur}",
    )


@socketio.on("delete_files", namespace="/administration")
def delete_files(data):
    if not current_user.est_Actif_Utilisateur:
        socketio.emit(
            "files_not_deleted",
            {
                "error": "Votre compte est désactivé, vous ne pouvez pas supprimer de fichiers."
            },
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    if current_user.id_Role == 4:
        socketio.emit(
            "files_not_deleted",
            {"error": "Vous n'avez pas l'autorisation de supprimer des fichiers."},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    file_ids = data.get("fileIds")
    for file_id in file_ids:
        if not FICHIER.query.get(file_id).est_Indexe_Fichier:
            socketio.emit(
                "files_not_deleted",
                {
                    "error": "Un ou plusieurs fichiers sélectionnés sont en cours de traitement. Veuillez réessayer ultérieurement."
                },
                namespace="/administration",
                room=f"user_{current_user.id_Utilisateur}",
            )
            return
    try:
        file_paths = []
        with InterProcessLock(f"{current_app.storage_path}/storage/index/whoosh.lock"):
            Whoosh().delete_documents(file_ids)
        for file_id in file_ids:
            database_file = FICHIER.query.get(file_id)
            db.session.delete(database_file)
            file_paths.append(
                os.path.join(
                    current_app.storage_path,
                    "storage",
                    "files",
                    str(database_file.id_Dossier),
                    f"{file_id}.{database_file.extension_Fichier}",
                )
            )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        socketio.emit(
            "files_not_deleted",
            {"error": str(e)},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    for file_path in file_paths:
        if os.path.exists(file_path):
            os.remove(file_path)
    socketio.emit(
        "files_deleted",
        {"fileIds": file_ids},
        namespace="/administration",
        room=f"user_{current_user.id_Utilisateur}",
    )


def delete_file(file_id):
    with InterProcessLock(f"{current_app.storage_path}/storage/index/whoosh.lock"):
        Whoosh().delete_document(file_id)
    database_file = FICHIER.query.get(file_id)
    db.session.delete(database_file)
    os.remove(
        os.path.join(
            current_app.storage_path,
            "storage",
            "files",
            str(database_file.id_Dossier),
            f"{file_id}.{database_file.extension_Fichier}",
        )
    )
    db.session.commit()


@socketio.on("delete_link", namespace="/administration")
def delete_link(data):
    if not current_user.est_Actif_Utilisateur:
        socketio.emit(
            "link_not_deleted",
            {
                "error": "Votre compte est désactivé, vous ne pouvez pas supprimer de liens."
            },
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    try:
        link = LIEN.query.get(data.get("linkId"))
        db.session.delete(link)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        socketio.emit(
            "link_not_deleted",
            {"error": str(e)},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    socketio.emit(
        "link_deleted",
        {"linkId": data.get("linkId")},
        namespace="/administration",
        room=f"user_{current_user.id_Utilisateur}",
    )


@socketio.on("create_link", namespace="/administration")
def create_link(data):
    if not current_user.est_Actif_Utilisateur:
        socketio.emit(
            "link_not_created",
            {"error": "Votre compte est désactivé, vous ne pouvez pas créer de liens."},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    link_name = data.get("linkName")
    link_url = data.get("linkUrl")
    link_description = data.get("linkDescription")
    try:
        link = LIEN(
            nom_Lien=link_name,
            lien_Lien=link_url,
            description_Lien=link_description,
            id_Utilisateur=current_user.id_Utilisateur,
        )
        db.session.add(link)
        db.session.commit()
        link_date = link.date_Lien.strftime("%d/%m/%Y à %H:%M")
    except Exception as e:
        db.session.rollback()
        socketio.emit(
            "link_not_created",
            {"error": str(e)},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    socketio.emit(
        "link_created",
        {
            "linkId": link.id_Lien,
            "linkName": link_name,
            "linkUrl": link_url,
            "linkDescription": link_description,
            "linkDate": link_date,
            "linkAuthor": f"{current_user.prenom_Utilisateur} {current_user.nom_Utilisateur}",
        },
        namespace="/administration",
        room=f"user_{current_user.id_Utilisateur}",
    )


@socketio.on("verify_index", namespace="/administration")
def verify_index_socket(data={}):
    if not current_user.est_Actif_Utilisateur:
        socketio.emit(
            "index_not_verified",
            {
                "error": "Votre compte est désactivé, vous ne pouvez pas vérifier l'indexation des fichiers."
            },
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    if current_user.id_Role != 1:
        socketio.emit(
            "index_not_verified",
            {
                "error": "Vous n'avez pas l'autorisation de vérifier l'indexation des fichiers."
            },
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    force = data.get("force", False)
    workers = redis.keys("worker:*") if len(redis.keys("worker:*")) > 0 else []
    for file in redis.lrange("files_queue", 0, -1):
        file = json.loads(file.decode("utf-8"))
        if FICHIER.query.get(file["file_id"]).est_Indexe_Fichier or len(workers) == 0:
            redis.lrem("files_queue", 0, json.dumps(file))
    if redis.llen("files_queue") > 0:
        if not force:
            socketio.emit(
                "index_not_verified_with_options",
                {
                    "error": "Un ou plusieurs fichiers sont en cours de traitement.\nVoulez-vous forcer la vérification de l'indexation (attention, cette action peut générer des doublons si des fichiers sont en cours de traitement) ?",
                },
                namespace="/administration",
                room=f"user_{current_user.id_Utilisateur}",
            )
            return
    verify_index.apply_async(args=[current_user.to_dict_secure()])
    socketio.emit(
        "index_verification_started",
        {"message": "La vérification de l'indexation des fichiers a commencé."},
        namespace="/administration",
        room=f"user_{current_user.id_Utilisateur}",
    )


@socketio.on("transfer_files", namespace="/administration")
def transfer_files(data):
    if not current_user.est_Actif_Utilisateur:
        socketio.emit(
            "files_not_transferred",
            {
                "error": "Votre compte est désactivé, vous ne pouvez pas transférer de fichiers."
            },
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    if current_user.id_Role == 4:
        socketio.emit(
            "files_not_transferred",
            {"error": "Vous n'avez pas l'autorisation de transférer des fichiers."},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    folder_id = data.get("destinationFolder")
    file_ids = data.get("fileIds")
    try:
        for file_id in file_ids:
            if not FICHIER.query.get(file_id).est_Indexe_Fichier:
                socketio.emit(
                    "files_not_transferred",
                    {
                        "error": "Un ou plusieurs fichiers sélectionnés sont en cours de traitement. Veuillez réessayer ultérieurement."
                    },
                    namespace="/administration",
                    room=f"user_{current_user.id_Utilisateur}",
                )
                return
        with InterProcessLock(f"{current_app.storage_path}/storage/index/whoosh.lock"):
            Whoosh().transfer_documents(file_ids, folder_id)
        for file_id in file_ids:
            database_file = FICHIER.query.get(file_id)
            file_path = os.path.join(
                current_app.storage_path,
                "storage",
                "files",
                str(database_file.DOSSIER_.id_Dossier),
                f"{file_id}.{database_file.extension_Fichier}",
            )
            new_file_path = os.path.join(
                current_app.storage_path,
                "storage",
                "files",
                str(folder_id),
                f"{file_id}.{database_file.extension_Fichier}",
            )
            if not os.path.exists(f"{current_app.storage_path}/storage/files/{folder_id}"):
                os.makedirs(f"{current_app.storage_path}/storage/files/{folder_id}")
            os.rename(file_path, new_file_path)
            database_file.id_Dossier = folder_id
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        socketio.emit(
            "files_not_transferred",
            {"error": str(e)},
            namespace="/administration",
            room=f"user_{current_user.id_Utilisateur}",
        )
        return
    socketio.emit(
        "files_transferred",
        {"fileIds": file_ids, "folderId": folder_id},
        namespace="/administration",
        room=f"user_{current_user.id_Utilisateur}",
    )
