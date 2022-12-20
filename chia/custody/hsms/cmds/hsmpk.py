import sys

from hsms.bls12_381 import BLSSecretExponent


def main():
    for arg in sys.argv[1:]:
        secret_exponent = BLSSecretExponent.from_bech32m(arg)
        print(secret_exponent.public_key().as_bech32m())


if __name__ == "__main__":
    main()
