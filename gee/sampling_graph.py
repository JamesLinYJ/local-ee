"""Type edges for dynamic sample tables and models inside the existing DAG."""
from __future__ import annotations

from .sampling_spec import decode_sampling_spec, decode_training_spec, sampling_columns
from .sample_table_spec import MAX_OPERATIONS


SAMPLE_PROCESS = "local_ee_sample_regions"
TRAIN_PROCESS = "local_ee_train_minimum_distance"
CLASSIFY_PROCESS = "local_ee_minimum_distance"
OP_PROCESS = "local_ee_sample_table_op"


def _sampling_origin(nodes, key):
    """Linear operation chains retain the sampler's original schema and identity."""
    seen = set()
    operations = 0
    while True:
        if key in seen:
            raise ValueError("Sample-table operations contain a cycle")
        seen.add(key)
        node = nodes[key]
        if node['process_id'] == SAMPLE_PROCESS:
            return node
        if node['process_id'] != OP_PROCESS:
            raise ValueError("Sampled training data must come directly from local_ee_sample_regions or its audited operations")
        operations += 1
        if operations > MAX_OPERATIONS:
            raise ValueError("Sample-table chains support at most16 operations")
        key = node['arguments']['data']['from_node']


def validate_sampling_dependencies(nodes):
    """A model reference must name the audited sampled-training producer.

    Called only after ordinary node, canonical reference and local-spec checks.
    JSON string specifications stay data; this function never traverses their
    property dictionaries as process nodes or graph dependencies.
    """
    for key, node in nodes.items():
        name, arguments = node["process_id"], node.get("arguments", {})
        if name == OP_PROCESS:
            _sampling_origin(nodes, key)
        if name == TRAIN_PROCESS:
            source = _sampling_origin(nodes, arguments['data']['from_node'])
            sample = decode_sampling_spec(source["arguments"]["spec"])
            training = decode_training_spec(arguments["spec"])
            available = set(sampling_columns(sample)) - {"system:index", ".geo"}
            if training["class_property"] not in available or not set(training["schema"]) <= available:
                raise ValueError("Training fields must exist in the declared sample-table columns")
        if name == CLASSIFY_PROCESS:
            model = arguments["model"]
            if type(model) is dict and set(model) == {"from_node"}:
                source = nodes[model["from_node"]]
                if source["process_id"] != TRAIN_PROCESS:
                    raise ValueError("Dynamic classifier models must come from local_ee_train_minimum_distance")
        if name in {SAMPLE_PROCESS, 'local_ee_remap'}:
            source = nodes[arguments["data"]["from_node"]]
            if source["process_id"] in {SAMPLE_PROCESS, TRAIN_PROCESS, OP_PROCESS, "local_ee_table", "save_result"}:
                raise ValueError("Sampling data must be a raster cube, not a feature table or model")
