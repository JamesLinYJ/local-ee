"""Real upstream HTTP authentication must retain job-bound script authority."""
from datetime import datetime, timezone
from pathlib import Path

import pytest
from openeo_driver.errors import JobNotFoundException
from openeo_driver.views import build_app
from gee import auth, backend, db

PARENT = '00000000-0000-0000-0000-000000000001'
CHILD = '00000000-0000-0000-0000-000000000002'
SIBLING = '00000000-0000-0000-0000-000000000003'


@pytest.fixture
def api(monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    def row(jid, **extra):
        return dict(id=jid, user_id='researcher', kind='batch', language='python',
                    context={}, status='finished', created=now, updated=now,
                    started=now, finished=now, process={'process_graph': {}},
                    title='Synthetic task', logs='synthetic log', assets={}, **extra)
    rows = {jid: row(jid) for jid in [PARENT, CHILD, SIBLING]}
    rows[PARENT].update(kind='script', status='running')
    rows[CHILD]['context'] = {'source_job_id': PARENT}
    for jid in [CHILD, SIBLING]:
        folder = tmp_path / 'jobs' / jid / 'out'
        folder.mkdir(parents=True)
        (folder / 'result.csv').write_text('value\n1\n')
        rows[jid]['assets'] = {'result.csv': {'type': 'text/csv'}}
    account = dict(user_id='researcher', role='researcher', scope='script', job_id=PARENT)
    calls = []
    def job(jid, uid):
        if jid not in rows or uid != 'researcher': raise JobNotFoundException(job_id=jid)
        return rows[jid]
    def query(sql, params=(), one=False):
        calls.append((sql, params))
        if sql.startswith('SELECT * FROM jobs'):
            selected = [r for r in rows.values() if r['kind'] == 'batch']
            if "context->>'source_job_id'=%s" in sql:
                selected = [r for r in selected if r['context'].get('source_job_id') == params[1]]
            return selected
        return None
    monkeypatch.setattr(db, 'job', job)
    monkeypatch.setattr(db, 'query', query)
    monkeypatch.setattr(auth, 'resolve', lambda token: account)
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    implementation = backend.Backend()
    app = build_app(implementation)
    auth.install(app.extensions['auth_handler'])
    client = app.test_client()
    client.environ_base['HTTP_AUTHORIZATION'] = 'Bearer basic//synthetic-test-token'
    return client, rows, account, calls, implementation


@pytest.mark.parametrize('prefix', ['/openeo', '/openeo/1.0.0', '/openeo/1.1', '/openeo/1.2'])
def test_listing_is_filtered_to_own_children(api, prefix):
    client, rows, _, _, _ = api
    response = client.get(prefix + '/jobs')
    assert response.status_code == 200, response.json
    assert [r['id'] for r in response.json['jobs']] == [CHILD]


@pytest.mark.parametrize('method, suffix', [
    ('GET', ''), ('HEAD', ''), ('DELETE', ''),
    ('POST', '/results'), ('DELETE', '/results'),
    ('GET', '/results'), ('GET', '/logs'),
    ('GET', '/results/assets/result.csv'), ('HEAD', '/results/assets/result.csv'),
])
def test_sibling_and_parent_resources_are_inaccessible(api, method, suffix):
    client, rows, _, calls, _ = api
    for jid in [SIBLING, PARENT, '../unknown']:
        response = client.open('/openeo/1.2/jobs/' + jid + suffix, method=method)
        assert response.status_code == 404, (method, jid, suffix, response.status_code)
    assert not any(sql.startswith(('UPDATE', 'DELETE')) for sql, _ in calls)


@pytest.mark.parametrize('suffix', ['', '/logs', '/results/assets/result.csv'])
def test_own_child_reads_preserve_official_client_routes(api, suffix):
    client, *_ = api
    response = client.get('/openeo/1.2/jobs/' + CHILD + suffix)
    assert response.status_code == 200, response.json


@pytest.mark.parametrize('method,suffix,status', [('POST','/results',202), ('DELETE','/results',204), ('DELETE','',204)])
def test_own_child_mutations_remain_available(api, method, suffix, status):
    client, rows, *_ = api
    rows[CHILD]['status'] = 'created'
    response = client.open('/openeo/1.2/jobs/' + CHILD + suffix, method=method)
    assert response.status_code == status, response.json


@pytest.mark.parametrize('change', [dict(status='finished'), dict(kind='batch'), dict(language='other')])
def test_stopped_or_invalid_parent_denies_even_listing(api, change):
    client, rows, *_ = api
    rows[PARENT].update(change)
    response = client.get('/openeo/1.2/jobs')
    assert response.status_code == 409 and response.json['code'] == 'ScriptNotRunning'


def test_unrelated_authenticated_operations_are_denied(api):
    client, *_ = api
    assert client.get('/openeo/1.2/me').status_code == 403
    assert client.patch('/openeo/1.2/jobs/' + CHILD, json={'title':'changed'}).status_code == 403


def test_user_scope_keeps_account_wide_access(api):
    client, _, account, _, _ = api
    account.update(scope='user', job_id=None)
    response = client.get('/openeo/1.2/jobs')
    assert {r['id'] for r in response.json['jobs']} == {CHILD, SIBLING}
    assert client.get('/openeo/1.2/jobs/' + SIBLING).status_code == 200
