# Kenneth Tucker
# CS493 - Final Project

from flask import Blueprint, request, make_response
from google.cloud import datastore
import json
from utils import make_error, AuthError, verify_jwt
import datetime

client = datastore.Client()

bp = Blueprint('loan', __name__, url_prefix='/loans')

# Helpers for checking loan attributes


def is_valid_date(date: str):
    '''Date must be valid YYYY-MM-DD format'''
    try:
        date = datetime.datetime.strptime(date, '%Y-%m-%d')
        return True
    except ValueError:
        return False


def is_valid_end_type(end_type):
    '''End type must be valid option'''
    return end_type in {'returned', 'replaced', 'paid', 'forgiven'}


# Helpers for checking loan status

def is_item_available(item_id):
    query = client.query(kind="loans")
    query.add_filter("item", "=", int(item_id))
    query.add_filter("end_date", "=", None)
    query_result = list(query.fetch())
    if len(query_result) == 0:
        return True
    return False


# Routes

@bp.route('', methods=['POST', 'GET'])
def handle_loans_request():
    # Open a loan
    if request.method == 'POST':
        if request.content_type == 'application/json':
            if 'application/json' in request.accept_mimetypes:
                payload = verify_jwt(request)
                content = request.get_json()
                # When a loan is created we know the item being lent,
                # what day it was lent (the current date), and when it is due.
                # The loan will be closed in the future with an update
                # to the loan entity (see that part of code for details).
                # The due date must be after today's date.
                # Note: since dates are YYYY-MM-DD format, they can be compared as strings
                today = datetime.date.today().strftime('%Y-%m-%d')
                if "item" in content and "due_date" in content and \
                    is_valid_date(content["due_date"]) and content["due_date"] > today:
                    # Verify the item exists, it is loanable, no self loan,
                    # and no open loans already exist for it
                    items_key = client.key("items", int(content["item"]))
                    item = client.get(key=items_key)
                    if item and item["loanable"] and item["owner"] != payload["sub"]:
                        if is_item_available(content["item"]):
                            new_loan = datastore.entity.Entity(key=client.key("loans"))
                            new_loan.update({"item": content["item"], "borrower": payload["sub"],
                                            "start_date": today, "due_date": content["due_date"], 
                                            "end_date": None, "end_type": None
                                            })
                            client.put(new_loan)
                            # Copy ID into body to be sent (similar throughout)
                            new_loan["id"] = new_loan.key.id
                            # Create self link
                            new_loan["self"] = request.base_url + '/' + str(new_loan.key.id)
                            res = make_response(json.dumps(new_loan))
                            res.mimetype = 'application/json'
                            res.status_code = 201
                            return res
                        else:
                            return (make_error('Item not available'), 403)
                    else:
                        return (make_error('Invalid loan'), 403)
                else:
                    return (make_error("The request object has invalid attributes"), 400)
            else:
                return (make_error("Not Acceptable"), 406)
        else:
            return (make_error("Server only accepts application/json data."), 415)
    # Get loan history for the user
    elif request.method == 'GET':
        if 'application/json' in request.accept_mimetypes:
            payload = verify_jwt(request)
            query = client.query(kind="loans")
            query.add_filter("borrower", "=", payload["sub"])
            # Paginate
            q_limit = int(request.args.get('limit', '5'))
            q_offset = int(request.args.get('offset', '0'))
            l_iterator = query.fetch(limit=q_limit, offset=q_offset)
            pages = l_iterator.pages
            loans = list(next(pages))
            if l_iterator.next_page_token:
                next_offset = q_offset + q_limit
                next_url = request.base_url + "?limit=" + str(q_limit) + "&offset=" + str(next_offset)
            else:
                next_url = None
            for loan in loans:
                loan["id"] = loan.key.id
                loan["self"] = request.base_url + '/' + str(loan.key.id)
            output = {'loans': loans}
            if next_url:
                output["next"] = next_url
            res = make_response(json.dumps(output))
            res.mimetype = 'application/json'
            res.status_code = 200
            return res
        else:
            return (make_error("Not Acceptable"), 406)
    else:
        return (make_error('Method not recogonized'), 404)


@bp.route('/<loan_id>', methods=['GET', 'DELETE', 'PUT', 'PATCH'])
def handle_single_loan_request(loan_id):
    # View a loan (if the user is the lender or lendee)
    if request.method == 'GET':
        if 'application/json' in request.accept_mimetypes:
            payload = verify_jwt(request)
            sub = payload["sub"]
            loans_key = client.key("loans", int(loan_id))
            loan = client.get(key=loans_key)
            if loan:
                items_key = client.key("items", int(loan["item"]))
                item = client.get(key=items_key)
                # Note: even if the item was deleted the lendee can
                # still access their loan records
                if loan["borrower"] == sub or (item and item["owner"] == sub):
                    loan["id"] = loan.key.id
                    loan["self"] = request.base_url
                    res = make_response(json.dumps(loan))
                    res.mimetype = 'application/json'
                    res.status_code = 200
                    return res
                else:
                    return (make_error('Loan not available'), 403)
            else:
                return (make_error('No loan with this loan_id exists'), 404)
        else:
            return (make_error("Not Acceptable"), 406)
    # Delete a loan
    elif request.method == 'DELETE':
        payload = verify_jwt(request)
        loans_key = client.key("loans", int(loan_id))
        loan = client.get(key=loans_key)
        if loan:
            # Only the borrower can delete their loan records
            if loan["borrower"] == payload["sub"]:
                # Do not allow open loans to be deleted
                if loan["end_date"]:
                    client.delete(key=loan.key)
                    return ('', 204)
                else:
                    return (make_error('Open loans cannot be deleted'), 403)
            else:
                return (make_error('Loan never held'), 403)
        else:
            return (make_error('No loan with this loan_id exists'), 404)
    # Extend a loan's due date (only allowed by item owner)
    elif request.method == 'PUT':
        if request.content_type == 'application/json':
            if 'application/json' in request.accept_mimetypes:
                payload = verify_jwt(request)
                content = request.get_json()
                if "id" not in content and "due_date" in content and is_valid_date(content["due_date"]):
                    loans_key = client.key("loans", int(loan_id))
                    loan = client.get(key=loans_key)
                    if loan:
                        items_key = client.key("items", int(loan["item"]))
                        item = client.get(key=items_key)
                        if item and item["owner"] == payload["sub"]:
                            # Only allow loan extensions
                            if content["due_date"] > loan["due_date"]:
                                loan.update({"due_date": content["due_date"]})
                                client.put(loan)
                                loan["id"] = loan.key.id
                                loan["self"] = request.base_url
                                res = make_response(json.dumps(loan))
                                res.mimetype = 'application/json'
                                res.status_code = 200
                                return res
                            else:
                                return (make_error('Due date only extendable'), 400)
                        else:
                            return (make_error('Item not owned'), 403)
                    else:
                        return (make_error('No loan with this loan_id exists'), 404)
                else:
                    return (make_error("The request object has invalid attributes"), 400)
            else:
                return (make_error("Not Acceptable"), 406)
        else:
            return (make_error("Server only accepts application/json data."), 415)
    # End a loan (only allowed by item owner)
    elif request.method == 'PATCH':
        if request.content_type == 'application/json':
            if 'application/json' in request.accept_mimetypes:
                payload = verify_jwt(request)
                content = request.get_json()
                # Ensure end type is provided
                if "id" not in content and "end_type" in content and \
                    is_valid_end_type(content["end_type"]):
                    loans_key = client.key("loans", int(loan_id))
                    loan = client.get(key=loans_key)
                    if loan:
                        items_key = client.key("items", int(loan["item"]))
                        item = client.get(key=items_key)
                        # Only allow the loan to be ended one time
                        if loan["end_date"] is None and item and item["owner"] == payload["sub"]:
                            today = datetime.date.today().strftime('%Y-%m-%d')
                            loan.update({
                                "end_date": today,
                                "end_type": content["end_type"]})
                            client.put(loan)
                            loan["id"] = loan.key.id
                            loan["self"] = request.base_url
                            res = make_response(json.dumps(loan))
                            res.mimetype = 'application/json'
                            res.status_code = 200
                            return res
                        else:
                            return (make_error('Cannot end loan'), 403)
                    else:
                        return (make_error('No loan with this loan_id exists'), 404)
                else:
                    return (make_error("The request object has invalid attributes"), 400)
            else:
                return (make_error("Not Acceptable"), 406)
        else:
            return (make_error("Server only accepts application/json data."), 415)
    else:
        return (make_error('Method not recogonized'), 404)
