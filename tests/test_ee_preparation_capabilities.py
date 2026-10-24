"""The source-only inventory describes exactly the implemented preparation family."""
from pathlib import Path

from gee.compat.earthengine.capabilities import SUPPORTED_FUNCTIONS
from gee.compat.earthengine.element_metadata_values import ELEMENT_METADATA_VALUE_METHODS
from gee.compat.earthengine.feature_structure import FEATURE_STRUCTURE_METHODS
from gee.compat.earthengine.feature_values import FEATURE_GEOMETRY_ARGUMENTS
from gee.compat.earthengine.filtering import FILTER_PREPARATION_ARGUMENTS
from gee.compat.earthengine.geometry_structure import GEOMETRY_STRUCTURE_FUNCTIONS
from scripts.ee_inventory.declarations import read_declared_handlers
from scripts.ee_inventory.feature_preparation import FEATURE_PREPARATION_LIMITS


def test_preparation_catalogue_matches_real_families_and_source_only_inventory():
    constructors = {
        "GeometryConstructors.BBox", "GeometryConstructors.MultiGeometry",
        "GeometryConstructors.LinearRing",
    }
    implemented = (
        ELEMENT_METADATA_VALUE_METHODS | FEATURE_STRUCTURE_METHODS
        | FILTER_PREPARATION_ARGUMENTS.keys() | GEOMETRY_STRUCTURE_FUNCTIONS
        | constructors | FEATURE_GEOMETRY_ARGUMENTS.keys()
    )
    assert set(FEATURE_PREPARATION_LIMITS) == implemented
    assert implemented <= SUPPORTED_FUNCTIONS
    root = Path(__file__).resolve().parents[1]
    assert implemented <= read_declared_handlers(root / "gee/ee_translate.py")
    assert "Filter.hasType" not in SUPPORTED_FUNCTIONS
    assert "Geometry.projection" not in SUPPORTED_FUNCTIONS
    assert all(FEATURE_PREPARATION_LIMITS.values())
