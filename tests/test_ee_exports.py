import csv
from pathlib import Path
import uuid

import pytest

from gee.ee_translate import UnsupportedEEError
from gee.services.ee_exports import export_options, finalize_export


def test_export_prefix_and_selectors_are_applied(tmp_path):
    jid=str(uuid.uuid4()); folder=tmp_path/'jobs'/jid/'out'; folder.mkdir(parents=True)
    (folder/'openEO.csv').write_text('feature_index,red,nir\n0,0.2,0.6\n')
    options=export_options('export_table',{'fileNamePrefix':'区域统计','selectors':['nir','red']},['red','nir'])
    finalize_export(tmp_path,{'id':jid,'context':{'protocol':'earthengine','result_kind':'export',**options}})
    assert sorted(p.name for p in folder.iterdir())==['区域统计.csv']
    with (folder/'区域统计.csv').open() as f:
        rows=list(csv.reader(f))
    assert rows==[['nir','red'],['0.6','0.2']]


@pytest.mark.parametrize('prefix',['../escape','a/b','a\\b','.hidden','a\nname','a\x00','a.',''])
def test_export_prefix_rejects_paths_and_control_characters(prefix):
    with pytest.raises(ValueError):export_options('export_image',{'fileNamePrefix':prefix},[])


def test_export_selectors_are_validated_before_scheduling():
    with pytest.raises(UnsupportedEEError):export_options('export_table',{'selectors':['missing']},['nir'])
    with pytest.raises(UnsupportedEEError):export_options('export_image',{'selectors':['nir']},['nir'])


def test_export_finalizer_keeps_regular_file_boundary(tmp_path):
    jid=str(uuid.uuid4()); folder=tmp_path/'jobs'/jid/'out'; folder.mkdir(parents=True)
    outside=tmp_path/'source.csv'; outside.write_text('secret\n')
    (folder/'openEO.csv').symlink_to(outside)
    with pytest.raises(ValueError):
        finalize_export(tmp_path,{'id':jid,'context':{'protocol':'earthengine','result_kind':'export','file_prefix':'result'}})
    assert outside.read_text()=='secret\n'


@pytest.mark.parametrize('text', ['雪,"甲"\r\n保持回车\r和换行\n', 'x'*200000])
def test_csv_finalizer_preserves_line_endings_and_bounded_large_cells(tmp_path,text):
    jid=str(uuid.uuid4()); folder=tmp_path/'jobs'/jid/'out'; folder.mkdir(parents=True)
    target=folder/'openEO.csv'
    with target.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['note','unused']);writer.writerow([text,1])
    prior=csv.field_size_limit()
    finalize_export(tmp_path,{'id':jid,'context':{'protocol':'earthengine','result_kind':'export','selectors':['note']}})
    assert csv.field_size_limit()==prior
    try:
        csv.field_size_limit(1048576)
        with target.open(encoding='utf-8',newline='') as stream:
            assert list(csv.reader(stream))==[['note'],[text]]
    finally:csv.field_size_limit(prior)


def test_invalid_csv_encoding_is_a_normal_publication_failure(tmp_path):
    jid=str(uuid.uuid4()); folder=tmp_path/'jobs'/jid/'out'; folder.mkdir(parents=True)
    (folder/'openEO.csv').write_bytes(b'note\n\xff\n')
    prior=csv.field_size_limit()
    with pytest.raises(ValueError,match='UTF-8 CSV'):
        finalize_export(tmp_path,{'id':jid,'context':{'protocol':'earthengine','result_kind':'export','selectors':['note']}})
    assert csv.field_size_limit()==prior
