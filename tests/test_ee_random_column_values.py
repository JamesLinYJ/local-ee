"""Independent typed-wire reference and random-column invariants."""
import copy
import hashlib
import math
import statistics
import struct

import pytest

from gee.random_column_spec import decode_random_column_spec,prepare_random_column_spec
from gee.random_column_values import apply_random_column,random_value


def options(**kwargs):
    return decode_random_column_spec(prepare_random_column_spec(**kwargs))


def reference(values, seed=0, normal=False):
    # Independent frame construction; no production serializer or RNG helper.
    frames=[]
    for value in values:
        if isinstance(value,str): tag,data=b"s",value.encode()
        elif isinstance(value,bool): tag,data=b"b",b"\x01" if value else b"\x00"
        else: tag,data=b"n",struct.pack("!d",float(value) if value else 0.0)
        frames.append(tag+struct.pack("!I",len(data))+data)
    raw=(b"local-ee/randomColumn/sha256-rowkeys-v1\x00"+struct.pack("!qI",seed,len(values))
         +b"".join(frames))
    digest=hashlib.sha256(raw).digest()
    a,b=struct.unpack("!QQ",digest[:16])
    if not normal: return (a//2048)/9007199254740992
    u=(a//4096+0.5)/4503599627370496
    v=(b//2048)/9007199254740992
    return math.sqrt(-2*math.log(u))*math.cos(2*math.pi*v)


@pytest.mark.parametrize("seed",[-(2**63),-1,0,42,2**63-1])
@pytest.mark.parametrize("distribution",["uniform","normal"])
def test_typed_values_match_independent_wire_and_transform(seed,distribution):
    values=["猫😀",True,False,1.0000000000000002,-3.25,0,""]
    feature={"properties":{f"k{i}":v for i,v in enumerate(values)}}
    spec=options(seed=seed,distribution=distribution,row_keys=list(feature["properties"]))
    actual=random_value(feature,spec)
    assert actual == reference(values,seed,distribution=="normal")
    assert math.isfinite(actual)
    if distribution=="uniform": assert 0 <= actual < 1


def test_identity_typed_distinctions_numeric_equivalence_and_property_precedence():
    spec=options(row_keys=["k"])
    value=lambda x:random_value({"properties":{"k":x}},spec)
    assert value(1)==value(1.0)
    assert value(-0.0)==value(0)==value(0.0)
    assert len({value(True),value(1),value("1")})==3
    assert value("é") != value("e\u0301")
    default=options()
    assert random_value({"id":"a","properties":{}},default)==reference(["a"])
    assert random_value({"id":"ignored","properties":{"system:index":"chosen"}},default)==reference(["chosen"])
    assert random_value({"properties":{}},options(row_keys=[]))==reference([])
    assert random_value({"properties":{"other":2}},options(row_keys=["other"]))==value(2)


@pytest.mark.parametrize("bad",[None,[],{},float("nan"),float("inf"),2**53+1,float(2**54),"x"*4097,"\ud800"])
def test_missing_null_complex_nonfinite_and_oversize_key_values_fail(bad):
    with pytest.raises(ValueError):
        random_value({"properties":{"k":bad}},options(row_keys=["k"]))
    with pytest.raises(ValueError,match="missing"):
        random_value({"properties":{}},options())


def test_reorder_filter_duplicate_keys_and_overwrite_do_not_mutate_input():
    features=[{"type":"Feature","id":str(i),"geometry":None,"properties":{"k":i%3,"random":99}}
              for i in range(12)]
    before=copy.deepcopy(features)
    spec=options(row_keys=["k"],seed=17)
    actual=apply_random_column(features,spec)
    reordered=apply_random_column(list(reversed(features)),spec)
    assert features==before
    assert reordered==list(reversed(actual))
    assert actual[0]["properties"]["random"]==actual[3]["properties"]["random"]
    assert len({f["properties"]["random"] for f in actual})==3
    left=[f for f in actual if f["properties"]["random"] < .7]
    right=[f for f in actual if f["properties"]["random"] >= .7]
    assert {f['id'] for f in left}.isdisjoint({f['id'] for f in right})
    assert len(left)+len(right)==len(features)
    assert apply_random_column(features[::2],spec)==actual[::2]


def test_budget_failure_precedes_value_scan_or_copy_allocation():
    used=0
    def charge(work):
        nonlocal used
        used+=work
        if used>100: raise ValueError("test work cap")
    features=[{"properties":{"k":"x"*4096}}]
    before=copy.deepcopy(features)
    with pytest.raises(ValueError,match="work cap"):
        apply_random_column(features,options(row_keys=["k"]),charge)
    assert features==before


def test_option_reservation_precedes_canonical_encoding(monkeypatch):
    from gee import random_column_values

    entered = []
    spec = options()
    monkeypatch.setattr(random_column_values, "validate_random_column_spec", lambda value: entered.append(value))
    def deny(_):
        raise ValueError("reservation failed")
    with pytest.raises(ValueError, match="reservation failed"):
        random_column_values.random_value({"id": "a", "properties": {}}, spec, deny)
    assert entered == []


def test_deterministic_normal_distribution_moments_and_negative_values():
    spec=options(distribution="normal")
    values=[random_value({"id":str(i),"properties":{}},spec) for i in range(4096)]
    assert abs(statistics.mean(values)) < .06
    assert .9 < statistics.pvariance(values) < 1.1
    assert min(values)<-3 and max(values)>3
