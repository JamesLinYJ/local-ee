"""Run an untrusted openEO / Earth Engine Python script in its Seatbelt process."""

import os
import runpy
from pathlib import Path

import openeo

from ee_python_client import configure_local_ee


url = os.environ["OPENEO_URL"]
token = os.environ.pop("OPENEO_TOKEN")
connection = openeo.connect(url)
connection.authenticate_bearer_token("basic//" + token)
signatures = Path(__file__).resolve().parent.parent / ".native/eejs/vendor/algorithms.json"
ee = configure_local_ee(url, token, signatures_path=signatures)
del token

runpy.run_path(
    os.environ["GEE_SCRIPT_PATH"],
    init_globals={"connection": connection, "ee": ee, "Map": ee.Map},
    run_name="__main__",
)
