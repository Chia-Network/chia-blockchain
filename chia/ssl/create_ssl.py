from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pkg_resources
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.x509.oid import NameOID

from chia.util.ssl_check import DEFAULT_PERMISSIONS_CERT_FILE, DEFAULT_PERMISSIONS_KEY_FILE

_all_private_node_names: List[str] = [
    "full_node",
    "wallet",
    "farmer",
    "harvester",
    "timelord",
    "crawler",
    "data_layer",
    "daemon",
]
_all_public_node_names: List[str] = ["full_node", "wallet", "farmer", "introducer", "timelord", "data_layer"]


def get_chia_ca_crt_key() -> Tuple[Any, Any]:
    crt = pkg_resources.resource_string(__name__, "chia_ca.crt")
    key = pkg_resources.resource_string(__name__, "chia_ca.key")
    return crt, key


def get_mozilla_ca_crt() -> str:
    mozilla_path = Path(__file__).parent.parent.parent.absolute() / "mozilla-ca/cacert.pem"
    return str(mozilla_path)


def write_ssl_cert_and_key(cert_path: Path, cert_data: bytes, key_path: Path, key_data: bytes, overwrite: bool = True):
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY

    for path, data, mode in [
        (cert_path, cert_data, DEFAULT_PERMISSIONS_CERT_FILE),
        (key_path, key_data, DEFAULT_PERMISSIONS_KEY_FILE),
    ]:
        if path.exists():
            if not overwrite:
                continue

            path.unlink()

        with open(os.open(str(path), flags, mode), "wb") as f:
            f.write(data)  # lgtm [py/clear-text-storage-sensitive-data]


def ensure_ssl_dirs(dirs: List[Path]):
    """Create SSL dirs with a default 755 mode if necessary"""
    for dir in dirs:
        if not dir.exists():
            dir.mkdir(mode=0o755)


def generate_ca_signed_cert(ca_crt: bytes, ca_key: bytes, cert_out: Path, key_out: Path):
    one_day = datetime.timedelta(1, 0, 0)
    root_cert = x509.load_pem_x509_certificate(ca_crt, default_backend())
    root_key = load_pem_private_key(ca_key, None, default_backend())

    cert_key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    new_subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "Chia"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Chia"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Organic Farming Division"),
        ]
    )

    cert = (
        x509.CertificateBuilder()
        .subject_name(new_subject)
        .issuer_name(root_cert.issuer)
        .public_key(cert_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.today() - one_day)
        .not_valid_after(datetime.datetime(2100, 8, 2))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("chia.net")]),
            critical=False,
        )
        .sign(root_key, hashes.SHA256(), default_backend())
    )

    cert_pem = cert.public_bytes(encoding=serialization.Encoding.PEM)
    key_pem = cert_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )

    write_ssl_cert_and_key(cert_out, cert_pem, key_out, key_pem)


def make_ca_cert(cert_path: Path, key_path: Path):
    root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Chia"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Chia CA"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Organic Farming Division"),
        ]
    )
    root_cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(root_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(root_key, hashes.SHA256(), default_backend())
    )

    cert_pem = root_cert.public_bytes(encoding=serialization.Encoding.PEM)
    key_pem = root_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )

    write_ssl_cert_and_key(cert_path, cert_pem, key_path, key_pem)


def create_all_ssl(
    root_path: Path,
    *,
    private_ca_crt_and_key: Optional[Tuple[bytes, bytes]] = None,
    node_certs_and_keys: Optional[Dict[str, Dict]] = None,
    private_node_names: List[str] = _all_private_node_names,
    public_node_names: List[str] = _all_public_node_names,
    overwrite: bool = True,
):
    # remove old key and crt
    config_dir = root_path / "config"
    old_key_path = config_dir / "trusted.key"
    old_crt_path = config_dir / "trusted.crt"
    if old_key_path.exists():
        print(f"Old key not needed anymore, deleting {old_key_path}")
        os.remove(old_key_path)
    if old_crt_path.exists():
        print(f"Old crt not needed anymore, deleting {old_crt_path}")
        os.remove(old_crt_path)

    ssl_dir = config_dir / "ssl"
    ca_dir = ssl_dir / "ca"
    ensure_ssl_dirs([ssl_dir, ca_dir])

    private_ca_key_path = ca_dir / "private_ca.key"
    private_ca_crt_path = ca_dir / "private_ca.crt"
    chia_ca_crt, chia_ca_key = get_chia_ca_crt_key()
    chia_ca_crt_path = ca_dir / "chia_ca.crt"
    chia_ca_key_path = ca_dir / "chia_ca.key"
    write_ssl_cert_and_key(chia_ca_crt_path, chia_ca_crt, chia_ca_key_path, chia_ca_key, overwrite=overwrite)

    # If Private CA crt/key are passed-in, write them out
    if private_ca_crt_and_key is not None:
        private_ca_crt, private_ca_key = private_ca_crt_and_key
        write_ssl_cert_and_key(private_ca_crt_path, private_ca_crt, private_ca_key_path, private_ca_key)

    if not private_ca_key_path.exists() or not private_ca_crt_path.exists():
        # Create private CA
        print(f"Can't find private CA, creating a new one in {root_path} to generate TLS certificates")
        make_ca_cert(private_ca_crt_path, private_ca_key_path)
        # Create private certs for each node
        ca_key = private_ca_key_path.read_bytes()
        ca_crt = private_ca_crt_path.read_bytes()
        generate_ssl_for_nodes(
            ssl_dir,
            ca_crt,
            ca_key,
            prefix="private",
            nodes=private_node_names,
            node_certs_and_keys=node_certs_and_keys,
            overwrite=overwrite,
        )
    else:
        # This is entered when user copied over private CA
        print(f"Found private CA in {root_path}, using it to generate TLS certificates")
        ca_key = private_ca_key_path.read_bytes()
        ca_crt = private_ca_crt_path.read_bytes()
        generate_ssl_for_nodes(
            ssl_dir,
            ca_crt,
            ca_key,
            prefix="private",
            nodes=private_node_names,
            node_certs_and_keys=node_certs_and_keys,
            overwrite=overwrite,
        )

    chia_ca_crt, chia_ca_key = get_chia_ca_crt_key()
    generate_ssl_for_nodes(
        ssl_dir,
        chia_ca_crt,
        chia_ca_key,
        prefix="public",
        nodes=public_node_names,
        overwrite=False,
        node_certs_and_keys=node_certs_and_keys,
    )


def generate_ssl_for_nodes(
    ssl_dir: Path,
    ca_crt: bytes,
    ca_key: bytes,
    *,
    prefix: str,
    nodes: List[str],
    overwrite: bool = True,
    node_certs_and_keys: Optional[Dict[str, Dict]] = None,
):
    for node_name in nodes:
        node_dir = ssl_dir / node_name
        ensure_ssl_dirs([node_dir])
        key_path = node_dir / f"{prefix}_{node_name}.key"
        crt_path = node_dir / f"{prefix}_{node_name}.crt"
        if node_certs_and_keys is not None:
            certs_and_keys = node_certs_and_keys.get(node_name, {}).get(prefix, {})
            crt = certs_and_keys.get("crt", None)
            key = certs_and_keys.get("key", None)
            if crt is not None and key is not None:
                write_ssl_cert_and_key(crt_path, crt, key_path, key)
                continue

        if key_path.exists() and crt_path.exists() and overwrite is False:
            continue
        generate_ca_signed_cert(ca_crt, ca_key, crt_path, key_path)


def main():
    return make_ca_cert(Path("./chia_ca.crt"), Path("./chia_ca.key"))


if __name__ == "__main__":
    main()
