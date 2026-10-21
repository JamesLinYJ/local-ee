"""Publication must not silently restore a different JVM dependency."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('dependency_restore',
    Path(__file__).resolve().parents[1] / 'scripts/fetch_engine_dependencies.py')
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


def test_existing_mismatched_artifact_is_preserved(tmp_path):
    artifact = tmp_path / 'sample.jar'
    artifact.write_bytes(b'keep this original')
    item = {'file': 'sample.jar', 'url': 'https://example.org/sample.jar',
            'sha256': hashlib.sha256(b'different').hexdigest()}
    with pytest.raises(ValueError, match='preserved'):
        restore.restore(tmp_path, item)
    assert artifact.read_bytes() == b'keep this original'


def test_failed_download_never_publishes_artifact(tmp_path, monkeypatch):
    import io
    class Response(io.BytesIO):
        url = 'https://example.org/sample.jar'
    monkeypatch.setattr(restore.urllib.request, 'urlopen', lambda *a, **kw: Response(b'wrong bytes'))
    item = {'file': 'sample.jar', 'url': 'https://example.org/sample.jar',
            'size': 11, 'sha256': hashlib.sha256(b'right bytes').hexdigest()}
    with pytest.raises(ValueError, match='checksum'):
        restore.restore(tmp_path, item)
    assert list(tmp_path.iterdir()) == []
