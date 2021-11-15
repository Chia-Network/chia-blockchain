from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint32, uint64
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.pool_target import PoolTarget
from blspy import G1Element, G2Element
from chia.protocols import (
    farmer_protocol,
    full_node_protocol,
    harvester_protocol,
    introducer_protocol,
    pool_protocol,
    timelord_protocol,
    wallet_protocol,
)

### FARMER PROTOCOL
new_signage_point = farmer_protocol.NewSignagePoint(
    bytes32([0] * 16 + [1] * 16),
    bytes32(b"a" * 16 + b"b" * 16),
    bytes32([0] * 32),
    uint64(123123),
    uint64(2 ** 16),
    uint8(15),
)

proof_of_space = ProofOfSpace(
    bytes32(bytes.fromhex("f0613f3b6b8258d6f62c6b13e53dd45d3eaf0abe74430f9a00de442310b8e499")),
    G1Element.from_bytes(
        bytes.fromhex(
            "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
        ),
    ),
    None,
    G1Element.from_bytes(
        bytes.fromhex(
            "b6449c2c68df97c19e884427e42ee7350982d4020571ead08732615ff39bd216bfd630b6460784982bec98b49fea79d0"
        ),
    ),
    uint8(22),
    bytes.fromhex(
        "a67188ae0c02c49b0e821a9773033a3fbd338030c383080dbb8b1d63f07af427d8075e59d911f85ea562fd967823588f9a405a4464fdf5dc0866ee15bebd6b94cb147e28aa9cf96da930611486b779737ed721ea376b9939ba05357141223d75d21b21f310ec32d85ed3b98cf301494ea91b8501138481f3bfa1c384fd998b1fdd2855ac6f0c8554c520fb0bfa3663f238124035e14682bc11eaf7c372b6af4ed7f59a406810c71711906f8c91f94b1f",
    ),
)

declare_proof_of_space = farmer_protocol.DeclareProofOfSpace(
    bytes32([0] * 16 + [1] * 16),
    bytes32(b"a" * 16 + b"b" * 16),
    uint8(60),
    bytes32([0] * 16 + [1] * 16),
    proof_of_space,
    G2Element.from_bytes(bytes.fromhex("c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000")),
    G2Element.from_bytes(bytes.fromhex("c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000")),
    bytes32([0] * 32),
    PoolTarget(bytes.fromhex("d23da14695a188ae5708dd152263c4db883eb27edeb936178d4d988b8f3ce5fc"), uint32(0)),
    G2Element.from_bytes(bytes.fromhex("c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000")),
)

request_signed_values = farmer_protocol.RequestSignedValues(
    bytes32([0] * 16 + [1] * 16),
    bytes32(b"a" * 16 + b"b" * 16),
    bytes32([0] * 32),
)

farming_info = farmer_protocol.FarmingInfo(
    bytes32([0] * 16 + [1] * 16),
    bytes32(b"a" * 16 + b"b" * 16),
    uint64(100000),
    uint32(0),
    uint32(1),
    uint32(2),
)

signed_values = farmer_protocol.SignedValues(
    bytes32([0] * 16 + [1] * 16),
    G2Element.from_bytes(bytes.fromhex("c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000")),
    G2Element.from_bytes(bytes.fromhex("c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000")),
)
