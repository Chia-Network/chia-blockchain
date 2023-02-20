from __future__ import annotations

from typing import Any, Dict

import pytest

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.network import is_trusted_peer


@pytest.mark.parametrize(
    "host,node_id,trusted_peers,testing,result",
    [
        ("::1", 0, {}, False, True),
        ("::1", bytes32(b"d" * 32), {bytes32(b"a" * 32).hex(): "0"}, False, True),
        ("127.0.0.1", 0, {}, False, True),
        ("localhost", 0, {}, False, True),
        ("0:0:0:0:0:0:0:1", 0, {}, False, True),
        ("2000:1000::1234:abcd", 0, {}, True, True),  # testing=True
        ("10.11.12.13", bytes32(b"d" * 32), {bytes32(b"a" * 32).hex(): "0"}, False, False),
        ("10.11.12.13", bytes32(b"d" * 32), {bytes32(b"d" * 32).hex(): "0"}, False, True),
        ("10.11.12.13", bytes32(b"d" * 32), {}, False, False),
    ],
)
def test_is_trusted_peer(
    host: str, node_id: bytes32, trusted_peers: Dict[str, Any], testing: bool, result: bool
) -> None:
    assert is_trusted_peer(host=host, node_id=node_id, trusted_peers=trusted_peers, testing=testing) == result
