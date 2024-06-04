from __future__ import annotations

from typing import Any, Dict, List

import pytest

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.network import is_trusted_peer


@pytest.mark.parametrize(
    "host,node_id,trusted_peers,trusted_cidrs,testing,result",
    [
        # IPv6 localhost testing
        ("::1", bytes32(b"0" * 32), {}, [], False, True),
        # IPv6 localhost testing with mismatched node_id (still True)
        ("::1", bytes32(b"d" * 32), {bytes32(b"a" * 32).hex(): "0"}, [], False, True),
        # IPv6 localhost testing with testing flag True
        ("::1", bytes32(b"0" * 32), {}, [], True, False),
        ("::1", bytes32(b"d" * 32), {bytes32(b"a" * 32).hex(): "0"}, [], True, False),
        # IPv6 localhost long form
        ("0:0:0:0:0:0:0:1", bytes32(b"0" * 32), {}, [], False, True),
        ("0:0:0:0:0:0:0:1", bytes32(b"0" * 32), {}, [], True, False),
        # IPv4 localhost testing
        ("127.0.0.1", bytes32(b"0" * 32), {}, [], False, True),
        ("localhost", bytes32(b"0" * 32), {}, [], False, True),
        ("127.0.0.1", bytes32(b"0" * 32), {}, [], True, False),
        ("localhost", bytes32(b"0" * 32), {}, [], True, False),
        # localhost testing with testing True but with matching node_id
        ("127.0.0.1", bytes32(b"0" * 32), {bytes32(b"0" * 32).hex(): "0"}, [], True, True),
        # misc
        ("2000:1000::1234:abcd", bytes32(b"0" * 32), {}, [], True, False),
        ("10.11.12.13", bytes32(b"d" * 32), {bytes32(b"a" * 32).hex(): "0"}, [], False, False),
        ("10.11.12.13", bytes32(b"d" * 32), {bytes32(b"d" * 32).hex(): "0"}, [], False, True),
        ("10.11.12.13", bytes32(b"d" * 32), {}, [], False, False),
        # CIDR Allowlist
        ("2000:1000::1234:abcd", bytes32(b"0" * 32), {}, ["2000:1000::/64"], False, True),
        ("2000:1000::1234:abcd", bytes32(b"0" * 32), {}, [], False, False),
        ("10.11.12.13", bytes32(b"d" * 32), {bytes32(b"a" * 32).hex(): "0"}, ["10.0.0.0/8"], False, True),
        ("10.11.12.13", bytes32(b"d" * 32), {bytes32(b"a" * 32).hex(): "0"}, [], False, False),
    ],
)
def test_is_trusted_peer(
    host: str, node_id: bytes32, trusted_peers: Dict[str, Any], trusted_cidrs: List[str], testing: bool, result: bool
) -> None:
    assert (
        is_trusted_peer(
            host=host, node_id=node_id, trusted_peers=trusted_peers, testing=testing, trusted_cidrs=trusted_cidrs
        )
        == result
    )
