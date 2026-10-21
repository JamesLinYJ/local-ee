"""Shared HTTP authentication policy; script tokens access only declared runtime APIs."""
from functools import wraps
import os
from flask import request, g, abort
from . import auth


def authenticated(*, allow_script=False):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            header = request.headers.get('Authorization', '')
            if header:
                if not header.startswith('Bearer basic//'):
                    abort(401)
                token = header[len('Bearer basic//'):]
            else:
                token = request.cookies.get('gee_session', '')
            if not token:
                abort(401)
            try:
                account = auth.resolve(token)
            except Exception:
                abort(401)
            if request.method not in {'GET', 'HEAD', 'OPTIONS'} and not header:
                if request.headers.get('Origin', '') != os.environ.get('PUBLIC_ORIGIN', 'http://localhost:8787'):
                    abort(403)
            if account['scope'] not in ({'user', 'script'} if allow_script else {'user'}):
                abort(403)
            from .access import enforce_write
            enforce_write(account,request.method,request.path)
            g.account, g.token = account, token
            return fn(*args, **kwargs)
        return wrapped
    return decorate

secure = authenticated()
