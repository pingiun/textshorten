import logging
import os
import random
import re
import time

from queue import Queue
from functools import wraps

from jinja2 import evalcontextfilter, Markup, escape

from werkzeug.wrappers import Response
from flask import Flask, redirect, request, render_template
from flask_restful import reqparse, Resource, Api

import sqlalchemy.exc
from sqlalchemy import Column, Integer, String
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
api = Api(app)

postparser = reqparse.RequestParser()
postparser.add_argument('text', required=True, help="The text to save")
postparser.add_argument('secret', type=bool, help="Make a secret paste")
getparser = reqparse.RequestParser()
getparser.add_argument('page', type=int, default=1, help="Page of the result")

limiter_dict = {}

_paragraph_re = re.compile(r'(?:\r\n|\r|\n){2,}')

_text = 'DsU~CF6hjX2u5QpolMWaNmLr8keVqzR0_3tn7HdOyJbZ.TI1AgfExB4SP9GiwYcvK-'
_base = len(_text)

def number_to_text(number):
    text = ""
    if number == 0:
        text += _text[0]
    while number:
        text += _text[number % _base]
        number = number // _base
    return text

def text_to_number(tekst):
    number = 0
    for i, character in enumerate(tekst):
        number += _text.index(character) * _base ** i
    return number

def check_limit(token):
    if token in limiter_dict:
        while len(limiter_dict[token].queue) > 0 and limiter_dict[token].queue[0] < time.time():
            limiter_dict[token].get_nowait()
    else:
        limiter_dict[token] = Queue()

    if len(limiter_dict[token].queue) <= 20:
        limiter_dict[token].put_nowait(int(time.time() + 60 * 60))
    return int(os.environ["GLOBAL_RATELIMIT"]) - len(limiter_dict[token].queue), limiter_dict[token].queue[0]

def limit(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        remaining, reset = check_limit(request.remote_addr)
        if remaining < 0:
            return ({
                        'status': 429, 
                        'message': 'API limit reached'
                    }, 429, 
                    {
                        'RateLimit-Limit': os.environ["GLOBAL_RATELIMIT"],
                        'RateLimit-Remaining': remaining,
                        'RateLimit-Reset': reset
                    })
        resp = api.make_response(*f(*args, **kwargs))
        resp.headers['RateLimit-Limit'] = os.environ["GLOBAL_RATELIMIT"]
        resp.headers['RateLimit-Remaining'] = remaining
        resp.headers['RateLimit-Reset'] = reset
        return resp
    return wrapper

engine = create_engine(os.environ["DB_URL"], echo=True)

db_session = scoped_session(sessionmaker(autocommit=False,
                                         autoflush=False,
                                         bind=engine))

Base = declarative_base()
Base.query = db_session.query_property()

class NormalPaste(Base):
    __tablename__ = "pastes"

    id = Column(Integer, primary_key=True)
    text = Column(String)

    def __repr__(self):
        return "/{} = {}".format(number_to_text(self.id), self.text)

class SecretPaste(Base):
    __tablename__ = "secretpastes"

    id = Column(String, primary_key=True)
    text = Column(String)

    def __repr__(self):
        return "/{} = {}".format(self.id, self.text)

Base.metadata.create_all(bind=engine)

def get_paste(paste_id):
    if paste_id.startswith('+'):
        return get_secret_paste(paste_id)

    pasteid = text_to_number(paste_id)
    paste = NormalPaste.query.filter(NormalPaste.id == pasteid).first()
    return paste.text

def add_paste(text):
    newpaste = NormalPaste(text=text)
    db_session.add(newpaste)
    db_session.commit()
    if number_to_text(newpaste.id) == 'pastes':
        return -1
    return newpaste.id

def get_secret_paste(paste_id):
    paste = SecretPaste.query.filter(SecretPaste.id == paste_id).first()
    return paste.text

def add_secret_paste(paste):
    pasteid = ""
    tries = 0
    length = 5
    while SecretPaste.query.filter(SecretPaste.id == pasteid).first() or pasteid == "":
        if tries > 10:
            length += 1
            tries = 0
        pasteid = '+' + ''.join([random.choice(_text) for _ in range(length)])
        tries += 1
    
    newpaste = SecretPaste(id=pasteid, text=paste)
    db_session.add(newpaste)
    db_session.commit()
    return pasteid

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/<string:paste_id>')
def show_paste(paste_id):
    try:
        return render_template("showpaste.html", paste_content=get_paste(paste_id))
    except Exception as e:
        logger.exception(e)
        return "404 Not found", 404

@app.teardown_appcontext
def shutdown_session(exception=None):
    db_session.remove()

class Paste(Resource):
    @limit
    def get(self, paste_id):
        try:
            return {'status': 200, 'message': get_paste(paste_id)}, 200
        except:
            return {'status': 404, 'message': 'Not Found'}, 404

class PasteList(Resource):
    @limit
    def get(self):
        try:
            args = getparser.parse_args()
            page = args['page'] - 1
            print("page: {}".format(page))
            pastes = NormalPaste.query.order_by(NormalPaste.id.desc()).limit(25).offset(25 * page)
            allpastes = [number_to_text(paste.id) for paste in pastes]
        except Exception as e:
            logging.exception(e)
            return {'status': 500, 'message': 'Internal Server Error'}, 500
        else:
            return {'status': 200, 'message': allpastes}, 200

    @limit
    def post(self):
        args = postparser.parse_args()

        if args['text'] == "":
            return {'status': 400, 'message': "Paste text cannot be empty."}, 400
        else:
            logging.debug("Making new paste with content: {}".format(args['text']))
        
        if args['secret']:
            try:
                pasteid = add_secret_paste(args['text'])
            except Exception as e:
                logging.exception(e)
                return {'status': 500, 'message': 'Internal Server Error'}, 500
            else:
                return {'status': 200, 'message': pasteid}, 200
            
        try:
            pasteid = -1
            while pasteid == -1:
                pasteid = add_paste(args['text'])
        except Exception as e:
            logging.exception(e)
            return {'status': 500, 'message': 'Internal Server Error'}, 500
        else:
            return {'status': 200, 'message': number_to_text(pasteid)}, 200

api.add_resource(Paste, '/pastes/<string:paste_id>')
api.add_resource(PasteList, '/pastes/')

if __name__ == '__main__':
    app.run(debug=True)