"""Official local batch entry point with local-only config and restrictive umask."""
import json
import os
from pathlib import Path
os.umask(0o077)
from openeogeotrellis.deploy.run_graph_locally import run_graph_locally
try:
    run_graph_locally(json.loads(Path('/job/graph.json').read_text()), Path('/job/out'))
finally:
    # Upstream local runner makes results world writable; undo that inside the isolated job directory.
    for p in Path('/job/out').rglob('*'):
        if p.is_file() and not p.is_symlink(): p.chmod(0o640)
