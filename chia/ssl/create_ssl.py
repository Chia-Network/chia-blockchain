import datetime
from pathlib import Path
from typing import Any, Tuple

import pkg_resources
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.x509.oid import NameOID


def get_chia_ca_crt_key() -> Tuple[Any, Any]:
    crt = pkg_resources.resource_string(__name__, "chia_ca.crt")
    key = pkg_resources.resource_string(__name__, "chia_ca.key")
    return crt, key


def get_mozilla_ca_crt() -> str:
    mozilla_path = Path(__file__).parent.parent.parent.absolute() / "mozilla-ca/cacert.pem"
    return str(mozilla_path)


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

    cert_out.write_bytes(cert_pem)
    key_out.write_bytes(key_pem)


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

    cert_path.write_bytes(
        root_cert.public_bytes(
            encoding=serialization.Encoding.PEM,
        )
    )

    key_path.write_bytes(
        root_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def main():
    return make_ca_cert(Path("./chia_ca.crt"), Path("./chia_ca.key"))


if __name__ == "__main__":
    main()
