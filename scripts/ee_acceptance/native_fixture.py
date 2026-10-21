"""Run one bounded isolated native fixture; preserve failures for diagnosis."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import time
import uuid

from gee import graph


def run_native(root: Path, audit: Path, folder: Path, process, metadata, items):
    graph.validate(process)
    for key, (_, selection) in graph.collection_loads(process).items():
        catalog = copy.deepcopy(metadata)
        catalog["links"] = []
        for iid in selection:
            filename = f"item-{key}-{iid}.json"
            (folder/filename).write_text(json.dumps(next(item for item in items if item["id"] == iid)))
            catalog["links"].append({"rel": "item", "href": str(folder/filename), "type": "application/geo+json"})
        (folder/("catalog-"+key+".json")).write_text(json.dumps(catalog))
    (folder/"graph.json").write_text(json.dumps(graph.materialize(process, {metadata["id"]: metadata}, str(folder))))
    spec = importlib.util.spec_from_file_location("native_launch", root/"scripts/native.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    os.environ.update(launcher.environment())
    from gee.native.runtime import NativeClient
    task = NativeClient().launch({"id": str(uuid.uuid4()), "kind": "batch"}, folder=folder)
    print("Native isolated fixture started", flush=True)
    try:
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            task.reload()
            if task.status == "exited":
                break
            time.sleep(1)
        else:
            raise RuntimeError("Native fixture exceeded 300 seconds")
        (audit/"engine.log").write_bytes(task.logs())
        if task.attrs["State"]["ExitCode"] != 0:
            raise RuntimeError("Native engine failed; retained engine.log and inputs")
    finally:
        task.reload()
        if task.status in {"running", "starting"}:
            task.stop()
        task.remove()
    outputs = list((folder/"out").glob("*.tif"))
    if len(outputs) != 1:
        raise RuntimeError("Expected one native GeoTIFF output")
    return outputs[0]
