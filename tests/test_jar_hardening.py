"""Replacement failures preserve runtime bytes and metadata follows real code."""
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

spec=importlib.util.spec_from_file_location('jar_hardener',Path(__file__).resolve().parents[1]/'engine/harden_jars.py')
hardener=importlib.util.module_from_spec(spec);spec.loader.exec_module(hardener)


def jar(path, entries):
    with zipfile.ZipFile(path,'w') as out:
        for name,content in entries.items():out.writestr(name,content)


def test_bad_replacement_does_not_modify_either_runtime(tmp_path):
    fat,spark,locked=[tmp_path/name for name in ['fat','spark','locked']]
    for path in [fat,spark,locked]:path.mkdir()
    old=fat/'old.jar';jar(old,{'io/netty/Old.class':b'original'})
    original=old.read_bytes();(spark/'jackson-core-2.18.6.jar').write_bytes(b'original runtime')
    jar(locked/'jackson-core-2.18.12.jar',{'com/fasterxml/jackson/core/JsonFactory.class':b'new'})
    manifest=tmp_path/'lock.json';manifest.write_text(json.dumps([dict(file='jackson-core-2.18.12.jar',sha256='0'*64)]))
    with pytest.raises(RuntimeError,match='digest mismatch'):
        hardener.harden(fat,spark,locked,manifest,tmp_path/'report.json')
    assert old.read_bytes()==original
    assert (spark/'jackson-core-2.18.6.jar').read_bytes()==b'original runtime'
    assert not (tmp_path/'report.json').exists()


def test_metadata_without_matching_code_is_preserved(tmp_path):
    path=tmp_path/'shaded.jar'
    jar(path,{'shaded/io/netty/Old.class':b'actual relocated code',
              'META-INF/maven/io.netty/netty-common/pom.properties':b'version=old'})
    original=path.read_bytes()
    assert hardener.strip_fat(path)['class_entries']==0
    assert path.read_bytes()==original


def test_selected_bytecode_and_its_metadata_are_removed_together(tmp_path):
    path=tmp_path/'fat.jar'
    jar(path,{'io/netty/Old.class':b'old','META-INF/versions/11/io/netty/Old.class':b'old',
              'META-INF/native/libnetty_transport_native_kqueue_aarch_64.jnilib':b'old native',
              'META-INF/maven/io.netty/netty-common/pom.properties':b'old',
              'unrelated/Keep.class':b'keep','META-INF/maven/other/pom.properties':b'keep'})
    assert hardener.strip_fat(path)=={'entries':4,'class_entries':2}
    with zipfile.ZipFile(path) as source:
        assert set(source.namelist())=={'unrelated/Keep.class','META-INF/maven/other/pom.properties'}


def test_sqlite_native_code_does_not_outlive_removed_component_metadata(tmp_path):
    path=tmp_path/'fat.jar'
    jar(path,{'org/sqlite/JDBC.class':b'old',
              'org/sqlite/native/Mac/aarch64/libsqlitejdbc.jnilib':b'old native',
              'META-INF/maven/org.xerial/sqlite-jdbc/pom.properties':b'version=3.34.0',
              'unrelated/Keep.class':b'keep'})
    assert hardener.strip_fat(path)=={'entries':3,'class_entries':1}
    with zipfile.ZipFile(path) as source:assert source.namelist()==['unrelated/Keep.class']


def test_orphan_native_component_is_removed_without_fabricating_its_version(tmp_path):
    path=tmp_path/'native-only.jar'
    jar(path,{'META-INF/native/libnetty_transport_native_kqueue_aarch_64.jnilib':b'old native',
              'META-INF/maven/io.netty/netty-transport/pom.properties':b'old metadata'})
    assert hardener.strip_fat(path)=={'entries':2,'class_entries':0}
    with zipfile.ZipFile(path) as source:assert source.namelist()==[]


def test_exact_jackson_replacement_preserves_scala_and_other_modules(tmp_path):
    fat,spark,locked=[tmp_path/name for name in ['fat','spark','locked']]
    for path in [fat,spark,locked]:path.mkdir()
    for name in ['jackson-core-2.18.6.jar','jackson-module-scala_2.13-2.18.6.jar','jackson-annotations-2.18.6.jar','commons-lang-2.6.jar']:
        (spark/name).write_bytes(b'keep or replace')
    updated=locked/'jackson-core-2.18.12.jar';jar(updated,{'com/fasterxml/jackson/core/JsonFactory.class':b'new'})
    manifest=tmp_path/'lock.json';manifest.write_text(json.dumps([dict(file=updated.name,sha256=hashlib.sha256(updated.read_bytes()).hexdigest())]))
    hardener.harden(fat,spark,locked,manifest,tmp_path/'report.json')
    assert not (spark/'jackson-core-2.18.6.jar').exists()
    assert (spark/updated.name).read_bytes()==updated.read_bytes()
    assert len(list(spark.glob('*.jar')))==4
