import sys
from dataclasses import dataclass


def test_slots_dataclass_preserves_slots_when_supported():
    from backend._compat import slots_dataclass

    @slots_dataclass
    class Example:
        value: int

    item = Example(3)

    assert item.value == 3
    assert hasattr(Example, "__slots__") is (sys.version_info >= (3, 10))


def test_slots_dataclass_falls_back_when_slots_keyword_is_unsupported():
    from backend._compat import build_slots_dataclass

    def legacy_dataclass(cls=None, **kwargs):
        if "slots" in kwargs:
            raise TypeError("dataclass() got an unexpected keyword argument 'slots'")
        return dataclass(cls, **kwargs)

    legacy_slots_dataclass = build_slots_dataclass(legacy_dataclass)

    @legacy_slots_dataclass
    class Example:
        value: int

    item = Example(5)

    assert item.value == 5
    assert not hasattr(Example, "__slots__")
