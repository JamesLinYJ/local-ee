"""Authorize script capabilities before upstream views discard their context."""
from flask import g, has_request_context
from openeo_driver.errors import OpenEOApiException, JobNotFoundException
from . import db


_OPERATIONS = {
    ('create_job', 'POST'), ('list_jobs', 'GET'),
    ('get_job_info', 'GET'), ('delete_job', 'DELETE'),
    ('start_job', 'POST'), ('cancel_job', 'DELETE'),
    ('list_job_results', 'GET'), ('download_job_result', 'GET'),
    ('get_job_logs', 'GET'),
}


def script_parent():
    return getattr(g, 'openeo_script_parent', None) if has_request_context() else None


def authorize(user, request):
    internal = user.internal_auth_data or {}
    if internal.get('scope') == 'user':
        return user
    if internal.get('scope') != 'script':
        raise OpenEOApiException('Token scope is not allowed', code='PermissionsInsufficient', status_code=403)
    parent = internal.get('job_id')
    try:
        row = db.job(parent, user.user_id) if parent else None
    except JobNotFoundException:
        row = None
    if (not row or row['kind'] != 'script' or row['status'] != 'running'
            or row['language'] not in {'python', 'javascript'}):
        raise OpenEOApiException('Script parent is not running', code='ScriptNotRunning', status_code=409)
    operation = (request.endpoint or '').rsplit('.', 1)[-1]
    method = 'GET' if request.method == 'HEAD' else request.method
    if (operation, method) not in _OPERATIONS:
        raise OpenEOApiException('Operation is not available to script tokens', code='PermissionsInsufficient', status_code=403)
    target = (request.view_args or {}).get('job_id')
    if target is not None:
        child = db.job(target, user.user_id)
        if child['kind'] != 'batch' or child['context'].get('source_job_id') != str(parent):
            raise JobNotFoundException(job_id=target)
    g.openeo_script_parent = str(parent)
    return user
