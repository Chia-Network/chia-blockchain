from __future__ import annotations


def test_miniupnpc_imports_successfully() -> None:
    import miniupnpc

    # use it to avoid all related warnings
    assert miniupnpc is not None
