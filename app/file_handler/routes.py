import os
from app.file_handler import bp
from flask import send_from_directory, abort, current_app, request, send_file
from app.models.fichier import FICHIER
from flask_login import current_user, login_required
from app.extensions import socketio, db
from app.models.favoris import FAVORIS
from app.utils import FileDownloader
from app.decorators import admin_required, active_required
from threading import Timer
from flask_socketio import join_room


@bp.route("/classeur/<int:folder_id>/fichier/<int:file_id>", methods=["GET"])
@login_required
@active_required
def file(folder_id, file_id):
    file = FICHIER.query.get(file_id)
    as_attachment = request.args.get("as_attachment", default=False, type=bool)
    as_screenshot = request.args.get("as_screenshot", default=False, type=bool)
    if file is None:
        return abort(404)
    if file.DOSSIER_.id_Dossier != folder_id:
        return abort(404)
    if not any(current_user.id_Role == role.id_Role for role in file.DOSSIER_.ROLE):
        return abort(403)
    if not as_screenshot:
        return send_from_directory(
            f"{current_app.storage_path}/storage/files/{folder_id}",
            f"{file.id_Fichier}.{file.extension_Fichier}",
            as_attachment=as_attachment,
            download_name=file.nom_Fichier,
        )
    else:
        return send_from_directory(
            f"{current_app.storage_path}/storage/screenshots/{folder_id}",
            f"{file.id_Fichier}.png",
            as_attachment=False,
        )

@socketio.on("join", namespace="/file_handler")
def on_join(data):
    """
    Join a room.

    Args:
        data (dict): A dictionary containing the room information.

    Returns:
        None
    """
    join_room(data["room"])

@socketio.on("get_files_details", namespace="/file_handler")
def get_files_details(data):
    """
    Retrieves details of files based on the provided data.

    Args:
        data (dict): A dictionary containing the files' IDs.

    Returns:
        None

    Raises:
        None
    """
    files_id = data["files"]
    files_id = [
        file_id
        for file_id in files_id
        if db.session.query(FICHIER).filter(FICHIER.id_Fichier == file_id).first()
        is not None
    ]
    favoris = (
        db.session.query(FAVORIS.c.id_Fichier)
        .filter(FAVORIS.c.id_Utilisateur == current_user.id_Utilisateur)
        .all()
    )
    favoris_ids = [favori.id_Fichier for favori in favoris]
    files = []
    for file_id in files_id:
        file = db.session.query(FICHIER).filter(FICHIER.id_Fichier == file_id).first()
        dict_file = file.to_dict()
        dict_file["id_Dossier"] = file.DOSSIER_.id_Dossier
        dict_file["is_favorite"] = file.id_Fichier in favoris_ids
        dict_file["id_Utilisateur"] = str(file.id_Utilisateur)
        files.append(dict_file)
    socketio.emit(
        "files_details",
        {"files": files, "files_id": files_id},
        namespace="/file_handler",
        room=f"user_{current_user.id_Utilisateur}",
    )


@bp.route("/download/archive", methods=["POST"])
@login_required
@active_required
@admin_required
def download_archive():
    zip_path = FileDownloader().create_zip(request.json["fileIds"])
    delete_file_after_delay(43200, zip_path)
    return send_file(zip_path, "archive.zip", as_attachment=True)


def delete_file_after_delay(delay, path):
    def delete_file():
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

    Timer(delay, delete_file).start()
