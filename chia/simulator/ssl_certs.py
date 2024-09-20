from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Dict, Generic, List, Tuple, TypeVar

from chia.simulator.ssl_certs_1 import SSL_TEST_NODE_CERTS_AND_KEYS_1, SSL_TEST_PRIVATE_CA_CERT_AND_KEY_1
from chia.simulator.ssl_certs_2 import SSL_TEST_NODE_CERTS_AND_KEYS_2, SSL_TEST_PRIVATE_CA_CERT_AND_KEY_2
from chia.simulator.ssl_certs_3 import SSL_TEST_NODE_CERTS_AND_KEYS_3, SSL_TEST_PRIVATE_CA_CERT_AND_KEY_3
from chia.simulator.ssl_certs_4 import SSL_TEST_NODE_CERTS_AND_KEYS_4, SSL_TEST_PRIVATE_CA_CERT_AND_KEY_4
from chia.simulator.ssl_certs_5 import SSL_TEST_NODE_CERTS_AND_KEYS_5, SSL_TEST_PRIVATE_CA_CERT_AND_KEY_5
from chia.simulator.ssl_certs_6 import SSL_TEST_NODE_CERTS_AND_KEYS_6, SSL_TEST_PRIVATE_CA_CERT_AND_KEY_6
from chia.simulator.ssl_certs_7 import SSL_TEST_NODE_CERTS_AND_KEYS_7, SSL_TEST_PRIVATE_CA_CERT_AND_KEY_7
from chia.simulator.ssl_certs_8 import SSL_TEST_NODE_CERTS_AND_KEYS_8, SSL_TEST_PRIVATE_CA_CERT_AND_KEY_8
from chia.simulator.ssl_certs_9 import SSL_TEST_NODE_CERTS_AND_KEYS_9, SSL_TEST_PRIVATE_CA_CERT_AND_KEY_9
from chia.simulator.ssl_certs_10 import SSL_TEST_NODE_CERTS_AND_KEYS_10, SSL_TEST_PRIVATE_CA_CERT_AND_KEY_10

# ---------------------------------------------------------------------------
# NOTE:
# Use tests/util/gen_ssl_certs.py to generate additional SSL certs and keys
#
# EXAMPLE:
# $ python3 tests/util/gen_ssl_certs.py --suffix 123 > ssl_certs_123.py
# ---------------------------------------------------------------------------

_T_SSLTestCollateral = TypeVar("_T_SSLTestCollateral", bound="SSLTestCollateralTracker")


@dataclass
class SSLTestCollateralTracker:
    in_use: bool = field(default=False, init=False)

    def mark_in_use(self) -> None:
        self.in_use = True

    def mark_not_in_use(self) -> None:
        self.in_use = False


@dataclass
class SSLTestCACertAndPrivateKey(SSLTestCollateralTracker):
    cert_and_key: Tuple[bytes, bytes]


@dataclass
class SSLTestNodeCertsAndKeys(SSLTestCollateralTracker):
    certs_and_keys: Dict[str, Dict[str, Dict[str, bytes]]]


@dataclass
class SSLTestCollateralWrapper(Generic[_T_SSLTestCollateral]):
    collateral: _T_SSLTestCollateral

    def __post_init__(self) -> None:
        if self.collateral.in_use:
            print("  WARNING: Reusing SSL Test collateral that is currently in use")
        self.collateral.mark_in_use()

    def __del__(self) -> None:
        self.collateral.mark_not_in_use()


# ---------------------------------------------------------------------------
# Private CA certs/keys
# ---------------------------------------------------------------------------

SSL_TEST_PRIVATE_CA_CERTS_AND_KEYS: List[SSLTestCACertAndPrivateKey] = [
    SSLTestCACertAndPrivateKey(SSL_TEST_PRIVATE_CA_CERT_AND_KEY_1),
    SSLTestCACertAndPrivateKey(SSL_TEST_PRIVATE_CA_CERT_AND_KEY_2),
    SSLTestCACertAndPrivateKey(SSL_TEST_PRIVATE_CA_CERT_AND_KEY_3),
    SSLTestCACertAndPrivateKey(SSL_TEST_PRIVATE_CA_CERT_AND_KEY_4),
    SSLTestCACertAndPrivateKey(SSL_TEST_PRIVATE_CA_CERT_AND_KEY_5),
    SSLTestCACertAndPrivateKey(SSL_TEST_PRIVATE_CA_CERT_AND_KEY_6),
    SSLTestCACertAndPrivateKey(SSL_TEST_PRIVATE_CA_CERT_AND_KEY_7),
    SSLTestCACertAndPrivateKey(SSL_TEST_PRIVATE_CA_CERT_AND_KEY_8),
    SSLTestCACertAndPrivateKey(SSL_TEST_PRIVATE_CA_CERT_AND_KEY_9),
    SSLTestCACertAndPrivateKey(SSL_TEST_PRIVATE_CA_CERT_AND_KEY_10),
]

# ---------------------------------------------------------------------------
# Node -> cert/key mappings
# ---------------------------------------------------------------------------

SSL_TEST_NODE_CERTS_AND_KEYS: List[SSLTestNodeCertsAndKeys] = [
    SSLTestNodeCertsAndKeys(SSL_TEST_NODE_CERTS_AND_KEYS_1),
    SSLTestNodeCertsAndKeys(SSL_TEST_NODE_CERTS_AND_KEYS_2),
    SSLTestNodeCertsAndKeys(SSL_TEST_NODE_CERTS_AND_KEYS_3),
    SSLTestNodeCertsAndKeys(SSL_TEST_NODE_CERTS_AND_KEYS_4),
    SSLTestNodeCertsAndKeys(SSL_TEST_NODE_CERTS_AND_KEYS_5),
    SSLTestNodeCertsAndKeys(SSL_TEST_NODE_CERTS_AND_KEYS_6),
    SSLTestNodeCertsAndKeys(SSL_TEST_NODE_CERTS_AND_KEYS_7),
    SSLTestNodeCertsAndKeys(SSL_TEST_NODE_CERTS_AND_KEYS_8),
    SSLTestNodeCertsAndKeys(SSL_TEST_NODE_CERTS_AND_KEYS_9),
    SSLTestNodeCertsAndKeys(SSL_TEST_NODE_CERTS_AND_KEYS_10),
]


ssl_test_private_ca_certs_and_keys_gen = (
    SSL_TEST_PRIVATE_CA_CERTS_AND_KEYS[idx]
    for idx in itertools.cycle([*range(len(SSL_TEST_PRIVATE_CA_CERTS_AND_KEYS))])
)


def get_next_private_ca_cert_and_key() -> SSLTestCollateralWrapper[SSLTestCACertAndPrivateKey]:
    return SSLTestCollateralWrapper(next(ssl_test_private_ca_certs_and_keys_gen))


ssl_test_certs_and_keys_gen = (
    SSL_TEST_NODE_CERTS_AND_KEYS[idx] for idx in itertools.cycle([*range(len(SSL_TEST_NODE_CERTS_AND_KEYS))])
)


def get_next_nodes_certs_and_keys() -> SSLTestCollateralWrapper[SSLTestNodeCertsAndKeys]:
    return SSLTestCollateralWrapper(next(ssl_test_certs_and_keys_gen))
