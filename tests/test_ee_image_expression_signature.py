"""The second-order descriptor keeps declared Image arguments and work bounds."""
from __future__ import annotations

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.image_expression import descriptor, invoke
from gee.compat.earthengine.ir import Image, UnsupportedEEError, const
from gee.ee_expression import parse_expression


@pytest.mark.parametrize("arguments", [
    {}, {"expression": "x", "argName": "x", "vars": []},
    {"expression": "x", "argName": "x", "vars": ["x", "x"]},
    {"expression": "x", "argName": "x", "vars": ["y"]},
    {"expression": "x", "argName": "x", "vars": ["x", 1]},
    {"expression": 1, "argName": "x", "vars": ["x"]},
])
def test_invalid_expression_signature_rejects_before_parse(arguments):
    with pytest.raises(UnsupportedEEError):
        descriptor(Translator([], {}, {}), arguments)


def test_descriptor_owns_variable_names_and_rejects_missing_extra_or_bad_images():
    translator = Translator([], {}, {})
    names = ["default", "x"]
    function = descriptor(translator, {"expression": "x", "argName": "default", "vars": names})
    names.append("poison")
    assert function.variables == ("default", "x")
    image = Image([("one", const(1))], {})
    for values in ({"default": image}, {"default": image, "x": image, "other": image},
                   {"default": image, "x": {"bad": 1}}):
        with pytest.raises(UnsupportedEEError):
            invoke(translator, function, values)


def test_formula_scans_are_charged_before_allocating_tokens():
    translator = Translator([], {}, {})
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="compilation work budget"):
        parse_expression("1 + 2", {}, "default", translator)
    assert translator.steps == 49_999
