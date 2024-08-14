import pytest

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.program import Program
from chia.types.condition_opcodes import ConditionOpcode
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.util.byte_types import hexstr_to_bytes

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature


P2_DELEGATED_SECP_MOD: Program = load_clvm("p2_delegated_or_hidden_secp_k1.clsp")


def test_secp_k1_signing() -> None:
    genesis = bytes32(b'1'*32)
    hph = bytes32(b'2'*32)
    delegated_puz = Program.to(1)
    delegated_sol = Program.to(1)
    coin_id = bytes32(b'3'*32)
    message = delegated_puz.get_tree_hash() + coin_id + genesis + hph

    secret_exponent = 0x1a62c9636d1c9db2e7d564d0c11603bf456aad25aa7b12bdfd762b4e38e7edc6

    private_key = ec.derive_private_key(secret_exponent, ec.SECP256K1(), default_backend())
    public_key = private_key.public_key()
    pk = public_key.public_bytes(Encoding.X962, PublicFormat.CompressedPoint)

    der_sig = private_key.sign(message, ec.ECDSA(hashes.SHA256(), deterministic_signing=True))
    r, s = decode_dss_signature(der_sig)
    sig = r.to_bytes(32, byteorder='big') + s.to_bytes(32, byteorder='big')
    puz = P2_DELEGATED_SECP_MOD.curry(genesis, pk, hph)
    sol = Program.to([delegated_puz, delegated_sol, sig, coin_id])

    # Run the puzzle with a valid signature
    conds = puz.run(sol)
    assert conds == Program.to(([ConditionOpcode.ASSERT_MY_COIN_ID.value, coin_id], 1))

    # Modify the signature and assert it fails to verify
    modified_sig = bytearray(sig)
    modified_sig[0] ^= (modified_sig[0] + 1) % 256
    bad_signature = bytes(modified_sig)

    bad_solution = Program.to(
        [delegated_puz, delegated_sol, bad_signature, coin_id]
    )
    with pytest.raises(ValueError, match="secp256k1_verify failed"):
        puz.run(bad_solution)


def test_secp_k1_from_tag() -> None:
    genesis = bytes32(b'1'*32)
    hph = bytes32(b'2'*32)
    delegated_puz = Program.to(1)
    delegated_sol = Program.to(1)
    coin_id = bytes32(b'3'*32)
    pk_hex = "0403af9ba662e884db72f8fe2f6b797b86da0e0e593188ebc144f428836b32339fc2a0641dfc68aed021ff2936fc6daf79cf82a84f73bf79babfeefb675f09489d"
    pk_card = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), hexstr_to_bytes(pk_hex))
    pk = pk_card.public_bytes(Encoding.X962, PublicFormat.CompressedPoint)

    sig_hex = "304402206e430b07d5b3f0e95815f8a098e3f819b078b398f52c0f19c7a41b61d9b3707002204c9c4c36926e987d07ca7a139f8bc91665212d533c9719a73264db173adf60b4"
    r, s = decode_dss_signature(hexstr_to_bytes(sig_hex))
    sig = r.to_bytes(32, byteorder='big') + s.to_bytes(32, byteorder='big')
    puz = P2_DELEGATED_SECP_MOD.curry(genesis, pk, hph)
    sol = Program.to([delegated_puz, delegated_sol, sig, coin_id])
    conds = puz.run(sol)
