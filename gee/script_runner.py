"""Untrusted Python runs in a dedicated macOS Seatbelt process."""
import os
import runpy
import openeo
connection = openeo.connect(os.environ["OPENEO_URL"])
connection.authenticate_bearer_token("basic//" + os.environ.pop("OPENEO_TOKEN"))
runpy.run_path(os.environ["GEE_SCRIPT_PATH"], init_globals={"connection":connection}, run_name="__main__")
