import datetime
import json
import logging
import random
from functools import wraps

import flask.scaffold
import jwt
import pika
import werkzeug
from bson import ObjectId
from flask import Flask, jsonify, request, g
from flask_cors import CORS
from flask_swagger_ui import get_swaggerui_blueprint
from pymongo import MongoClient, response

werkzeug.cached_property = werkzeug.utils.cached_property
flask.helpers._endpoint_from_view_func = flask.scaffold._endpoint_from_view_func

app = Flask(__name__)
CORS(app)

SWAGGER_URL = '/swagger'
API_URL = '/static/swagger.json'
SWAGGERUI_BLUEPRINT = get_swaggerui_blueprint(
    SWAGGER_URL,
    API_URL,
    config={
        'app_name': "order-service"
    }
)
app.register_blueprint(SWAGGERUI_BLUEPRINT, url_prefix=SWAGGER_URL)

SECRET_KEY = 'nekaSkrivnost'


def verify_token(token):
    secret = 'nekaSkrivnost'
    try:
        payload = jwt.decode(token, secret, algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        return 'Signature expired. Please log in again.'
    except jwt.InvalidTokenError:
        return 'Invalid token. Please log in again.'


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            token = request.headers['Authorization'].split(" ")[1]
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        data = verify_token(token)
        if isinstance(data, str):
            return jsonify({'message': 'Token is invalid!'}), 401
        g.user = data
        return f(*args, **kwargs)

    return decorated_function


client = MongoClient('mongodb://mongo:27017/order-service')
db = client['order-service']
orders_collection = db['orders']
counter_collection = db['counters']
users_collection = db['users']

app_name = 'order-service'

amqp_url = 'amqp://student:student123@studentdocker.informatika.uni-mb.si:5672/'
exchange_name = 'UPP-2'
queue_name = 'UPP-2'


def get_next_sequence_value(sequence_name):
    counter = counter_collection.find_one_and_update(
        {'_id': sequence_name},
        {'$inc': {'value': 1}},
        upsert=True,
        return_document=True
    )
    return counter['value']


def json_encoder(obj):
    if isinstance(obj, ObjectId):
        return str(obj)
    return obj


# GET /users/orders
@app.route('/users/orders', methods=['GET'])
@login_required
def get_orders():
    correlation_id = str(random.randint(1, 99999))
    orders = list(orders_collection.find().sort('_id', 1))
    orders_json = json.dumps(orders, default=json_encoder)
    message = ('%s INFO %s Correlation: %s [%s] - <%s>' % (
        datetime.datetime.now(), request.url, correlation_id, app_name, '*Klic storitve GET users orders*'))
    connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
    channel = connection.channel()

    channel.exchange_declare(exchange=exchange_name, exchange_type='direct')
    channel.queue_declare(queue=queue_name)
    channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key=queue_name)

    channel.basic_publish(exchange=exchange_name, routing_key=queue_name, body=message)

    connection.close()
    return jsonify(json.loads(orders_json))


# POST /orders
@app.route('/orders', methods=['POST'])
def create_order():
    correlation_id = request.headers.get('X-Correlation-ID')
    new_order = {
        'id': get_next_sequence_value('order_id'),
        'name': request.json.get('name'),
        'price': request.json.get('price'),
        'user_id': request.json.get('user_id'),
        'status': "ordered",
    }
    result = orders_collection.insert_one(new_order)
    new_order['_id'] = str(result.inserted_id)
    message = ('%s INFO %s Correlation: %s [%s] - <%s>' % (
        datetime.datetime.now(), request.url, correlation_id, app_name, '*Klic storitve POST orders*'))
    connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
    channel = connection.channel()

    channel.exchange_declare(exchange=exchange_name, exchange_type='direct')
    channel.queue_declare(queue=queue_name)
    channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key=queue_name)

    channel.basic_publish(exchange=exchange_name, routing_key=queue_name, body=message)

    connection.close()
    return jsonify(new_order), 201


# DELETE /orders/{id}
@app.route('/orders/<string:order_id>', methods=['DELETE'])
def delete_user(order_id):
    correlation_id = str(random.randint(1, 99999))
    result = orders_collection.delete_one({'id': int(order_id)})
    if result.deleted_count > 0:
        message = ('%s INFO %s Correlation: %s [%s] - <%s>' % (
            datetime.datetime.now(), request.url, correlation_id, app_name, '*Klic storitve DELETE order*'))
        connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
        channel = connection.channel()

        channel.exchange_declare(exchange=exchange_name, exchange_type='direct')
        channel.queue_declare(queue=queue_name)
        channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key=queue_name)

        channel.basic_publish(exchange=exchange_name, routing_key=queue_name, body=message)

        connection.close()
        return jsonify({'message': 'Order deleted'})
    else:
        return jsonify({'error': 'Order not found'}), 404


# GET /orders
@app.route('/orders', methods=['GET'])
def get_orders_for_user():
    correlation_id = request.headers.get('X-Correlation-ID')
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'user_id is required'}), 400

    user_orders = list(orders_collection.find({'user_id': int(user_id)}))
    users_json = json.dumps(user_orders, default=json_encoder)
    message = ('%s INFO %s Correlation: %s [%s] - <%s>' % (
        datetime.datetime.now(), request.url, correlation_id, app_name, '*Klic storitve GET orders*'))
    connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
    channel = connection.channel()

    channel.exchange_declare(exchange=exchange_name, exchange_type='direct')
    channel.queue_declare(queue=queue_name)
    channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key=queue_name)

    channel.basic_publish(exchange=exchange_name, routing_key=queue_name, body=message)

    connection.close()
    return jsonify(json.loads(users_json))


# PUT /orders/{id}/cancel
@app.route('/orders/<string:order_id>/cancel', methods=['PUT'])
def cancel_order(order_id):
    correlation_id = str(random.randint(1, 99999))
    order = orders_collection.find_one({'id': int(order_id)})

    if order:
        orders_collection.update_one({'id': int(order_id)},
                                     {'$set': {'status': 'cancelled'}})
        message = ('%s INFO %s Correlation: %s [%s] - <%s>' % (
            datetime.datetime.now(), request.url, correlation_id, app_name, '*Klic storitve PUT cancel*'))
        connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
        channel = connection.channel()

        channel.exchange_declare(exchange=exchange_name, exchange_type='direct')
        channel.queue_declare(queue=queue_name)
        channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key=queue_name)

        channel.basic_publish(exchange=exchange_name, routing_key=queue_name, body=message)

        connection.close()
        return jsonify({'message': 'Order cancelled'})
    else:
        return jsonify({'error': 'Order not found'}), 404


# PUT /orders/{id}/confirm
@app.route('/orders/<string:order_id>/confirm', methods=['PUT'])
def confirm_order(order_id):
    correlation_id = str(random.randint(1, 99999))
    order = orders_collection.find_one({'id': int(order_id)})

    if order:
        orders_collection.update_one({'id': int(order_id)},
                                     {'$set': {'status': 'confirmed'}})
        message = ('%s INFO %s Correlation: %s [%s] - <%s>' % (
            datetime.datetime.now(), request.url, correlation_id, app_name, '*Klic storitve PUT confirm*'))
        connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
        channel = connection.channel()

        channel.exchange_declare(exchange=exchange_name, exchange_type='direct')
        channel.queue_declare(queue=queue_name)
        channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key=queue_name)

        channel.basic_publish(exchange=exchange_name, routing_key=queue_name, body=message)

        connection.close()
        return jsonify({'message': 'Order confirmed'})
    else:
        return jsonify({'error': 'Order not found'}), 404


# GET /orders/ordered
@app.route('/orders/ordered', methods=['GET'])
def get_ordered_orders():
    correlation_id = str(random.randint(1, 99999))
    orders = list(orders_collection.find({'status': 'ordered'}))
    orders_json = json.dumps(orders, default=json_encoder)
    message = ('%s INFO %s Correlation: %s [%s] - <%s>' % (
        datetime.datetime.now(), request.url, correlation_id, app_name, '*Klic storitve GET ordered*'))
    connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
    channel = connection.channel()

    channel.exchange_declare(exchange=exchange_name, exchange_type='direct')
    channel.queue_declare(queue=queue_name)
    channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key=queue_name)

    channel.basic_publish(exchange=exchange_name, routing_key=queue_name, body=message)

    connection.close()
    return jsonify(json.loads(orders_json))


# GET /orders/confirmed
@app.route('/orders/confirmed', methods=['GET'])
def get_confirmed_orders():
    correlation_id = str(random.randint(1, 99999))
    orders = list(orders_collection.find({'status': 'confirmed'}))
    orders_json = json.dumps(orders, default=json_encoder)
    message = ('%s INFO %s Correlation: %s [%s] - <%s>' % (
        datetime.datetime.now(), request.url, correlation_id, app_name, '*Klic storitve GET confirmed*'))
    connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
    channel = connection.channel()

    channel.exchange_declare(exchange=exchange_name, exchange_type='direct')
    channel.queue_declare(queue=queue_name)
    channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key=queue_name)

    channel.basic_publish(exchange=exchange_name, routing_key=queue_name, body=message)

    connection.close()
    return jsonify(json.loads(orders_json))


# GET /orders/cancelled
@app.route('/orders/cancelled', methods=['GET'])
def get_cancelled_orders():
    correlation_id = str(random.randint(1, 99999))
    orders = list(orders_collection.find({'status': 'cancelled'}))
    orders_json = json.dumps(orders, default=json_encoder)
    message = ('%s INFO %s Correlation: %s [%s] - <%s>' % (
        datetime.datetime.now(), request.url, correlation_id, app_name, '*Klic storitve GET cancelled*'))
    connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
    channel = connection.channel()

    channel.exchange_declare(exchange=exchange_name, exchange_type='direct')
    channel.queue_declare(queue=queue_name)
    channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key=queue_name)

    channel.basic_publish(exchange=exchange_name, routing_key=queue_name, body=message)

    connection.close()
    return jsonify(json.loads(orders_json))


if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=3000)
