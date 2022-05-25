import itertools
from typing import Dict, List, Tuple

from tests.util.ssl_certs_1 import SSL_TEST_NODE_CERTS_AND_KEYS_1, SSL_TEST_PRIVATE_CA_CERT_AND_KEY_1
from tests.util.ssl_certs_2 import SSL_TEST_NODE_CERTS_AND_KEYS_2, SSL_TEST_PRIVATE_CA_CERT_AND_KEY_2
from tests.util.ssl_certs_3 import SSL_TEST_NODE_CERTS_AND_KEYS_3, SSL_TEST_PRIVATE_CA_CERT_AND_KEY_3
from tests.util.ssl_certs_4 import SSL_TEST_NODE_CERTS_AND_KEYS_4, SSL_TEST_PRIVATE_CA_CERT_AND_KEY_4
from tests.util.ssl_certs_5 import SSL_TEST_NODE_CERTS_AND_KEYS_5, SSL_TEST_PRIVATE_CA_CERT_AND_KEY_5
from tests.util.ssl_certs_6 import SSL_TEST_NODE_CERTS_AND_KEYS_6, SSL_TEST_PRIVATE_CA_CERT_AND_KEY_6
from tests.util.ssl_certs_7 import SSL_TEST_NODE_CERTS_AND_KEYS_7, SSL_TEST_PRIVATE_CA_CERT_AND_KEY_7

# ---------------------------------------------------------------------------
# Private CA certs/keys
# ---------------------------------------------------------------------------

SSL_TEST_PRIVATE_CA_CERTS_AND_KEYS: List[Tuple[bytes, bytes]] = [
    SSL_TEST_PRIVATE_CA_CERT_AND_KEY_1,
    SSL_TEST_PRIVATE_CA_CERT_AND_KEY_2,
    SSL_TEST_PRIVATE_CA_CERT_AND_KEY_3,
    SSL_TEST_PRIVATE_CA_CERT_AND_KEY_4,
    SSL_TEST_PRIVATE_CA_CERT_AND_KEY_5,
    SSL_TEST_PRIVATE_CA_CERT_AND_KEY_6,
    SSL_TEST_PRIVATE_CA_CERT_AND_KEY_7,
]

# ---------------------------------------------------------------------------
# Node -> cert/key mappings
# ---------------------------------------------------------------------------

SSL_TEST_NODE_CERTS_AND_KEYS: List[Dict[str, Dict[str, Dict[str, bytes]]]] = [
    SSL_TEST_NODE_CERTS_AND_KEYS_1,
    SSL_TEST_NODE_CERTS_AND_KEYS_2,
    SSL_TEST_NODE_CERTS_AND_KEYS_3,
    SSL_TEST_NODE_CERTS_AND_KEYS_4,
    SSL_TEST_NODE_CERTS_AND_KEYS_5,
    SSL_TEST_NODE_CERTS_AND_KEYS_6,
    SSL_TEST_NODE_CERTS_AND_KEYS_7,
]


ssl_test_private_ca_certs_and_keys_gen = (
    SSL_TEST_PRIVATE_CA_CERTS_AND_KEYS[idx]
    for idx in itertools.cycle([*range(len(SSL_TEST_PRIVATE_CA_CERTS_AND_KEYS))])
)


def get_next_private_ca_cert_and_key() -> Tuple[bytes, bytes]:
    return next(ssl_test_private_ca_certs_and_keys_gen)  # type: ignore[no-any-return]


ssl_test_certs_and_keys_gen = (
    SSL_TEST_NODE_CERTS_AND_KEYS[idx] for idx in itertools.cycle([*range(len(SSL_TEST_NODE_CERTS_AND_KEYS))])
)


def get_next_nodes_certs_and_keys() -> Dict[str, Dict[str, Dict[str, bytes]]]:
    return next(ssl_test_certs_and_keys_gen)
