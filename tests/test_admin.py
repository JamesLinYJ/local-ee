"""Management permission boundaries and catalog write validation."""
import pytest
from flask import Flask, jsonify
from openeo_driver.errors import OpenEOApiException
from gee.access import permits, enforce_write
from gee.services import administration as service


@pytest.mark.parametrize('role,scope,expected',[
    ('admin','user',True),('dataset_manager','user',True),('researcher','user',False),
    ('viewer','user',False),('admin','script',False),('unknown','user',False),
])
def test_dataset_management_permissions(role,scope,expected):
    assert permits({'role':role,'scope':scope},'datasets:manage') is expected


def test_dataset_manager_cannot_manage_accounts():
    assert not permits({'role':'dataset_manager','scope':'user'},'users:manage')


@pytest.mark.parametrize('path',['/workbench/jobs','/workbench/scripts','/openeo/1.2/jobs','/gee/v1/dispatch'])
def test_viewer_cannot_write_via_alternate_interfaces(path):
    with pytest.raises(OpenEOApiException) as caught:enforce_write({'role':'viewer'},'POST',path)
    assert caught.value.status_code == 403
    enforce_write({'role':'viewer'},'GET',path)
    enforce_write({'role':'viewer'},'POST','/workbench/logout')


@pytest.mark.parametrize('data',[
    {'id':'local-example','title':'Example','license':'proprietary','href':'https://invalid.example/a.tif'},
    {'id':'local-example','title':'Example','license':'proprietary','enabled':True},
    {'id':'../outside','title':'Example','license':'proprietary'},
    {'id':'local-example','title':'','license':'proprietary'},
    {'id':'local-example','title':'Example','license':''},
])
def test_draft_validation_rejects_uncontrolled_fields_and_invalid_metadata(data):
    with pytest.raises(OpenEOApiException):service.dataset_create('synthetic-admin',data)


def test_scientific_metadata_cannot_be_rewritten_in_admin_form():
    for field in ['cube:dimensions','gee:units','scale','offset','assets']:
        with pytest.raises(OpenEOApiException):service.dataset_update('synthetic-admin','example',{'revision':1,field:{}})


@pytest.mark.parametrize('role,scope,resource',[
    ('researcher','user','datasets'),('viewer','user','datasets'),
    ('dataset_manager','user','users'),('dataset_manager','user','jobs'),
    ('dataset_manager','user','audit'),('admin','script','users'),
])
def test_api_refuses_before_querying_other_accounts(monkeypatch,role,scope,resource):
    from gee import auth,db
    from gee.api.admin import register_admin_api
    app=Flask(__name__)
    @app.errorhandler(OpenEOApiException)
    def problem(error):return jsonify({'code':error.code,'message':str(error)}),error.status_code
    monkeypatch.setattr(auth,'resolve',lambda token:{'user_id':'synthetic-member','scope':scope,'role':role})
    def never_connect():raise AssertionError('Unauthorized request reached database')
    monkeypatch.setattr(db,'connect',never_connect)
    register_admin_api(app)
    response=app.test_client().get('/workbench/admin/v1/'+resource,headers={'Authorization':'Bearer basic//synthetic-session'})
    assert response.status_code==403
