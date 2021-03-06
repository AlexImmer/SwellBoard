import json
import base64
from auxiliary.private import mongo_uri, db_name
from flask import jsonify
from pymongo import MongoClient
import gridfs
from auxiliary.nocache import nocache
from auxiliary.cookie import Cookie
from flask_cors import CORS, cross_origin
from auxiliary.supervisor import Supervisor
from auxiliary.mongoconfig import MongoConfig
from flask import Flask, request, send_from_directory, make_response, redirect

# Server configuration
SERVER_HOST = 'localhost'
SERVER_PORT = 5010
DB_CONFIG = MongoConfig().get_values()

# Sessions-related variables
SESSION_COOKIE_LABEL = 'session_cookie'
SUPERVISOR = Supervisor()

# Initailize application
application = Flask(__name__)
application.config.from_object(__name__)
cors = CORS(application)

# Configure Database
mongo_url = mongo_uri
db = MongoClient(mongo_url)
#application.config["APPLICATION_ROOT"] = '/api/1.0'

def decode_request(request):
    '''
    This function decodes a flask.request
    object and returns a session cookie
    as an auziliary.Cookie object and a
    dictionary containing all the 
    request's arguments (both for POST
    and GET methods).
    '''
    encoded_cookie = request.cookies.get('session_cookie', None)
    session_cookie = None#Cookie().decode(encoded_cookie)
    request_arguments = request.form if (request.method == 'POST') else request.args
    return session_cookie, request_arguments

def encode_response(response, session_cookie):
    '''
    This function encodes an auxiliary.Cookie
    object and injects it into the reposnse's
    body.
    '''
    #response.set_cookie(SESSION_COOKIE_LABEL, session_cookie.encode())
    return response

def valid_request(path, cookie, args):
    '''
    This function makes use of the Supervisor
    class to verify the integrity and 
    validity of a request.
    '''
    arg_val = SUPERVISOR.validate_arguments(path, args)
    cookie_val = True#SUPERVISOR.validate_cookie(cookie)
    return (arg_val and cookie_val)

@application.route('/login', methods=['POST'])
@nocache
def login():
    '''
    This function takes care of registering a
    user and returning a valid cookie.

    Parameters:
        username <desired loggin username>
    
    Return:
        None
    '''
    cookie, args = decode_request(request)
    if SUPERVISOR.validate_arguments(request.path, args) == False:
        return "Necessary parameter 'username' not found\n", 400
    if SUPERVISOR.validate_cookie(cookie) == False:
        cookie = Cookie(args['username'])
        response = make_response("Loged in", 200)
        return encode_response(response, cookie)
    return "Re-authentication not allowed\n", 403

@application.route('/models', methods=['GET'])
@cross_origin()
def get_models():
    '''
    This function takes care of querying all
    the models from a user.

    Parameters:
        None

    Return:
        JSON encoded list of all models.
    '''
    cookie, args = decode_request(request)
    if valid_request(request.path, cookie, args) == False:
        return "Invalid request\n", 400

    models = db[db_name]['runs'].find({}, {'config': 1})
    models = set([i['config']['method_tag'] for i in models])

    return encode_response(json_response(models), cookie)

@application.route('/runs', methods=['GET'])
@cross_origin()
def get_runs():
    '''
    This function gets all the runs associated
    with a specific model.

    Parameters:
        model_name <name of the module>

    Return:
        JSON encoded dictionary with run
        information.
    '''
    cookie, args = decode_request(request)
    if valid_request(request.path, cookie, args) == False:
        return "Invalid request\n", 400

    runs = db[db_name]['runs'].find({'config.method_tag': args['model_name']}, {'config': 1, 'heartbeat': 1})
    runs = list(runs)

    return encode_response(json_response(runs), cookie)

@application.route('/metrics/names', methods=['GET'])
@cross_origin()
def get_metric_names():
    '''
    This function gets all the metric
    names associated with a single run.

    Parameters:
        run_id <ID of the run>

    Return:
        JSON encoded list of strings.
    '''
    cookie, args = decode_request(request)
    if valid_request(request.path, cookie, args) == False:
        return "Invalid request\n", 400

    metric_names = db[db_name]['runs'].find_one({'_id': int(args['run_id'])}, {'info': 1})
    metric_names = set([i['name'] for i in metric_names['info']['metrics']])

    return encode_response(json_response(metric_names), cookie)

@application.route('/metrics/scalars', methods=['GET'])
@cross_origin()
def get_metric_scalars():
    '''
    This function gets all the metrics'
    values associated with a single run, 
    specific to a single metric.

    Parameters:
        run_id <ID of the run>
        metric_name <Name of the metricto track>

    Return:
        JSON encoded over time information
        for the requested metric.
    '''
    cookie, args = decode_request(request)
    if valid_request(request.path, cookie, args) == False:
        return "Invalid request\n", 400

    run_id = int(args['run_id'])
    metric_name = args['metric_name']
    result = dict()
    run_metric = db[db_name]['metrics'].find_one({'run_id': run_id, 'name': metric_name})
    run = db[db_name]['runs'].find_one({'_id': run_id}, {'config'})['config']['method_tag']
    run_model_name = run + '-' + str(run_id)
    result['name'] = run_model_name
    result['series'] = [{'name': step, 'value': val, 'run_id': run_id}
                        for step, val in zip(run_metric['steps'], run_metric['values'])]
    return encode_response(json_response(result), cookie)

@application.route('/results/names', methods=['GET'])
@cross_origin()
def get_result_names():
    '''
    This function gets all the results'
    names associated with a single run.

    Parameters:
        run_id <ID of the run>

    Return:
        JSON encoded list of all result
        names.
    '''
    cookie, args = decode_request(request)
    if valid_request(request.path, cookie, args) == False:
        return "Invalid request\n", 400

    result_names = db[db_name]['runs'].find_one({'_id': int(args['run_id'])}, {'result': 1})['result'].keys()
    result_names = list(result_names)

    return encode_response(json_response(result_names), cookie)

@application.route('/results/scalars', methods=['GET'])
@cross_origin()
def get_result_scalars():
    '''
    This function gets all the results'
    values associated with a single run,
    specific to a single metric.

    Parameter:
        run_id <ID of the run>
        result_name <Name of the result>

    Return:
        JSON ecoded over time information
        for the requested result.
    '''
    cookie, args = decode_request(request)
    if valid_request(request.path, cookie, args) == False:
        return "Invalid request\n", 400

    run_metric = dict()
    run_metric['value'] = db[db_name]['runs'].find_one({'_id': int(args['run_id'])}, {'result': 1})['result'][
        args['result_name']]
    run_metric['name'] = db[db_name]['runs'].find_one({'_id': int(args['run_id'])}, {'config': 1})['config'][
                             'method_tag'] + '-{}'.format(args['run_id'])
    return encode_response(json_response(run_metric), cookie)

@application.route('/params/names', methods=['GET'])
@cross_origin()
def get_param_names():
    '''
    This function gets all the params'
    names associated witha a single run.

    Parameters:
        run_id <ID of the run>

    Return:
        JSON encoded list of all param
        names.
    '''
    cookie, args = decode_request(request)
    if valid_request(request.path, cookie, args) == False:
        return "Invalid request\n", 400

    param_names = db[db_name]['runs'].find_one({'_id': int(args['run_id'])}, {'config': 1})

    return encode_response(json_response(param_names), cookie)

@application.route('/params/scalars', methods=['GET'])
@cross_origin()
def get_param_scalars():
    '''
    This function gets all the params'
    values associated with a single run,
    specific to a single param.

    Parameters:
        run_id <ID of the run>
        param_name <Name of the parameter>

    Return:
        JSON encoded over time information
        for the requested param.
    '''
    cookie, args = decode_request(request)
    if valid_request(request.path, cookie, args) == False:
        return "Invalid request\n", 400

    param_scalars = db[db_name]['runs'].find_one({'_id': int(args['run_id'])}, {'config': 1})['config'][args['param_name']]
    param_scalars = [param_scalars]

    return encode_response(json_response(param_scalars), cookie)

@application.route('/artifacts', methods=['GET'])
@cross_origin()
def get_artifacts():
    '''
    This function gets all the artifacts for
    a specific run.

    Parameters:
        run_id <ID of the run>

    Returns:
        JSON encoded dictionary of
        binary data.
    '''
    cookie, args = decode_request(request)
    if valid_request(request.path, cookie, args) == False:
        return "Invalid request\n", 400

    fs = gridfs.GridFS(db[db_name])
    artifacts = {}
    for file in db[db_name]['runs'].find_one({'_id': int(args['run_id'])}, {'artifacts'})['artifacts']:
        if '.png' in file['name']:
            fig = fs.get(file['file_id']).read()
            artifacts[file['name']] = str(base64.b64encode(fig))

    return encode_response(json_response(artifacts), cookie)

def json_response(dictionary):
    '''
    This function encodes cetain data types
    into JSON formatted strings.
    '''
    data = dictionary
    if type(data) is list:
        data = {'data': data}
    elif type(data) is set:
        data = {'data': list(data)}
    return jsonify(data)

def not_implemented():
    return make_response("Method not implemented\n", 403)

if __name__ == '__main__':
    application.run(host=SERVER_HOST, port=SERVER_PORT)