import secrets

from chia.custody.hsms.bls12_381 import BLSSecretExponent


async def hsmgen_cmd() -> str:
    secret_exponent = BLSSecretExponent.from_int(secrets.randbits(256))
    b = secret_exponent.as_bech32m()
    assert BLSSecretExponent.from_bech32m(b) == secret_exponent
    print(b)
    return b
