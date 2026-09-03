from black_ice_common.decision import is_match


def test_is_match():
    assert is_match(0.6, 0.45) is True
    assert is_match(0.44, 0.45) is False
    assert is_match(0.45, 0.45) is True
