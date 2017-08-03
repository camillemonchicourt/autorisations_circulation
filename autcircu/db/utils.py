
import string
import random

import unicodedata

from csv import DictReader

from datetime import datetime

from sqlalchemy.orm import exc
from sqlalchemy import create_engine

from pypnusershub.db.models import (
    db, Application, User, UserApplicationRight, ApplicationRight
)
from pypnusershub.db.tools import init_schema, delete_schema, load_fixtures
from pypnusershub.utils import text_resource_stream

import autcircu


def generate_secret_key(size=50):
    punc = string.punctuation
    for letter in "%#;=:[]":
        punc = punc.replace(letter, '')
    pool = string.ascii_letters + string.digits + punc
    return "".join(random.SystemRandom().choice(pool) for i in range(size))


def start_app_context():
    from autcircu.conf import app
    # trigger the blueprint registering which binds pypnusershub'db
    from autcircu import routes  # noqa
    return app.app_context().push()


def init_db(app, db=db, debug_db=False):
    """ Create the schema and the tables if they don't exist """

    # init pypnusershub's db
    init_schema(app.config['SQLALCHEMY_DATABASE_URI'])

    start_app_context()
    if not ApplicationRight.query.filter().count():
        load_fixtures(app.config['SQLALCHEMY_DATABASE_URI'])

    # init aut circu's db
    engine = create_engine(
        app.config['SQLALCHEMY_DATABASE_URI'],
    )
    with engine.connect():
        engine.execute("CREATE SCHEMA IF NOT EXISTS auth_circu")
        engine.execute("COMMIT")

    db.create_all()

    # ensure we have our application registered in the database
    application, created = get_or_create(
        db.session,
        Application,
        commit=True,
        id_application=app.config['AUTHCIRCU_USERSHUB_APP_ID'],
        nom_application='Autorisations de circulation',
        desc_application='Gestion des autorisations de circulation des '
                         'véhicules à moteur dans le PN du mercantour'
    )


def create_test_user(app, username, password, access_rights=6, db=db):
    """ Create a local user for testing. UsersHub is not notified """

    user = User.query.filter(User.identifiant == username).one_or_none()
    if user:
        raise ValueError(f"A user with username '{username}' already exists")

    with db.session.begin_nested():
        user = User(identifiant=username, groupe=False)
        user.password = password
        db.session.add(user)
        db.session.flush()  # to get the new user id

        user_rights = UserApplicationRight(
            id_role=user.id_role,
            id_droit=access_rights,
            id_application=app.config['AUTHCIRCU_USERSHUB_APP_ID'],
        )
        db.session.add(user_rights)

    db.session.commit()


def delete_db(app, db=db):
    delete_schema(app.config['SQLALCHEMY_DATABASE_URI'])
    engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI'])
    with engine.connect():
        engine.execute("DROP SCHEMA IF EXISTS auth_circu CASCADE")
        engine.execute("COMMIT")


def reset_schema(con_uri):
    delete_schema(con_uri)
    init_schema(con_uri)


def get_or_create(session,
                  model,
                  create_method='',
                  create_method_kwargs=None,
                  commit=False,
                  **kwargs):
    """ Get an existing object from the DB or create one """
    try:
        return session.query(model).filter_by(**kwargs).one(), True
    except exc.NoResultFound:
        kwargs.update(create_method_kwargs or {})
        try:
            with session.begin_nested():
                created = getattr(model, create_method, model)(**kwargs)
                session.add(created)
            if commit:
                session.commit()
            return created, False
        except exc.IntegrityError:
            return session.query(model).filter_by(**kwargs).one(), True


def populate_db(db=db):

    # temporarly avoid settings default dates
    columns = autcircu.db.models.AuthRequest.__table__.columns
    columns['auth_start_date'].default = None
    columns['auth_end_date'].default = None
    columns['request_date'].default = None

    def normalize(s):
        """ Return a normalize string so that you can compare duplicate """
        # convert to lower case ascii chars
        s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore')
        s = s.decode('ascii').strip().lower()

        # remove non alphanumerical characters
        ''.join(e for e in s.casefold() if e.isalnum())

        # remove spaces
        return ' '.join(s.split())

    all_places = {}

    with text_resource_stream('legacy_auth_export.csv', 'autcircu.db') as data:

        for row in DictReader(data):

            # Default type is "other", we should not have 'pro' as they are
            # a new thing, and we switch to salèze if we see it in the places
            request_type = "other"

            # Remove useless spaces.
            row = {key: value.strip() for key, value in row.items()}

            name = "{NOM} {PRENOM}".format_map(row).strip()
            address = "{ADRESSE} {CODE POSTAL} {COMMUNE}".format_map(row)\
                                                         .strip()

            # Fetch all authorised vehicules.
            vehicules = set()
            for i in range(1, 5):
                immat = row[f"IMMATRICULATION {i}"]
                if immat:
                    vehicules.add(immat)

            # Fetch all the places, avoiding duplates.
            # Also check if we are asking an auth for Salèse.
            places = []
            for i in range(1, 3):
                place = row[f"PISTE {i}"]
                if place:

                    norm_str = normalize(place)

                    if norm_str not in all_places:
                        restricted_place = autcircu.db.models.RestrictedPlace(
                            name=place
                        )
                        all_places[norm_str] = restricted_place
                        db.session.add(restricted_place)
                    else:
                        restricted_place = all_places[norm_str]

                    if "salese" in norm_str:
                        request_type = 'salese'

                    places.append(restricted_place)

            # Get the gender of the person making the request
            # TODO: what do we display in the template for N/A ?
            gender = row['CIVILITE']
            if not gender:
                gender = "na"
            elif 'mme' in gender.casefold():
                gender = 'f'
            else:
                gender = 'm'

            # Parse the starting and ending date
            try:
                start_date = datetime.strptime(row['DEBUT DECISION'],
                                               '%d/%m/%y').date()
            except (ValueError, TypeError):
                start_date = None

            try:
                end_date = datetime.strptime(
                    row['FIN DECISION'],
                    '%d/%m/%y'
                ).date()
            except (ValueError, TypeError):
                end_date = None

            number = row['NUMERO AUTORISATION']
            if not number:
                base = start_date.year if start_date else '????'
                number = autcircu.db.models.AuthRequest.generate_number(base)

            # TODO: put a "note" ?
            auth_req = autcircu.db.models.AuthRequest(
                number=number,
                type=request_type,
                author_name=name or None,
                author_gender=gender,
                author_address=address or None,
                author_phone=row['TELEPHONE'] or None,
                auth_start_date=start_date,
                auth_end_date=end_date,
                vehicules=list(vehicules),
                proof_documents={
                    "legacy_info": row['JUSTIFICATIF'],
                    "expiration": row['DATE JUSTIFICATIF'],
                    "doc_type": None
                }
            )

            auth_req.request_date = auth_req.auth_start_date or auth_req.auth_end_date

            for place in places:
                auth_req.places.append(place)

            db.session.add(auth_req)
            yield auth_req

        db.session.commit()
