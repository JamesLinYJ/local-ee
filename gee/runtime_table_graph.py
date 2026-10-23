"""Closed graph lineage for operations on actual classified feature tables."""
from __future__ import annotations

from .runtime_table_spec import PROCESS, runtime_columns
from .sample_table_spec import MAX_OPERATIONS, decode_sample_operation
from .sample_table_schema import decode_operation_chain


CLASSIFIERS = frozenset({"local_ee_smile_rf_classify_rows", "local_ee_smile_rf_classify_samples"})


def runtime_table_chain(nodes, reference):
    seen, operations = set(), []
    while True:
        if reference in seen or reference not in nodes:
            raise ValueError("Runtime table chain contains a cycle or unknown producer")
        seen.add(reference)
        node = nodes[reference]
        if node["process_id"] in CLASSIFIERS:
            return node, tuple(reversed(operations))
        if node["process_id"] != PROCESS:
            raise ValueError("Runtime table operations require an audited classification producer")
        operations.append(node["arguments"]["spec"])
        if len(operations) > MAX_OPERATIONS:
            raise ValueError("Runtime table chains support at most16 operations")
        reference = node["arguments"]["data"]["from_node"]


def runtime_table_columns(nodes, reference):
    from .sampling_graph import sample_chain

    origin, operations = runtime_table_chain(nodes, reference)
    prior = ()
    if origin["process_id"] == "local_ee_smile_rf_classify_samples":
        _, prior = sample_chain(nodes, origin["arguments"]["data"]["from_node"])
    if len(prior) + len(operations) > MAX_OPERATIONS:
        raise ValueError("Combined sampled and classified table chain exceeds16 operations")
    # Apply the existing bounded schema-wire scan to the entire chain as well
    # as each producer's local checks. Actual runtime copy/predicate work is
    # carried on the trusted table and checked separately by the handler.
    decode_operation_chain((*prior, *operations))
    return runtime_columns(origin["arguments"]["spec"], operations)


def runtime_table_known_empty(nodes, reference):
    from .rf_validation_spec import decode_feature_rows
    from .sampling_graph import sample_chain
    from .sampling_spec import decode_sampling_spec

    origin, operations = runtime_table_chain(nodes, reference)
    if origin["process_id"] == "local_ee_smile_rf_classify_rows":
        if not decode_feature_rows(origin["arguments"]["rows"])["features"]:
            return True
    else:
        sampler, prior = sample_chain(nodes, origin["arguments"]["data"]["from_node"])
        sample = decode_sampling_spec(sampler["arguments"]["spec"])
        if not sample["regions"]["features"]:
            return True
        if sample.get("image_sample", {}).get("num_pixels") == 0:
            return True
        operations = (*prior, *operations)
    return any(op["operation"] == "limit" and op["count"] == 0
               for op in map(decode_sample_operation, operations))
