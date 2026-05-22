from wasted_sun.data.cube_scope import D_REDISPATCH, wasted_sun_filters


def test_wasted_sun_filters_single_code():
    assert wasted_sun_filters(("A",), ()) == [
        {"member": D_REDISPATCH, "operator": "equals", "values": ["A"]}
    ]
