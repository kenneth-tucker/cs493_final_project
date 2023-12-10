# Kenneth Tucker
# CS493 - Final Project

from flask import Blueprint, request, make_response
from google.cloud import datastore
import json
from utils import make_error, AuthError, verify_jwt
from loan import is_item_available

client = datastore.Client()

bp = Blueprint('item', __name__, url_prefix='/items')

# Helpers for checking item attributes


def is_valid_name(item_name):
    '''Name must be a non-empty string less than 64 characters'''
    return isinstance(item_name, str) and \
        (len(item_name) > 0) and \
        (len(item_name) < 64)


def is_valid_description(item_description):
    '''Description must be a string less than 256 characters'''
    return isinstance(item_description, str) and \
        (len(item_description) < 256)


def is_valid_value(item_value):
    '''Value must be an integer greater than 0 and less than 1000'''
    return isinstance(item_value, int) and \
        (item_value > 0) and \
        (item_value < 1000)


def is_valid_loanable(item_loanable):
    '''Value must be a bool'''
    return isinstance(item_loanable, bool)


# Routes


@bp.route('', methods=['POST', 'GET'])
def handle_items_request():
    # Create an item
    if request.method == 'POST':
        if request.content_type == 'application/json':
            if 'application/json' in request.accept_mimetypes:
                payload = verify_jwt(request)
                content = request.get_json()
                if "name" in content and "description" in content and \
                    "value" in content and "loanable" in content and \
                    is_valid_name(content["name"]) and is_valid_description(content["description"]) and \
                    is_valid_value(content["value"]) and is_valid_loanable(content["loanable"]):
                    new_item = datastore.entity.Entity(key=client.key("items"))
                    new_item.update({"name": content["name"], "description": content["description"],
                                    "value": content["value"], "loanable": content["loanable"],
                                    "owner": payload["sub"]})
                    client.put(new_item)
                    # Copy ID into body to be sent (similar throughout)
                    new_item["id"] = new_item.key.id
                    # Create self link
                    new_item["self"] = request.base_url + '/' + str(new_item.key.id)
                    res = make_response(json.dumps(new_item))
                    res.mimetype = 'application/json'
                    res.status_code = 201
                    return res
                else:
                    return (make_error("The request object has invalid attributes"), 400)
            else:
                return (make_error("Not Acceptable"), 406)
        else:
            return (make_error("Server only accepts application/json data."), 415)
    # Get items (depending on JWT validity)
    elif request.method == 'GET':
        if 'application/json' in request.accept_mimetypes:
            query = client.query(kind="items")
            try:
                payload = verify_jwt(request)
                # JWT valid, return all items of specified owner
                query.add_filter("owner", "=", payload["sub"])
            except AuthError:
                # Return all items advertised by the owners as loanable
                query.add_filter("loanable", "=", True)
            # Paginate
            q_limit = int(request.args.get('limit', '5'))
            q_offset = int(request.args.get('offset', '0'))
            l_iterator = query.fetch(limit=q_limit, offset=q_offset)
            pages = l_iterator.pages
            items = list(next(pages))
            if l_iterator.next_page_token:
                next_offset = q_offset + q_limit
                next_url = request.base_url + "?limit=" + str(q_limit) + "&offset=" + str(next_offset)
            else:
                next_url = None
            for item in items:
                item["id"] = item.key.id
                item["self"] = request.base_url + '/' + str(item.key.id)
            output = {'items': items}
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


@bp.route('/<item_id>', methods=['GET', 'DELETE', 'PUT', 'PATCH'])
def handle_single_item_request(item_id):
    # View a item
    if request.method == 'GET':
        if 'application/json' in request.accept_mimetypes:
            try:
                payload = verify_jwt(request)
                sub = payload["sub"]
            except AuthError:
                sub = ""
            items_key = client.key("items", int(item_id))
            item = client.get(key=items_key)
            if item:
                if item["owner"] == sub or item["loanable"]:
                    item["id"] = item.key.id
                    item["self"] = request.base_url
                    res = make_response(json.dumps(item))
                    res.mimetype = 'application/json'
                    res.status_code = 200
                    return res
                else:
                    return (make_error('Item not available'), 403)
            else:
                return (make_error('No item with this item_id exists'), 404)
        else:
            return (make_error("Not Acceptable"), 406)
    # Delete an item
    elif request.method == 'DELETE':
        payload = verify_jwt(request)
        items_key = client.key("items", int(item_id))
        item = client.get(key=items_key)
        if item:
            if item["owner"] == payload["sub"]:
                # Prevent deletion for items on loan
                if is_item_available(item_id):
                    client.delete(key=item.key)
                    return ('', 204)
                else:
                    return (make_error('Cannot delete loaned item'), 403)
            else:
                return (make_error('Item not owned'), 403)
        else:
            return (make_error('No item with this item_id exists'), 404)
    # Edit an item (update all attributes)
    elif request.method == 'PUT':
        if request.content_type == 'application/json':
            if 'application/json' in request.accept_mimetypes:
                payload = verify_jwt(request)
                content = request.get_json()
                if "id" not in content and "name" in content and "description" in content and \
                    "value" in content and "loanable" in content and \
                    is_valid_name(content["name"]) and is_valid_description(content["description"]) and \
                    is_valid_value(content["value"]) and is_valid_loanable(content["loanable"]):
                    items_key = client.key("items", int(item_id))
                    item = client.get(key=items_key)
                    if item:
                        if item["owner"] == payload["sub"]:
                            if is_item_available(item_id):
                                item.update({"name": content["name"], "description": content["description"],
                                            "value": content["value"], "loanable": content["loanable"]})
                                client.put(item)
                                item["id"] = item.key.id
                                item["self"] = request.base_url
                                res = make_response(json.dumps(item))
                                res.mimetype = 'application/json'
                                res.status_code = 200
                                return res
                            else:
                                return (make_error('Cannot modify loaned item'), 403)
                        else:
                            return (make_error('Item not owned'), 403)
                    else:
                        return (make_error('No item with this item_id exists'), 404)
                else:
                    return (make_error("The request object has invalid attributes"), 400)
            else:
                return (make_error("Not Acceptable"), 406)
        else:
            return (make_error("Server only accepts application/json data."), 415)
    # Edit an item (update some attributes)
    elif request.method == 'PATCH':
        if request.content_type == 'application/json':
            if 'application/json' in request.accept_mimetypes:
                payload = verify_jwt(request)
                content = request.get_json()
                # Ensure whichever attributes provided are correct type
                if "id" not in content and \
                    ("name" not in content or is_valid_name(content["name"])) and \
                    ("description" not in content or is_valid_description(content["description"])) and \
                    ("value" not in content or is_valid_value(content["value"])) and \
                    ("loanable" not in content or is_valid_loanable(content["loanable"])):
                    items_key = client.key("items", int(item_id))
                    item = client.get(key=items_key)
                    if item:
                        if item["owner"] == payload["sub"]:
                            if is_item_available(item_id):
                                update_dict = {}
                                if "name" in content:
                                    update_dict["name"] = content["name"]
                                if "description" in content:
                                    update_dict["description"] = content["description"]
                                if "value" in content:
                                    update_dict["value"] = content["value"]
                                if "loanable" in content:
                                    update_dict["loanable"] = content["loanable"] 
                                item.update(update_dict)
                                client.put(item)
                                item["id"] = item.key.id
                                item["self"] = request.base_url
                                res = make_response(json.dumps(item))
                                res.mimetype = 'application/json'
                                res.status_code = 200
                                return res
                            else:
                                return (make_error('Cannot modify loaned item'), 403)
                        else:
                            return (make_error('Item not owned'), 403)
                    else:
                        return (make_error('No item with this item_id exists'), 404)
                else:
                    return (make_error("The request object has invalid attributes"), 400)
            else:
                return (make_error("Not Acceptable"), 406)
        else:
            return (make_error("Server only accepts application/json data."), 415)
    else:
        return (make_error('Method not recogonized'), 404)
