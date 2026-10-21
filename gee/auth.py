import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from openeo_driver.errors import TokenInvalidException, CredentialsInvalidException
from openeo_driver.users import User
from . import db

_DUMMY_PASSWORD_HASH = generate_password_hash("unusable-auth-timing-placeholder")

def create_user(name, password, role=None):
    from .access import ROLES
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", name) or len(password) < 12:
        raise ValueError("账号仅限字母数字 ._-，密码至少 12 位")
    if role is not None and role not in ROLES: raise ValueError('Unknown role')
    with db.connect() as c:
        c.execute("INSERT INTO users(id,password,role) VALUES(%s,%s,%s) ON CONFLICT(id) DO UPDATE SET password=EXCLUDED.password",
                  (name,generate_password_hash(password),role or 'researcher'))
        # Role changes for existing accounts use the administration service/CLI.
        c.execute("DELETE FROM tokens WHERE user_id=%s",(name,))

def reserve_auth_attempt(name, source):
    """Shared atomic limits cover every HTTP alias and all API worker processes."""
    with db.connect() as c:
        c.execute("DELETE FROM auth_attempts WHERE window_started < now() - interval '2 minutes'")
        for kind,value,limit in [("source",source,60),("account",name,12)]:
            bucket=hashlib.sha256((kind+":"+value).encode()).hexdigest()
            row=c.execute("""INSERT INTO auth_attempts(bucket,attempts) VALUES(%s,1)
                ON CONFLICT(bucket) DO UPDATE SET
                attempts=CASE WHEN auth_attempts.window_started < now()-interval '1 minute' THEN 1 ELSE auth_attempts.attempts+1 END,
                window_started=CASE WHEN auth_attempts.window_started < now()-interval '1 minute' THEN now() ELSE auth_attempts.window_started END
                RETURNING attempts""",(bucket,)).fetchone()
            if row["attempts"] > limit:
                return False
    return True

def verify(name, password):
    from flask import has_request_context,request,abort
    if has_request_context() and not reserve_auth_attempt(name,request.remote_addr or "unknown"):
        abort(429)
    row = db.query("SELECT password,enabled FROM users WHERE id=%s", (name,), one=True)
    # Perform a hash even for unknown users.
    valid=check_password_hash(row["password"] if row else _DUMMY_PASSWORD_HASH,password)
    return bool(row and row['enabled'] and valid)

def issue(user_id, scope="user", hours=12, job_id=None):
    token = secrets.token_urlsafe(36)
    db.query("INSERT INTO tokens(digest,user_id,expires,scope,job_id) VALUES(%s,%s,%s,%s,%s)",
             (hashlib.sha256(token.encode()).hexdigest(), user_id, datetime.now(timezone.utc)+timedelta(hours=hours), scope, job_id))
    return token

def resolve(token):
    row = db.query("SELECT t.user_id,t.scope,t.job_id,u.role FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.digest=%s AND t.expires>now() AND u.enabled",
                   (hashlib.sha256(token.encode()).hexdigest(),), one=True)
    if not row:
        raise TokenInvalidException()
    return row

def revoke(token):
    db.query("DELETE FROM tokens WHERE digest=%s", (hashlib.sha256(token.encode()).hexdigest(),))

def install(handler):
    """Replace the upstream development basic tokens with revocable random tokens.

    Keep the handler object captured by all registered endpoint decorators.
    Disable its TTL cache so expiry/revocation takes effect on the next request.
    """
    def authenticate(request):
        from flask import g
        if hasattr(g, "issued_basic"):
            return g.issued_basic
        name, password = handler.parse_basic_auth_header(request)
        if not verify(name, password):
            raise CredentialsInvalidException()
        # Upstream basic decorator calls this twice for one request.
        from flask import g
        if not hasattr(g, "issued_basic"):
            g.issued_basic = (issue(name), name)
        return g.issued_basic
    def bearer(request):
        text = handler.get_auth_token(request)
        if not text.startswith("basic//"):
            raise TokenInvalidException()
        row = resolve(text[7:])
        from .access import enforce_write
        enforce_write(row,request.method,request.path)
        return User(row["user_id"], internal_auth_data={"scope": row["scope"],"job_id":str(row['job_id']) if row.get('job_id') else None})
    handler.authenticate_basic = authenticate
    handler.get_user_from_bearer_token = bearer

def redact(text):
    text = re.sub(r"(?i)(Bearer\s+|basic//)[A-Za-z0-9_.~+/=-]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)((?:password|access_token|api[_-]?key|token|secret)\s*[=:]\s*)[^\s,;]+", r"\1[REDACTED]", text)
    return text
