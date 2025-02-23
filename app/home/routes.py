from app.home import bp
from flask_login import login_required, current_user
from flask import render_template, jsonify, request, current_app
from app.models.favoris import FAVORIS
from app.models.fichier import FICHIER
from app.models.lien import LIEN
from app.models.a_recherche import A_RECHERCHE
from app.forms.search_form import SearchForm
from datetime import datetime
from app.models.dossier import DOSSIER
from app.utils import Whoosh, check_notitications
from app.decorators import active_required
from app.extensions import socketio, db
from fasteners import InterProcessLock
from flask_socketio import join_room


@bp.route("/", methods=["GET", "POST"])
@login_required
@active_required
def home():
    """
    Renders the home page.

    Retrieves the favorite files and user researches for the current user.
    Initializes a search form and handles form submission.
    If the form is submitted successfully, adds the user's research to the database
    and redirects to the search page with the search query.
    Renders the home page template with the necessary data.

    Returns:
        The rendered home page template.
    """
    form = SearchForm()

    query = ""
    whoosh = Whoosh()
    form = SearchForm()
    if form.validate_on_submit():
        add_research(current_user.id_Utilisateur, form.search.data)
        query = form.search.data
    results = whoosh.search(query)
    results = create_rendered_list(results)
    favorite_files = get_files_favoris(current_user.id_Utilisateur)
    researches = get_user_researches(current_user.id_Utilisateur)
    links = db.session.query(LIEN).order_by(LIEN.date_Lien).all()
    return render_template(
        "home/index.html",
        is_authenticated=True,
        is_admin=current_user.is_admin(),
        has_notifications=check_notitications(),
        favorite_files=favorite_files,
        researches=researches,
        links=links,
        folders=results,
        query=query,
        form=form,
        title="Accueil" if not query else query,
        user_id=current_user.id_Utilisateur,
    )


@bp.route("/favori/<int:id_file>", methods=["POST", "DELETE"])
@login_required
def favorize(id_file):
    """
    Favorize or unfavorize a file for the current user.

    Args:
        id_file (int): The ID of the file to favorize or unfavorize.

    Returns:
        dict: A JSON response indicating the status of the operation.
            The response will have a 'status' key with the value 'ok'.
    """
    try:
        if db.session.query(FICHIER).filter_by(id_Fichier=id_file).first() is None:
                return jsonify({"error": "Ce fichier n'existe pas."}), 500
        if request.method == "POST":
            if not current_user.est_Actif_Utilisateur:
                return jsonify({"error": "Vous ne pouvez pas ajouter un favori, votre compte est desactivé."}), 500
            db.session.execute(
                FAVORIS.insert().values(
                    id_Fichier=id_file, id_Utilisateur=current_user.id_Utilisateur
                )
            )
        else:
            if not current_user.est_Actif_Utilisateur:
                return jsonify({"error": "Vous ne pouvez pas supprimer un favori, votre compte est desactivé."}), 500
            db.session.query(FAVORIS).filter(
                FAVORIS.c.id_Fichier == id_file,
                FAVORIS.c.id_Utilisateur == current_user.id_Utilisateur,
            ).delete()
        db.session.commit()
        return jsonify({"file": id_file}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


def get_files_favoris(user_id):
    """
    Retrieve the files favorited by a user.

    Args:
        user_id (int): The ID of the user.

    Returns:
        list: A list of files favorited by the user.
    """
    files = (
        db.session.query(FICHIER)
        .join(FAVORIS)
        .filter(FAVORIS.c.id_Utilisateur == user_id)
        .all()
    )
    return files


def get_user_researches(user_id):
    """
    Retrieve the researches made by a user.

    Args:
        user_id (int): The ID of the user.

    Returns:
        list: A list of researches made by the user.
    """
    researches = (
        db.session.query(A_RECHERCHE)
        .filter(A_RECHERCHE.id_Utilisateur == user_id)
        .order_by(A_RECHERCHE.datetime_Recherche.desc())
        .limit(8)
        .all()
    )
    return researches


def add_research(user_id, search):
    """
    Add a research to the database.

    Args:
        user_id (int): The ID of the user.
        search (str): The search query.
    """
    research = A_RECHERCHE.query.filter_by(
        id_Utilisateur=user_id, champ_Recherche=search
    ).first()
    if research:
        research.datetime_Recherche = datetime.now()
    else:
        research = A_RECHERCHE(
            id_Utilisateur=user_id,
            champ_Recherche=search,
            datetime_Recherche=datetime.now(),
        )
        db.session.add(research)
    db.session.commit()
    db.session.commit()


def create_folder_dict(folder, files):
    """
    Create a dictionary representation of a folder.

    Args:
        folder (Folder): The folder object.
        files (list): A list of file objects.

    Returns:
        dict: A dictionary representation of the folder, including its name, files, color, id, and subfolders.
    """
    files_in_folder = [
        result for result in files if result["path"] == (str(folder.id_Dossier))
    ]
    subfolders = recursive_subfolder(folder, files)
    return {
        "name": folder.nom_Dossier,
        "files": files_in_folder,
        "color": folder.couleur_Dossier,
        "id": folder.id_Dossier,
        "subfolder": subfolders,
    }


def create_rendered_list(results):
    """
    Create a rendered list of folders and their associated results.

    Args:
        results (list): A list of results.

    Returns:
        list: A list of dictionaries representing folders and their associated results.
    """
    folders = db.session.query(DOSSIER).order_by(DOSSIER.priorite_Dossier).all()
    folders_root = [
        folder for folder in folders if folder.DOSSIER == [] and is_accessible(folder)
    ]
    return [create_folder_dict(folder, results) for folder in folders_root]


def recursive_subfolder(folder, files):
    """
    Recursively searches for subfolders in the given folder and creates a list of dictionaries
    containing information about each subfolder.

    Args:
        folder (str): The path of the folder to search for subfolders.
        files (list): A list of files to include in the dictionaries.

    Returns:
        list: A list of dictionaries containing information about each subfolder.
    """
    return [
        create_folder_dict(subfolder, files)
        for subfolder in folder.DOSSIER_
        if is_accessible(subfolder)
    ]


def is_accessible(folder):
    """
    Check if the current user has access to the given folder.

    Args:
        folder (Folder): The folder to check.

    Returns:
        bool: True if the user has access to the folder, False otherwise.
    """
    return any(current_user.id_Role == role.id_Role for role in folder.ROLE)

@socketio.on("join", namespace="/home")
def on_join(data):
    """
    Join a room.

    Args:
        data (dict): A dictionary containing the room information.

    Returns:
        None
    """
    join_room(data["room"])

@socketio.on("search_files", namespace="/home")
def search_files(data):
    """
    Search files based on the provided query and folder ID.

    Args:
        data (dict): A dictionary containing the search query and folder ID.

    Returns:
        None
    """
    search_query = data.get("query")
    with InterProcessLock(f"{current_app.storage_path}/storage/index/whoosh.lock"):
        search_results = Whoosh().search(search_query, path=f'{data.get("folderId")}')
        search_results = [result["id"] for result in search_results]
    socketio.emit(
        "search_results",
        {
            "query": search_query,
            "results": search_results,
            "folderId": data.get("folderId"),
        },
        namespace="/home",
        room=f"user_{current_user.id_Utilisateur}",
    )

@socketio.on("add_tag", namespace="/home")
def add_tag(data):
    """
    Add a tag to a file.

    Args:
        data (dict): A dictionary containing the file ID and tag.

    Returns:
        None
    """
    file_id = data.get("fileId")
    tag = data.get("tag")
    with InterProcessLock(f"{current_app.storage_path}/storage/index/whoosh.lock"):
        Whoosh().add_tag(file_id, tag)
    socketio.emit(
        "tag_added",
        {"fileId": file_id, "tag": tag},
        namespace="/home",
        room=f"user_{current_user.id_Utilisateur}",
    )
    