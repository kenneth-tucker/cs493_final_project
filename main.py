# Kenneth Tucker
# CS493 - Final Project
# Citation: Some of this code is provided from lectures and the Auth0 tutorial
# linked in the assignment 7 page

"""App setup and user routes"""

import json
from flask import Flask, jsonify, redirect, render_template, session, url_for, request, make_response
from google.cloud import datastore
from six.moves.urllib.parse import urlencode, quote_plus
from utils import CLIENT_ID, DOMAIN, oauth, AuthError, verify_jwt, make_error
import item
import loan

app = Flask(__name__)
app.secret_key = 'b184f910a5e2f3707083abf6e9b910b1c87224361d6172e07dbf73f7eb7a2671'
app.register_blueprint(item.bp)
app.register_blueprint(loan.bp)

client = datastore.Client()


@app.errorhandler(AuthError)
def handle_auth_error(ex):
    response = jsonify(ex.error)
    response.status_code = ex.status_code
    return response


@app.route('/')
def home():
    return render_template(
        "home.html",
        session=session.get("user"),
        pretty=json.dumps(session.get("user"), indent=4),
    )


# Decode the JWT supplied in the Authorization header
@app.route('/decode', methods=['GET'])
def decode_jwt():
    payload = verify_jwt(request)
    return payload          
        

@app.route("/callback", methods=["GET", "POST"])
def callback():
    token = oauth.auth0.authorize_access_token()
    session["user"] = token
    query = client.query(kind="users")
    query.add_filter("sub", "=", token["userinfo"]["sub"])
    users = list(query.fetch())
    # Add any new users to the data store
    if len(users) == 0:
        new_user = datastore.entity.Entity(key=client.key("users"))
        new_user.update({
            "sub": token["userinfo"]["sub"],
            "name": token["userinfo"]["name"]})
        client.put(new_user)
    return redirect("/")


@app.route("/login")
def login():
    return oauth.auth0.authorize_redirect(
        redirect_uri=url_for("callback", _external=True)
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(
        "https://"
        + DOMAIN
        + "/v2/logout?"
        + urlencode(
            {
                "returnTo": url_for("home", _external=True),
                "client_id": CLIENT_ID,
            },
            quote_via=quote_plus,
        )
    )

@app.route('/users', methods=['GET'])
def users_get():
    if 'application/json' in request.accept_mimetypes:
        query = client.query(kind="users")
        users = list(query.fetch())
        res = make_response(json.dumps(users))
        res.mimetype = 'application/json'
        res.status_code = 200
        return res
    else:
        return (make_error("Not Acceptable"), 406)

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8080, debug=True)
