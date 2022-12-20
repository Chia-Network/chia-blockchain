import secrets

from hsms.bls12_381 import BLSSecretExponent


def main():
    secret_exponent = BLSSecretExponent.from_int(secrets.randbits(256))
    b = secret_exponent.as_bech32m()
    assert BLSSecretExponent.from_bech32m(b) == secret_exponent
    print(b)


if __name__ == "__main__":
    main()
