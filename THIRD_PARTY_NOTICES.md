# Third-party sources and dependencies

This repository includes pinned third-party source snapshots in `vendor/`.
Their original copyright notices, licenses and attribution remain in place.
See `upstream-lock.json` for source URLs, versions and commits.

| Component | Source | License notice |
| --- | --- | --- |
| openEO Python driver | Open-EO/openeo-python-driver | `vendor/openeo-python-driver/LICENSE` |
| openEO GeoPySpark driver | Open-EO/openeo-geopyspark-driver | `vendor/openeo-geopyspark-driver/LICENSE` |
| GeoPySpark | Open-EO/geopyspark | `vendor/geopyspark/LICENSE` |
| GDAL | OSGeo GDAL | `vendor/gdal/LICENSE.TXT`; additional component notices within that tree |
| GDAL warp bindings | Open-EO/gdal-warp-bindings | `vendor/gdal-warp-bindings/LICENSE` and Java utility notices |
| JEP | ninia/jep | `vendor/jep/LICENSE` |
| Earth Engine JavaScript client | google/earthengine-api, Apache-2.0 | `vendor/earthengine-js/LICENSE`, `upstream-lock.json` |

The Earth Engine client is an offline protocol binding. Google-hosted data and
service-side implementations are not included. This project is not affiliated
with or endorsed by Google.

Python and frontend package licenses remain those of their respective packages.
The large JVM artifacts are not stored in Git. Their versions, source URLs and
SHA-256 values are tracked in the engine manifests, and their embedded license
and notice metadata must be preserved when restoring them.

The root project does not grant a new open-source license merely by being
hosted on GitHub. Any future choice of license for original project code needs
to be made by its owner; third-party licenses continue to apply independently.
