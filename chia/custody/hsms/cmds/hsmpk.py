import sys

from chia.custody.hsms.bls12_381 import BLSSecretExponent


async def hsmpk_cmd(filename: str) -> str:
    secret_exponent = BLSSecretExponent.from_bech32m(filename)
    b = secret_exponent.public_key().as_bech32m()
    print(b)
    return b
