"""Pinned independent numerical expectations for the raw label fixture."""
from ee_label_training_reference import (
    independent_training_model,
    load_fixture,
    model_centers_as_pairs,
    reference_filter_stages,
    reference_sample_rows,
)


def test_raw_label_grid_reference_covers_mask_filter_threshold_and_overlap_weights():
    data = load_fixture()
    stages = reference_filter_stages(data)
    rows, counts = reference_sample_rows(data, diagnostics=True)
    reference = data["reference_expectations"]
    assert reference["target_export_region"] == data["target_export_region"]
    assert counts == {"selected_cells": 17, "unmapped_labels": 1, "source_nodata": 1}
    mapping = dict(zip(data["label_remap"]["from"], data["label_remap"]["to"]))
    assert [mapping.get(code) for code in data["items"][0]["pixel_values"]["label_code"]] == \
        reference["mapped_label_values"]
    assert len(rows) == reference["sample_candidate_rows"] == 15
    assert len(stages["non_null"]) == reference["sample_not_null_rows"] == 14
    assert len(stages["eligible"]) == reference["sample_expression_rows_before_limit"] == 11
    assert len(stages["limited"]) == reference["sample_limited_rows"] == 8
    assert [row["id"] for row in rows] == reference["sample_candidate_feature_system_indexes"]
    assert [row["id"] for row in stages["limited"]] == [
        "f0_r0_c1", "f1_r0_c0", "f1_r0_c1", "f2_r0_c1",
        "f2_r1_c1", "f2_r1_c2", "f3_r0_c3", "f3_r1_c3",
    ]
    # The repeated west-overlap cell remains three independent samples and its
    # three copies contribute to the exact class center. A zero class remains
    # valid under the >= 0 threshold; false and null controls are filtered.
    west_overlap = [row for row in stages["limited"]
                    if row["row"] == 0 and row["col"] == 1]
    assert [row["feature"] for row in west_overlap] == [0, 1, 2]
    assert any(row["properties"]["landcover"] == 0 for row in stages["eligible"])
    assert not any(row["properties"]["plot_id"] in {"false-keep", "false-control", "site-drop"}
                   for row in stages["eligible"])
    assert any(row["properties"]["plot_id"] == "valid-tail" for row in stages["eligible"])
    assert not any(row["properties"]["plot_id"] == "valid-tail" for row in stages["limited"])

    model = independent_training_model(data)
    assert [row["id"] for row in stages["limited"]] == reference["sample_limited_feature_system_indexes"]
    assert model_centers_as_pairs(model) == reference["class_means_in_red_nir_order"]
