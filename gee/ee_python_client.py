"""Offline initialization of the pinned Earth Engine Python object model."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

if __package__:
    from .ee_python_transport import LocalEETransport, LocalEETransportError
else:
    from ee_python_transport import LocalEETransport, LocalEETransportError


SIGNATURES_SHA256 = "8279bfd5e755f10c291a0d833aed810a5aba2e360e26ecee69f2bacaeecb3d01"
SDK_VERSION = "1.7.49"
MAX_SIGNATURE_BYTES = 1_048_576
_LOCAL_PROJECT = "local-ee"
_NETWORK_DATA_METHODS = (
    "getInfo", "getAsset", "getList", "listImages", "listAssets", "listBuckets",
    "getFeatureViewTilesKey", "listFeatures", "getPixels", "computePixels",
    "computeImages", "computeFeatures", "getTileUrl", "getThumbnail", "getThumbId",
    "makeThumbUrl", "getDownloadId", "makeDownloadUrl", "getTableDownloadId",
    "makeTableDownloadUrl", "createAsset", "createFolder", "copyAsset", "renameAsset",
    "deleteAsset", "exportMap", "exportVideo", "exportClassifier", "_startIngestion",
    "startIngestion", "startExternalImageIngestion", "startTableIngestion",
    "getAssetRoots", "getAssetRootQuota", "getAssetAcl", "getIamPolicy", "setAssetAcl",
    "setIamPolicy", "setAssetProperties", "updateAsset", "createAssetHome",
    "getProjectConfig", "updateProjectConfig", "authorizeHttp", "create_assets",
)


class LocalEEInitializationError(RuntimeError):
    """Raised when a cloud-only SDK path is requested by a local script."""


def _imports():
    if __package__:
        from .ee_python_map import make_map
        from .ee_python_tasks import install_tasks
    else:
        from ee_python_map import make_map
        from ee_python_tasks import install_tasks
    return install_tasks, make_map


def _load_signatures(path: str | Path | None) -> dict[str, Any]:
    source = (
        Path(path)
        if path is not None
        else Path(__file__).resolve().parent.parent / ".native/eejs/vendor/algorithms.json"
    )
    try:
        if source.is_symlink() or not source.is_file() or source.stat().st_size > MAX_SIGNATURE_BYTES:
            raise LocalEEInitializationError("Pinned local EE signatures are unavailable")
        raw = source.read_bytes()
    except OSError:
        raise LocalEEInitializationError("Pinned local EE signatures are unavailable") from None
    if hashlib.sha256(raw).hexdigest() != SIGNATURES_SHA256:
        raise LocalEEInitializationError("Pinned local EE signatures failed verification")
    try:
        document = json.loads(raw)
        algorithms = document["algorithms"]
        if not isinstance(algorithms, list) or not algorithms:
            raise ValueError
        from ee import _cloud_api_utils
        signatures = _cloud_api_utils.convert_algorithms(document)
    except (ImportError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise LocalEEInitializationError("Pinned local EE signatures are invalid") from None
    if not signatures or len(signatures) > 10_000:
        raise LocalEEInitializationError("Pinned local EE signatures are invalid")
    return signatures


def _blocked(name: str):
    def deny(*_args, **_kwargs):
        raise LocalEETransportError(f"Google Earth Engine network operation {name} is disabled")

    return deny


def _initialize_offline(ee: Any, state: dict[str, Any]) -> None:
    data = ee.data
    data.reset()
    state["sdk_data_initialize"](
        credentials=None,
        api_base_url=state["url"].rstrip("/") + "/api",
        tile_base_url=state["url"],
        cloud_api_base_url=state["url"],
        project=_LOCAL_PROJECT,
        http_transport=None,
    )
    ee.ApiFunction.initialize()
    for dynamic_class in ee._DYNAMIC_CLASSES:
        dynamic_class.initialize()
    ee._InitializeGeneratedClasses()
    ee._InitializeUnboundMethods()
    # The upstream deprecation initializer downloads a Google STAC catalogue
    # through urllib, outside ee.data's guarded transport. Local assets and
    # their lifecycle are owned by our catalogue; never fetch cloud metadata
    # during offline initialization (including after ee.Reset()).


def configure_local_ee(
    url: str, token: str, signatures_path: str | Path | None = None
):
    """Install local-only dispatch around the official pinned ``ee`` module."""
    try:
        import ee
    except ImportError as error:
        raise LocalEEInitializationError("The pinned Earth Engine Python SDK is unavailable") from error
    if getattr(ee, "__version__", None) != SDK_VERSION:
        raise LocalEEInitializationError("The local EE adapter requires SDK 1.7.49")

    transport = LocalEETransport(url, token)
    existing = getattr(ee, "_local_ee_runtime", None)
    if existing is not None:
        if existing["url"] != url or existing["token"] != token:
            raise LocalEEInitializationError("This process already has a different local EE session")
        ee.Initialize()
        return ee

    signatures = _load_signatures(signatures_path)
    state = {
        "url": url,
        "token": token,
        "transport": transport,
        "sdk_data_initialize": ee.data.initialize,
        "signatures": signatures,
    }
    ee._local_ee_runtime = state
    ee.Reset()

    def get_algorithms():
        return copy.deepcopy(state["signatures"])

    def local_compute_value(obj):
        try:
            response = transport.request(
                {"action": "evaluate", "expression": encode(obj)}
            )
        except LocalEETransportError as error:
            raise ee.ee_exception.EEException(str(error)) from error
        if "value" not in response:
            raise ee.ee_exception.EEException("Local EE returned no value")
        return response["value"]

    def encode(obj):
        return ee.serializer.encode(obj, is_compound=True, for_cloud_api=False)

    def no_cloud_resource():
        current = ee.data._get_state()
        current.cloud_api_resource = None
        current.cloud_api_resource_raw = None

    ee.data.getAlgorithms = get_algorithms
    ee.data.computeValue = local_compute_value
    ee.data._install_cloud_api_resource = no_cloud_resource

    def initialize(*args, **kwargs):
        if args:
            raise LocalEEInitializationError("Local ee.Initialize accepts no positional credentials")
        unknown = set(kwargs) - {"url", "opt_url"}
        if unknown:
            raise LocalEEInitializationError(
                "Local ee.Initialize does not accept credentials, project or cloud options"
            )
        if "url" in kwargs and "opt_url" in kwargs:
            raise LocalEEInitializationError("Specify only one local EE URL")
        requested_url = kwargs.get("url", kwargs.get("opt_url"))
        if requested_url is not None and requested_url != state["url"]:
            raise LocalEEInitializationError("ee.Initialize can use only this script's local API URL")
        if not ee.data.is_initialized():
            _initialize_offline(ee, state)

    def disable_auth(*_args, **_kwargs):
        raise LocalEEInitializationError("Google authentication is disabled in the local runtime")

    ee.Initialize = initialize
    ee.Authenticate = disable_auth
    ee.oauth.authenticate = disable_auth
    ee.oauth.get_credentials_arguments = disable_auth
    ee.data.get_persistent_credentials = disable_auth
    ee.data.initialize = _blocked("ee.data.initialize")
    ee.data.setCloudApiKey = _blocked("setCloudApiKey")
    ee.data.setCloudApiUserProject = _blocked("setCloudApiUserProject")
    ee.data._execute_cloud_call = _blocked("Cloud API")
    ee.data._get_cloud_projects = _blocked("Cloud API")
    ee.data._get_cloud_projects_raw = _blocked("Cloud API")
    for name in _NETWORK_DATA_METHODS:
        setattr(ee.data, name, _blocked(name))

    ee.Initialize()
    install_tasks, make_map = _imports()
    install_tasks(ee, transport.request, encode)
    local_map = make_map(ee, transport.request, encode)
    ee.Map = local_map
    return ee
