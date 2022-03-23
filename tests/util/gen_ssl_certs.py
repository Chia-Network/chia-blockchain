import click

from chia.ssl.create_ssl import generate_ca_signed_cert, make_ca_cert
from pathlib import Path
from pytest import MonkeyPatch
from typing import Optional


# NOTE: This is a standalone tool that can be used to generate a CA cert/key as well as node certs/keys.


@click.command()
@click.option(
    "--suffix",
    type=str,
    default="",
    help="Suffix to append to the generated cert/key symbols.",
    required=True,
)
def gen_ssl(suffix: str):
    captured_crt: Optional[bytes] = None
    captured_key: Optional[bytes] = None
    capture_cert_and_key = False

    def patched_write_ssl_cert_and_key(cert_path: Path, cert_data: bytes, key_path: Path, key_data: bytes):
        nonlocal capture_cert_and_key, captured_crt, captured_key

        if capture_cert_and_key:
            captured_crt = cert_data
            captured_key = key_data

        print(f"{cert_path} = b\"\"\"{cert_data.decode(encoding='utf8')}\"\"\"")
        print()
        print(f"{key_path} = b\"\"\"{key_data.decode(encoding='utf8')}\"\"\"")
        print()

    patch = MonkeyPatch()
    patch.setattr("chia.ssl.create_ssl.write_ssl_cert_and_key", patched_write_ssl_cert_and_key)

    ca_crt: Optional[bytes] = None
    ca_key: Optional[bytes] = None
    capture_cert_and_key = True

    print("from typing import Dict, List, Tuple")
    print()

    make_ca_cert(Path("SSL_TEST_PRIVATE_CA_CRT"), Path("SSL_TEST_PRIVATE_CA_KEY"))

    capture_cert_and_key = False
    ca_crt = captured_crt
    ca_key = captured_key

    node_certs_and_keys = {
        "full_node": {
            "private": {"crt": "SSL_TEST_FULLNODE_PRIVATE_CRT", "key": "SSL_TEST_FULLNODE_PRIVATE_KEY"},
            "public": {"crt": "SSL_TEST_FULLNODE_PUBLIC_CRT", "key": "SSL_TEST_FULLNODE_PUBLIC_KEY"},
        },
        "wallet": {
            "private": {"crt": "SSL_TEST_WALLET_PRIVATE_CRT", "key": "SSL_TEST_WALLET_PRIVATE_KEY"},
            "public": {"crt": "SSL_TEST_WALLET_PUBLIC_CRT", "key": "SSL_TEST_WALLET_PUBLIC_KEY"},
        },
        "farmer": {
            "private": {"crt": "SSL_TEST_FARMER_PRIVATE_CRT", "key": "SSL_TEST_FARMER_PRIVATE_KEY"},
            "public": {"crt": "SSL_TEST_FARMER_PUBLIC_CRT", "key": "SSL_TEST_FARMER_PUBLIC_KEY"},
        },
        "harvester": {"private": {"crt": "SSL_TEST_HARVESTER_PRIVATE_CRT", "key": "SSL_TEST_HARVESTER_PRIVATE_KEY"}},
        "timelord": {
            "private": {"crt": "SSL_TEST_TIMELORD_PRIVATE_CRT", "key": "SSL_TEST_TIMELORD_PRIVATE_KEY"},
            "public": {"crt": "SSL_TEST_TIMELORD_PUBLIC_CRT", "key": "SSL_TEST_TIMELORD_PUBLIC_KEY"},
        },
        "crawler": {"private": {"crt": "SSL_TEST_CRAWLER_PRIVATE_CRT", "key": "SSL_TEST_CRAWLER_PRIVATE_KEY"}},
        "daemon": {"private": {"crt": "SSL_TEST_DAEMON_PRIVATE_CRT", "key": "SSL_TEST_DAEMON_PRIVATE_KEY"}},
        "introducer": {
            "public": {"crt": "SSL_TEST_INTRODUCER_PUBLIC_CRT", "key": "SSL_TEST_INTRODUCER_PUBLIC_KEY"},
        },
    }

    for node_name, cert_type_dict in node_certs_and_keys.items():
        for _, cert_dict in cert_type_dict.items():
            crt = cert_dict["crt"]
            key = cert_dict["key"]
            generate_ca_signed_cert(ca_crt, ca_key, crt, key)

    patch.undo()

    append_str = "" if suffix == "" else f"_{suffix}"
    print(
        f"SSL_TEST_PRIVATE_CA_CERT_AND_KEY{append_str}: List[Tuple[bytes, bytes]] = "
        "(SSL_TEST_PRIVATE_CA_CRT, SSL_TEST_PRIVATE_CA_KEY)"
    )
    print()
    print(f"SSL_TEST_NODE_CERTS_AND_KEYS{append_str}: Dict[str, Dict[str, bytes]] = {{")
    for node_name, cert_type_dict in node_certs_and_keys.items():
        print(f'    "{node_name}": {{')
        for cert_type, cert_dict in cert_type_dict.items():
            crt = cert_dict["crt"]
            key = cert_dict["key"]
            print(f'       "{cert_type}": {{"crt": {crt}, "key": {key}}},')
        print("    },")
    print("}")
    print()


def main():
    gen_ssl()


if __name__ == "__main__":
    main()
