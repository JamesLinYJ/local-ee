"""Shared scalar DAGs keep every mutable Image wrapper privately owned."""
from __future__ import annotations

from dataclasses import replace

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel, Source, UnsupportedEEError
from gee.compat.earthengine.scalar_image_snapshot import (
    ScalarImageSnapshot,
    restore_scalar_image,
    snapshot_scalar_image,
)


def image():
    source = Source("sentinel-2-l2a", ("scene",), ("red", "green", "blue"))
    return Image(
        bands=[(name, Pixel("to_double", (Pixel("band", (source, name)),)))
               for name in source.names],
        props={"nested": {"labels": ["original"]}}, source=source,
        inherit_props=False, copied_props=("system:time_start",),
        footprint={"type": "Point", "coordinates": [1.0, 2.0]},
        footprint_is_absolute=True,
    )


def test_store_and_restore_detach_metadata_preserving_all_image_fields():
    translator, original = Translator([], {}, {}), image()
    snapshot = snapshot_scalar_image(translator, original)
    assert type(snapshot) is ScalarImageSnapshot
    original.props["nested"]["labels"].append("changed")
    original.footprint["coordinates"][0] = 999
    first = restore_scalar_image(translator, snapshot)
    first.props["nested"]["labels"].append("private")
    first.footprint["coordinates"][1] = 333
    first.bands.pop()
    second = restore_scalar_image(translator, snapshot)
    assert second.props == {"nested": {"labels": ["original"]}}
    assert second.footprint == {"type": "Point", "coordinates": [1.0, 2.0]}
    assert second.source is original.source
    assert second.inherit_props is False
    assert second.copied_props == ("system:time_start",)
    assert second.footprint_is_absolute is True
    assert second.mapped is False
    assert first is not second and second is not original
    assert second.bands is not original.bands
    assert all(a is b for (_name, a), (_other, b)
               in zip(second.bands, original.bands))


@pytest.mark.parametrize("change", [
    {"mapped": True},
    {"inherit_props": 1},
    {"copied_props": ["mutable"]},
    {"props": {"typed": Image([], {})}},
    {"source": Source("local", ("scene",), ["mutable"])},
    {"bands": [("red", Pixel("unsafe", ([1],)))] * 3},
    {"bands": [("red", Pixel("constant", (1,)))] * 3},
])
def test_unsupported_or_mutable_values_keep_the_uncached_path(change):
    assert snapshot_scalar_image(
        Translator([], {}, {}), replace(image(), **change),
    ) is None


def test_cycles_and_nonfinite_metadata_are_not_snapshotted():
    original = image()
    cycle = []
    cycle.append(cycle)
    original.props = {"cycle": cycle}
    assert snapshot_scalar_image(Translator([], {}, {}), original) is None
    original.props = {"value": float("inf")}
    assert snapshot_scalar_image(Translator([], {}, {}), original) is None
    original.props = {}
    pixel = object.__new__(Pixel)
    object.__setattr__(pixel, "op", "to_double")
    object.__setattr__(pixel, "args", (pixel,))
    object.__setattr__(pixel, "boolean", False)
    original.bands[0] = ("red", pixel)
    assert snapshot_scalar_image(Translator([], {}, {}), original) is None


@pytest.mark.parametrize("operation", ["store", "restore"])
def test_both_metadata_copies_require_budget_before_allocation(monkeypatch, operation):
    original = image()
    snapshot = snapshot_scalar_image(Translator([], {}, {}), original)
    translator = Translator([], {}, {})
    translator.steps = 49_999

    def unexpected(*_args, **_kwargs):
        raise AssertionError("metadata copied before work admission")

    monkeypatch.setattr(
        "gee.compat.earthengine.scalar_image_snapshot.copy.deepcopy", unexpected,
    )
    with pytest.raises(UnsupportedEEError, match="work budget"):
        if operation == "store":
            snapshot_scalar_image(translator, original)
        else:
            restore_scalar_image(translator, snapshot)
    assert translator.steps == 49_999


def test_non_snapshot_values_pass_through_without_charging():
    translator, original = Translator([], {}, {}), image()
    assert restore_scalar_image(translator, original) is original
    assert translator.steps == 0
