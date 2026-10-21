"""Versioned local Earth Engine adapter routes."""
from flask import Blueprint,request,jsonify,g
from ..http_auth import authenticated
from ..services.ee import dispatch
from ..ee_translate import UnsupportedEEError, get_capabilities


def register_ee_api(app,backend):
    bp=Blueprint('earthengine',__name__,url_prefix='/gee/v1')

    @bp.post('/dispatch')
    @authenticated(allow_script=True)
    def local_dispatch():
        try:return jsonify(dispatch(backend,g.account,request.get_json()))
        except UnsupportedEEError as error:return jsonify({'code':'EEUnsupported','message':str(error)}),422
        except (ValueError,TypeError,KeyError,RecursionError) as error:return jsonify({'code':'EEInvalidRequest','message':str(error)[:500]}),400

    @bp.get('/capabilities')
    @authenticated(allow_script=True)
    def capabilities():
        return jsonify({**get_capabilities(),'version':'0.1','client':'@google/earthengine','client_version':'1.7.49','execution':'isolated-local-node','backend':'openEO GeoTrellis','full_gee_compatibility':False})

    app.register_blueprint(bp)
