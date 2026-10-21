"""Complete pinned signatures plus the introspected public SDK callable surface."""
from __future__ import annotations

from collections import Counter, defaultdict
import copy
import hashlib
import inspect
import json
from pathlib import Path
from unittest.mock import patch

from gee.ee_python_client import SDK_VERSION, _load_signatures
from .bindings import describe_callable, describe_class
from .offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[2]


def _algorithm_bindings(container, path, names):
    rows = []
    for key, value in sorted(container.items()):
        child_path = f"{path}.{key}"
        if isinstance(value, dict):
            rows.extend(_algorithm_bindings(value, child_path, names))
        elif callable(value):
            rows.append(describe_callable(child_path, value, names))
    return rows


def _module_surface(module, path, names):
    functions, classes = [], []
    for key, value in sorted(vars(module).items()):
        if key.startswith("_") or not getattr(value, "__module__", "").startswith("ee"):
            continue
        if inspect.isclass(value):
            class_path = f"{path}.{key}"
            classes.append(describe_class(class_path, value, names))
            # Export.image.toDrive etc. are public nested SDK classes.
            for child_name, child in sorted(vars(value).items()):
                if not child_name.startswith("_") and inspect.isclass(child):
                    classes.append(describe_class(f"{class_path}.{child_name}", child, names))
        elif inspect.isfunction(value):
            functions.append(describe_callable(f"{path}.{key}", value, names))
    return {"module": path, "classes": classes, "functions": functions}


def build_inventory(root=ROOT):
    """Inspect an unadapted SDK in a process dedicated to inventory generation.

    Local runtime configuration replaces upstream public methods. Refuse that
    state rather than producing an incomplete catalogue or disturbing a live
    local session; the CLI starts with an unadapted SDK in a fresh process.
    """
    root = Path(root)
    signature_path = root / "vendor/earthengine-js/algorithms.json"
    signatures = _load_signatures(signature_path)
    raw = json.loads(signature_path.read_text(encoding="utf-8"))["algorithms"]
    lock = json.loads((root / "vendor/earthengine-python/upstream-lock.json").read_text())
    names = set(signatures)
    with OfflineGuard() as guard:
        import ee

        if getattr(ee, "_local_ee_runtime", None) is not None:
            raise RuntimeError(
                "Python API inventory requires a pristine SDK process; "
                "run .venv/bin/python -m scripts.ee_python_inventory in a "
                "separate process before configuring the local EE runtime"
            )
        if ee.__version__ != SDK_VERSION:
            raise ValueError("Python inventory requires the pinned SDK version")
        # Initialize only object-model functions, never ee.Initialize/data/OAuth.
        with patch.object(ee.data, "getAlgorithms", lambda: copy.deepcopy(signatures)):
            ee.ApiFunction.initialize()
            for cls in ee._DYNAMIC_CLASSES:
                cls.initialize()
            ee._InitializeGeneratedClasses()
            ee._InitializeUnboundMethods()
        if set(ee.ApiFunction.allSignatures()) != names:
            raise ValueError("Initialized SDK signature set differs from pinned catalogue")
        surfaces = [_module_surface(ee, "ee", names)]
        # These public transport/export surfaces are listed, not claimed locally supported.
        surfaces.extend(_module_surface(module, path, names) for module, path in (
            (ee.batch, "ee.batch"), (ee.data, "ee.data"), (ee.oauth, "ee.oauth"),
            (ee.serializer, "ee.serializer"), (ee.deserializer, "ee.deserializer"),
        ))
        unbound = _algorithm_bindings(ee.Algorithms, "ee.Algorithms", names)

    bindings = defaultdict(list)
    all_callables = list(unbound)
    for surface in surfaces:
        all_callables.extend(surface["functions"])
        for cls in surface["classes"]:
            all_callables.extend([cls["constructor"], *cls["methods"]])
    for row in all_callables:
        for name in row["algorithm_names"]:
            bindings[name].append(row["path"])
    algorithms = []
    for signature in sorted(raw, key=lambda item: item["name"].removeprefix("algorithms/")):
        name = signature["name"].removeprefix("algorithms/")
        algorithms.append({
            "name": name,
            "official_signature": signature,
            "python_bindings": sorted(set(bindings[name])),
            "generic_python_entry_point": "ee.ApiFunction.call_",
            "evidence": {
                "signature_present": True,
                "named_python_binding_identified": bool(bindings[name]),
                "serialization": "not_exhaustively_probed",
                "compilation": "not_verified_per_signature",
                "engine_execution": "not_verified_per_signature",
                "independent_numerical_validation": "not_verified_per_signature",
                "google_same_data_comparison": "not_run",
            },
        })
    return {
        "schema": "local-ee-python-api-inventory/v1",
        "source": {
            "package": lock["package"], "sdk": SDK_VERSION,
            "upstream_commit": lock["revision"],
            "signature_sha256": hashlib.sha256(signature_path.read_bytes()).hexdigest(),
        },
        "scope": {
            "python": "Public classes (including inherited methods) and functions exported by ee, ee.batch, ee.data, ee.oauth, ee.serializer, ee.deserializer; nested export classes and ee.Algorithms included",
            "binding_mapping": "SDK attached signature or explicit upstream ApiFunction call; indirect helper calls are not guessed",
            "compatibility": "Visible callables, metadata and bindings do not establish serialization, compilation, execution, numerical equivalence or Google comparison; no compatibility percentage",
            "overloads": "All Python positional/keyword/variadic parameters and exact official arguments/defaults retained; Python helpers may accept forms beyond the single algorithm signature",
            "transport_surfaces": "Listed for completeness; cloud-only SDK methods remain disabled by the local runtime",
        },
        "summary": {
            "algorithm_signature_count": len(algorithms),
            "algorithm_argument_count": sum(len(row.get("arguments", [])) for row in raw),
            "python_class_count": sum(len(surface["classes"]) for surface in surfaces),
            "python_callable_count": len(all_callables),
            "named_binding_algorithm_count": sum(bool(bindings[name]) for name in names),
            "unmapped_named_algorithms": sorted(name for name in names if not bindings[name]),
            "families": dict(sorted(Counter(name.split(".", 1)[0] for name in names).items())),
        },
        "network_evidence": guard.evidence(),
        "python_surfaces": surfaces,
        "unbound_algorithm_callables": unbound,
        "algorithms": algorithms,
    }
