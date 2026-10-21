"""Code Editor-style map helpers backed by local EE jobs and map events."""

from __future__ import annotations

import math
from typing import Any


_VIS_FIELDS = {"bands", "min", "max", "gamma", "palette"}


def _vis_params(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Local Map visualization parameters must be an object")
    unsupported = set(value) - _VIS_FIELDS
    if unsupported:
        raise ValueError(
            "Unsupported local Map visualization options: "
            + ", ".join(sorted(unsupported))
        )
    return dict(value)


def _expression(ee: Any, encode: Any, value: Any) -> Any:
    computed = getattr(ee, "computedobject", None)
    computed_type = getattr(computed, "ComputedObject", ())
    if computed_type and isinstance(value, computed_type):
        result = encode(value)
    elif isinstance(value, dict) and value.get("type") in {
        "Point",
        "LineString",
        "LinearRing",
        "Polygon",
        "MultiPoint",
        "MultiLineString",
        "MultiPolygon",
        "Feature",
    }:
        result = value
    else:
        result = encode(value)
    if not isinstance(result, (dict, list, str, int, float, bool)):
        raise ValueError("Local Map expression is not serializable")
    return result


def _map_result(send: Any, encode: Any, image: Any, vis: Any) -> dict[str, Any]:
    response = send(
        {
            "action": "map",
            "expression": encode(image),
            "options": {"vis_params": _vis_params(vis)},
        }
    )
    if not isinstance(response, dict):
        raise ValueError("Local map request returned an invalid response")
    job_id = response.get("job_id")
    if not isinstance(job_id, str) or not job_id or len(job_id) > 128:
        raise ValueError("Local map request did not return a local job ID")
    return response


class LocalMap:
    """A small Code Editor-shaped facade; raster work continues asynchronously."""

    def __init__(self, ee: Any, send: Any, encode: Any):
        self._ee = ee
        self._send = send
        self._encode = encode

    def addLayer(
        self,
        image: Any,
        visParams: dict[str, Any] | None = None,
        name: str | None = None,
        shown: bool = True,
        opacity: float = 1,
    ) -> dict[str, Any]:
        if not isinstance(shown, bool):
            raise ValueError("shown must be a boolean")
        if isinstance(opacity, bool) or not isinstance(opacity, (int, float)):
            raise ValueError("opacity must be between 0 and 1")
        if not math.isfinite(opacity) or not 0 <= opacity <= 1:
            raise ValueError("opacity must be between 0 and 1")
        options = {
            "vis_params": _vis_params(visParams),
            "name": "图层" if name is None else str(name),
            "shown": shown,
            "opacity": opacity,
        }
        response = self._send(
            {"action": "map", "expression": self._encode(image), "options": options}
        )
        if not isinstance(response, dict) or not isinstance(
            response.get("job_id"), str
        ):
            raise ValueError("Local map request did not return a local job ID")
        return response

    def centerObject(self, geometry: Any, zoom: float | None = None) -> Any:
        options = {"geometry": _expression(self._ee, self._encode, geometry)}
        if zoom is not None:
            options["zoom"] = zoom
        return self._send({"action": "map_view", "options": options})

    def setCenter(
        self, longitude: float, latitude: float, zoom: float | None = None
    ) -> Any:
        options: dict[str, Any] = {"center": [longitude, latitude]}
        if zoom is not None:
            options["zoom"] = zoom
        return self._send({"action": "map_view", "options": options})

    def setZoom(self, zoom: float) -> Any:
        return self._send({"action": "map_zoom", "options": {"zoom": zoom}})

    def clear(self) -> Any:
        return self._send({"action": "map_clear", "options": {}})


def make_map(ee: Any, send: Any, encode: Any) -> LocalMap:
    """Create a per-script local Map facade for injection into Python globals."""
    return LocalMap(ee, send, encode)


def install_image_map_id(ee: Any, send: Any, encode: Any) -> None:
    """Replace cloud map creation with an explicit asynchronous local job."""

    def local_map_id(image: Any, vis_params: Any = None) -> dict[str, Any]:
        result = _map_result(send, encode, image, vis_params)
        job_id = result["job_id"]
        return {
            "mapid": "local:" + job_id,
            "token": "",
            "job_id": job_id,
            "state": "READY",
            "pending": True,
            "local": True,
            "warnings": result.get("warnings", []),
        }

    ee.Image.getMapId = local_map_id

    def local_data_map_id(params: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(params, dict) or "image" not in params:
            raise ValueError("Local getMapId requires an Image")
        unsupported = set(params) - {"image", *_VIS_FIELDS}
        if unsupported:
            raise ValueError(
                "Unsupported local getMapId options: "
                + ", ".join(sorted(unsupported))
            )
        image = params["image"]
        vis = {key: value for key, value in params.items() if key in _VIS_FIELDS}
        return local_map_id(image, vis)

    ee.data.getMapId = local_data_map_id
