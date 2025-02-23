from app.extensions import db
from app.password_reset import bp
from app.models.utilisateur import UTILISATEUR
from flask import current_app, flash, render_template
import json
import uuid
from itsdangerous import URLSafeTimedSerializer
from app.forms.password_reset_form import PasswordResetForm
from datetime import datetime, timedelta
from flask_bcrypt import generate_password_hash
from app.mail import send_reset_password_confirmation


@bp.route("/<string:hash_user_uuid>", methods=["GET", "POST"])
def reinitialisation(hash_user_uuid):
    """
    Reinitializes the password for a user identified by the given UUID.

    Args:
        user_uuid (str): The UUID of the user.

    Returns:
        redirect: A redirect response to the login page.

    Raises:
        None

    """
    form = PasswordResetForm()
    if form.validate_on_submit():
        json_file_path = f"{current_app.storage_path}/storage/password/password.json"
        with open(json_file_path, "r") as json_file:
            data = json.load(json_file)
            user_uuid = dehash_uuid(hash_user_uuid)
            if str(user_uuid) in data:
                user = UTILISATEUR.query.filter_by(id_Utilisateur=uuid.UUID(data[str(user_uuid)]["user_id"])).first()
                date_str = data[str(user_uuid)]["date"]
                date_obj = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S.%f") 
                now = datetime.now()
                # check if the request is still valid
                if now - date_obj > timedelta(minutes=10):
                    flash("La demande de réinitialisation n'est plus valide.", "danger")
                # The request is still valid
                else :
                    password = form.password.data
                    user.mdp_Utilisateur = generate_password_hash(password)
                    try:
                        send_reset_password_confirmation(user.email_Utilisateur)
                        flash("Votre mot de passe a bien été réinitialisé.", "success")
                        db.session.commit()
                    except:
                        flash("Erreur lors de l'envoi de l'email.", "danger")
                        db.session.rollback()
                del data[str(user_uuid)]
                with open(json_file_path, "w") as json_file:
                    json.dump(data, json_file)
            # The user is not found
            else:
                flash("aucun utilisateur trouvé", "danger")
    return render_template("password_reset/index.html", form=form, is_authenticated=False, hash_user_uuid=hash_user_uuid)


def dehash_uuid(hashed_uuid):
    """
    Dehashes a hashed UUID using a URLSafeTimedSerializer.

    Parameters:
    hashed_uuid (str): The hashed UUID to be dehashed.

    Returns:
    str: The dehashed UUID.

    """
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return serializer.loads(hashed_uuid)