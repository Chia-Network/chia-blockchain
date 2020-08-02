from blspy import PrivateKey
from src.util.ints import uint32

# EIP 2334 bls key derivation
# https://eips.ethereum.org/EIPS/eip-2334
# 12381 = bls spec number
# 8444 = Chia blockchain number and port number
# 0, 1, 2, 3, 4, farmer, pool, wallet, local, backup key numbers


def master_sk_to_farmer_sk(master: PrivateKey) -> PrivateKey:
    return master.derive_child(12381).derive_child(8444).derive_child(0).derive_child(0)


def master_sk_to_pool_sk(master: PrivateKey) -> PrivateKey:
    return master.derive_child(12381).derive_child(8444).derive_child(1).derive_child(0)


def master_sk_to_wallet_sk(master: PrivateKey, index: uint32) -> PrivateKey:
    return (
        master.derive_child(12381)
        .derive_child(8444)
        .derive_child(2)
        .derive_child(index)
    )


def master_sk_to_local_sk(master: PrivateKey) -> PrivateKey:
    return master.derive_child(12381).derive_child(8444).derive_child(3).derive_child(0)


def master_sk_to_backup_sk(master: PrivateKey) -> PrivateKey:
    return master.derive_child(12381).derive_child(8444).derive_child(4).derive_child(0)
