"""Type edges for dynamic sample tables and models inside the existing DAG."""
from __future__ import annotations

from .sampling_spec import decode_sampling_spec, decode_training_spec
from .sample_table_spec import MAX_OPERATIONS
from .sample_table_schema import sampled_columns


SAMPLE_PROCESS = "local_ee_sample_regions"
TRAIN_PROCESS = "local_ee_train_minimum_distance"
CLASSIFY_PROCESS = "local_ee_minimum_distance"
OP_PROCESS = "local_ee_sample_table_op"


def sample_chain(nodes, key):
    """Return the fixed sampler and ordered, opaque operation specifications."""
    seen = set()
    operations = []
    while True:
        if key in seen:
            raise ValueError("Sample-table operations contain a cycle")
        seen.add(key)
        if key not in nodes:
            raise ValueError("Sample-table operation references an unknown node")
        node = nodes[key]
        if node['process_id'] == SAMPLE_PROCESS:
            return node, tuple(reversed(operations))
        if node['process_id'] != OP_PROCESS:
            raise ValueError("Sampled training data must come directly from local_ee_sample_regions or its audited operations")
        operations.append(node['arguments']['spec'])
        if len(operations) > MAX_OPERATIONS:
            raise ValueError("Sample-table chains support at most16 operations")
        key = node['arguments']['data']['from_node']


def _sampling_origin(nodes, key):
    """Retain the historical origin-only helper for existing callers."""
    return sample_chain(nodes, key)[0]


def validate_sampling_dependencies(nodes):
    """A model reference must name the audited sampled-training producer.

    Called only after ordinary node, canonical reference and local-spec checks.
    JSON string specifications stay data; this function never traverses their
    property dictionaries as process nodes or graph dependencies.
    """
    from .smile_rf_processes import validate_rf_dependencies
    from .rf_validation_processes import validate_validation_dependencies

    validate_rf_dependencies(nodes)
    validate_validation_dependencies(nodes)
    for key, node in nodes.items():
        name, arguments = node["process_id"], node.get("arguments", {})
        if name == OP_PROCESS:
            origin, operations = sample_chain(nodes, key)
            sampled_columns(decode_sampling_spec(origin['arguments']['spec']), operations)
        if name == TRAIN_PROCESS:
            source, operations = sample_chain(nodes, arguments['data']['from_node'])
            sample = decode_sampling_spec(source["arguments"]["spec"])
            training = decode_training_spec(arguments["spec"])
            available = set(sampled_columns(sample, operations)) - {"system:index", ".geo"}
            if training["class_property"] not in available or not set(training["schema"]) <= available:
                raise ValueError("Training fields must exist in the declared sample-table columns")
        if name == CLASSIFY_PROCESS:
            model = arguments["model"]
            if type(model) is dict and set(model) == {"from_node"}:
                source = nodes[model["from_node"]]
                if source["process_id"] != TRAIN_PROCESS:
                    raise ValueError("Dynamic classifier models must come from local_ee_train_minimum_distance")
        if name in {SAMPLE_PROCESS, 'local_ee_remap', 'local_ee_pixel_math'}:
            source = nodes[arguments["data"]["from_node"]]
            if source["process_id"] in {SAMPLE_PROCESS, TRAIN_PROCESS, OP_PROCESS, "local_ee_table", "save_result"}:
                raise ValueError("Sampling data must be a raster cube, not a feature table or model")
