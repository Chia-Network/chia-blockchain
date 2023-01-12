# flake8: noqa

from __future__ import annotations

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
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.foliage import Foliage, FoliageBlockData, FoliageTransactionBlock, TransactionsInfo
from chia.types.blockchain_format.pool_target import PoolTarget
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.reward_chain_block import RewardChainBlock
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.slots import (
    ChallengeChainSubSlot,
    InfusedChallengeChainSubSlot,
    RewardChainSubSlot,
    SubSlotProofs,
)
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.blockchain_format.vdf import VDFInfo, VDFProof
from chia.types.coin_spend import CoinSpend
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.types.full_block import FullBlock
from chia.types.header_block import HeaderBlock
from chia.types.peer_info import TimestampedPeerInfo
from chia.types.spend_bundle import SpendBundle
from chia.types.unfinished_block import UnfinishedBlock
from chia.types.weight_proof import RecentChainData, SubEpochChallengeSegment, SubEpochData, SubSlotData, WeightProof
from chia.util.ints import uint8, uint16, uint32, uint64, uint128

### FARMER PROTOCOL
new_signage_point = farmer_protocol.NewSignagePoint(
    bytes32(bytes.fromhex("34b2a753b0dc864e7218f8facf23ca0e2b636351df5289b76f5845d9a78b7026")),
    bytes32(bytes.fromhex("9dc8b9d685c79acdf8780d994416dfcfb118e0adc99769ecfa94e1f40aa5bbe5")),
    bytes32(bytes.fromhex("b2828a2c7f6a2555c80c3ca9d10792a7da6ee80f686122ecd2c748dc0569a867")),
    uint64(2329045448547720842),
    uint64(8265724497259558930),
    uint8(194),
)

proof_of_space = ProofOfSpace(
    bytes32(bytes.fromhex("1fb331df88bc142e70c110e21620374118fb220ccc3ef621378197e850882ec9")),
    G1Element(
        bytes.fromhex(
            "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
        ),
    ),
    None,
    G1Element(
        bytes.fromhex(
            "b6449c2c68df97c19e884427e42ee7350982d4020571ead08732615ff39bd216bfd630b6460784982bec98b49fea79d0"
        ),
    ),
    uint8(204),
    bytes.fromhex(
        "a67188ae0c02c49b0e821a9773033a3fbd338030c383080dbb8b1d63f07af427d8075e59d911f85ea562fd967823588f9a405a4464fdf5dc0866ee15bebd6b94cb147e28aa9cf96da930611486b779737ed721ea376b9939ba05357141223d75d21b21f310ec32d85ed3b98cf301494ea91b8501138481f3bfa1c384fd998b1fdd2855ac6f0c8554c520fb0bfa3663f238124035e14682bc11eaf7c372b6af4ed7f59a406810c71711906f8c91f94b1f",
    ),
)

pool_target = PoolTarget(
    bytes32.from_hexstr("d23da14695a188ae5708dd152263c4db883eb27edeb936178d4d988b8f3ce5fc"),
    uint32(421941852),
)
g2_element = G2Element(
    bytes.fromhex(
        "c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    )
)

declare_proof_of_space = farmer_protocol.DeclareProofOfSpace(
    bytes32(bytes.fromhex("3f44d177faa11cea40477f233a8b365cce77215a84f48f65a37b2ac35c7e3ccc")),
    bytes32(bytes.fromhex("931c83fd8ef121177257301e11f41642618ddac65509939e252243e41bacbf78")),
    uint8(31),
    bytes32(bytes.fromhex("6c8dbcfae52c8df391231f3f7aae24c0b1e2be9638f6fc9e4c216b9ff43548d1")),
    proof_of_space,
    G2Element(
        bytes.fromhex(
            "c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        )
    ),
    G2Element(
        bytes.fromhex(
            "c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        )
    ),
    bytes32(bytes.fromhex("3843d1c2c574d376225733cf1a9c63da7051954b88b5adc1a4c198c1c7d5edfd")),
    pool_target,
    G2Element(
        bytes.fromhex(
            "c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        )
    ),
)

request_signed_values = farmer_protocol.RequestSignedValues(
    bytes32(bytes.fromhex("60649de258d2221ca6a178476861b13f8c394a992eaeae1f1159c32bbf703b45")),
    bytes32(bytes.fromhex("9da23e943246bb99ebeb5e773e35a445bbbfdbd45dd9b9df169eeca80880a53b")),
    bytes32(bytes.fromhex("5d76a4bcb3524d862e92317410583daf50828927885444c6d62ca8843635c46f")),
)

farming_info = farmer_protocol.FarmingInfo(
    bytes32(bytes.fromhex("345cefad6a04d3ea4fec4b31e56000de622de9fe861afa53424138dd45307fc2")),
    bytes32(bytes.fromhex("1105c288abb976e95804796aea5bb6f66a6b500c0f538d4e71f0d701cad9ff11")),
    uint64(16359391077414942762),
    uint32(1390832181),
    uint32(908923578),
    uint32(2259819406),
)

signed_values = farmer_protocol.SignedValues(
    bytes32(bytes.fromhex("915de5949724e1fc92d334e589c26ddbcd67415cbbdbbfc5e6de93b3b33bb267")),
    G2Element(
        bytes.fromhex(
            "c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        )
    ),
    G2Element(
        bytes.fromhex(
            "c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        )
    ),
)


### FULL NODE PROTOCOL.
new_peak = full_node_protocol.NewPeak(
    bytes32(bytes.fromhex("8a346e8dc02e9b44c0571caa74fd99f163d4c5d7deae9f8ddb00528721493f7a")),
    uint32(2653549198),
    uint128(196318552117141200341240034145143439804),
    uint32(928039765),
    bytes32(bytes.fromhex("dd421c55d4edaeeb3ad60e80d73c2005a1b275c381c7e418915200d7467711b5")),
)

new_transaction = full_node_protocol.NewTransaction(
    bytes32(bytes.fromhex("e4fe833328d4e82f9c57bc1fc2082c9b63da23e46927522cb5a073f9f0979b6a")),
    uint64(13950654730705425115),
    uint64(10674036971945712700),
)

request_transaction = full_node_protocol.RequestTransaction(
    bytes32(bytes.fromhex("3dc310a07be53bfd701e4a0d77ce39836eeab4717fe25b1ae4c3f16aad0e5d83")),
)

coin_1 = Coin(
    bytes32(bytes.fromhex("d56f435d3382cb9aa5f50f51816e4c54487c66402339901450f3c810f1d77098")),
    bytes32(bytes.fromhex("9944f63fcc251719b2f04c47ab976a167f96510736dc6fdfa8e037d740f4b5f3")),
    uint64(6602327684212801382),
)

serialized_program_1 = SerializedProgram.from_bytes(
    bytes.fromhex(
        "ff01ffff33ffa0f8912302fb33b8188046662785704afc3dd945074e4b45499a7173946e044695ff8203e880ffff33ffa03eaa52e850322dbc281c6b922e9d8819c7b4120ee054c4aa79db50be516a2bcaff8207d08080"
    )
)
serialized_program_2 = SerializedProgram.from_bytes(
    bytes.fromhex(
        "ffff01ffff33ffa0f8912302fb33b8188046662785704afc3dd945074e4b45499a7173946e044695ff8203e880ffff33ffa03eaa52e850322dbc281c6b922e9d8819c7b4120ee054c4aa79db50be516a2bcaff8207d08080ff8080"
    )
)

coin_spend = CoinSpend(
    coin_1,
    serialized_program_1,
    serialized_program_2,
)

coin_spends = [coin_spend]

spend_bundle = SpendBundle(
    coin_spends,
    G2Element(
        bytes.fromhex(
            "c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        )
    ),
)

respond_transaction = full_node_protocol.RespondTransaction(spend_bundle)

request_proof_of_weight = full_node_protocol.RequestProofOfWeight(
    uint32(1109907246),
    bytes32(bytes.fromhex("1fa3bfc747762c6edbe9937630e50b6982c3cf4fd67931f2ffcececb8c509839")),
)

sub_epochs = SubEpochData(
    bytes32(bytes.fromhex("6fdcfaabeb149f9c44c80c230c44771e14b3d4e1b361dcca9c823b7ea7887ffe")),
    uint8(190),
    uint64(10527522631566046685),
    uint64(989988965238543242),
)

vdf_info = VDFInfo(
    bytes32(bytes.fromhex("7cbd5905838c1dc2becd00298a5b3a6e42b6a306d574c8897cd721f84d429972")),
    uint64(14708638287767651172),
    ClassgroupElement.get_default_element(),
)

vdf_proof = VDFProof(
    uint8(197),
    bytes(b"0" * 100),
    False,
)

sub_slot_data = SubSlotData(
    proof_of_space,
    vdf_proof,
    vdf_proof,
    vdf_proof,
    vdf_info,
    uint8(255),
    vdf_proof,
    vdf_proof,
    vdf_info,
    vdf_info,
    vdf_info,
    vdf_info,
    uint128(178067533887691737655963933428342640848),
)

sub_epoch_challenge_segments = SubEpochChallengeSegment(
    uint32(3946877794),
    [sub_slot_data],
    vdf_info,
)

challenge_chain = ChallengeChainSubSlot(
    vdf_info,
    bytes32(bytes.fromhex("42c10d66108589c11bb3811b37d214b6351b73e25bad6c956c0bf1c05a4d93fb")),
    bytes32(bytes.fromhex("cdb6d334b461a01c4d07c76dd71d5a9f3a2949807a3499eb484e4b91e6cea309")),
    uint64(42556034269004566),
    uint64(16610212302933121129),
)

infused_challenge_chain = InfusedChallengeChainSubSlot(
    vdf_info,
)

reward_chain = RewardChainSubSlot(
    vdf_info,
    bytes32(bytes.fromhex("893f282b27c4961f47d886577a8d7c136d1e738e6c5badd37c1994e68871cb70")),
    bytes32(bytes.fromhex("4be4cc2a1f15c5c69fb9becac0cbe0df5ea007a94f22bca79f88e14fc2a46def")),
    uint8(52),
)

proofs = SubSlotProofs(
    vdf_proof,
    vdf_proof,
    vdf_proof,
)

reward_chain_block = RewardChainBlock(
    uint128(187084448821891925757676377381787790114),
    uint32(301889038),
    uint128(147405131564197136044258885592706844266),
    uint8(9),
    bytes32(bytes.fromhex("50102505a28e3969db19c699a5e53af73c1cb3108e2ab9ce9d86d1f058b10457")),
    proof_of_space,
    vdf_info,
    g2_element,
    vdf_info,
    vdf_info,
    g2_element,
    vdf_info,
    vdf_info,
    False,
)

foliage_block_data = FoliageBlockData(
    bytes32(bytes.fromhex("205be4e4efff5b8d99b3f5c8d0ad19072875b9bac1ec3edda1f0df5467e2e61a")),
    pool_target,
    g2_element,
    bytes32(bytes.fromhex("4e62d7ed145b394ce28533e4f0a7d70f339f9d4c49ee717e51e2d6480e5fcbcc")),
    bytes32(bytes.fromhex("d53254dcdcbfddb431c3ff89d1a785491663b51552e3847d29e36972f43b536d")),
)

foliage = Foliage(
    bytes32(bytes.fromhex("312fd3fe7c9a21cd90ce40b567730ab087fa29436bf8568adacc605f52912fba")),
    bytes32(bytes.fromhex("ba37d30b755680e0b8873a1b7f0ae7636400999ca2b2d32ad0aebb0c24e258aa")),
    foliage_block_data,
    g2_element,
    bytes32(bytes.fromhex("ac6a47ca76efeac93b1c435dfa2e876ab63c0a62fa7aa5a6b8cf9efd95084025")),
    g2_element,
)

foliage_transaction_block = FoliageTransactionBlock(
    bytes32(bytes.fromhex("852ed117f46fa98af7a17fcb050c369245a30fcffc190177c3a316109d1609c7")),
    uint64(3871668531533889186),
    bytes32(bytes.fromhex("ffab724c5df9b90c0842565225f5ed842da14f159373c05d63643405ccce84b3")),
    bytes32(bytes.fromhex("5f87a17fafb44afd0d6b5b67b77be38570b4bc0150388bd9c176d4ac5d4e693b")),
    bytes32(bytes.fromhex("db967ce278f9bf4fdc77cb9fa82b5b2ce6876746eb5e61f4352a41e3abb63275")),
    bytes32(bytes.fromhex("7eebe3b21505f7c7cb5536e96ab893bfa4626a5cf9c79fadb5dae6913e0a7cb3")),
)

end_of_subslot_bundle = EndOfSubSlotBundle(
    challenge_chain,
    infused_challenge_chain,
    reward_chain,
    proofs,
)

transactions_info = TransactionsInfo(
    bytes32(bytes.fromhex("4cb791379aee03879628f69f16c0d3b78fd865c010c53c3b412dfa56e40f4d78")),
    bytes32(bytes.fromhex("180c72ecd6e32986a354681fcf6924aa82c08cfb9df95667fa24442103cc2189")),
    g2_element,
    uint64(5840504611725889474),
    uint64(7273736876528078474),
    [
        Coin(
            bytes32(bytes.fromhex("dde12b149d44bafd07390d2ad6ce774ab50d083ada3f0bc3c0adebe6a6a1a4ab")),
            bytes32(bytes.fromhex("503da231145145b114e85af933ed86a5834c08323743803ee31fca2b1c64ce15")),
            uint64(8428133224333694484),
        ),
    ],
)

header_block = HeaderBlock(
    [end_of_subslot_bundle],
    reward_chain_block,
    vdf_proof,
    vdf_proof,
    vdf_proof,
    vdf_proof,
    vdf_proof,
    foliage,
    foliage_transaction_block,
    bytes([0] * 50),
    transactions_info,
)

recent_chain_data = RecentChainData(
    [header_block],
)

weight_proof = WeightProof(
    [sub_epochs],
    [sub_epoch_challenge_segments],
    [header_block],
)

respond_proof_of_weight = full_node_protocol.RespondProofOfWeight(
    weight_proof,
    bytes32(bytes.fromhex("bf71d6f1ecae308aacf87db77aeba5a06f5d1099bfc7005529885e1f2dad857f")),
)

request_block = full_node_protocol.RequestBlock(
    uint32(678860074),
    False,
)

reject_block = full_node_protocol.RejectBlock(
    uint32(966946253),
)

request_blocks = full_node_protocol.RequestBlocks(
    uint32(2578479570),
    uint32(3884442719),
    False,
)

full_block = FullBlock(
    [end_of_subslot_bundle],
    reward_chain_block,
    vdf_proof,
    vdf_proof,
    vdf_proof,
    vdf_proof,
    vdf_proof,
    foliage,
    foliage_transaction_block,
    transactions_info,
    SerializedProgram.from_bytes(
        bytes.fromhex(
            "ff01ffff33ffa0f8912302fb33b8188046662785704afc3dd945074e4b45499a7173946e044695ff8203e880ffff33ffa03eaa52e850322dbc281c6b922e9d8819c7b4120ee054c4aa79db50be516a2bcaff8207d08080"
        )
    ),
    [uint32(2456207540)],
)

respond_blocks = full_node_protocol.RespondBlocks(uint32(1000), uint32(4201431299), [full_block, full_block])

reject_blocks = full_node_protocol.RejectBlocks(
    uint32(1160742782),
    uint32(1856800720),
)

respond_block = full_node_protocol.RespondBlock(
    full_block,
)

new_unfinished_block = full_node_protocol.NewUnfinishedBlock(
    bytes32(bytes.fromhex("229646fb33551966039d9324c0d10166c554d20e9a11e3f30942ec0bb346377e")),
)

request_unfinished_block = full_node_protocol.RequestUnfinishedBlock(
    bytes32(bytes.fromhex("8b5e5a59f33bb89e1bfd5aca79409352864e70aa7765c331d641875f83d59d1d")),
)

unfinished_block = UnfinishedBlock(
    [end_of_subslot_bundle],
    reward_chain_block.get_unfinished(),
    vdf_proof,
    vdf_proof,
    foliage,
    foliage_transaction_block,
    transactions_info,
    SerializedProgram.from_bytes(
        bytes.fromhex(
            "ff01ffff33ffa0f8912302fb33b8188046662785704afc3dd945074e4b45499a7173946e044695ff8203e880ffff33ffa03eaa52e850322dbc281c6b922e9d8819c7b4120ee054c4aa79db50be516a2bcaff8207d08080"
        )
    ),
    [uint32(1862532955)],
)

respond_unfinished_block = full_node_protocol.RespondUnfinishedBlock(unfinished_block)

new_signage_point_or_end_of_subslot = full_node_protocol.NewSignagePointOrEndOfSubSlot(
    bytes32(bytes.fromhex("f945510ccea927f832635e56bc20315c92943e108d2b458ac91a290a82e02997")),
    bytes32(bytes.fromhex("27a16b348971e5dfb258e7a01f0b300acbecf8339476afd144e8520f1981833b")),
    uint8(102),
    bytes32(bytes.fromhex("a619471c0ba0b8b8b92b7b2cb1241c2fbb2324c4f1a20a01eb7dcc0027393a56")),
)

request_signage_point_or_end_of_subslot = full_node_protocol.RequestSignagePointOrEndOfSubSlot(
    bytes32(bytes.fromhex("edd45b516bf1dc3754c30a99e289639e05f967dc1b590df8a377652bee4f463c")),
    uint8(217),
    bytes32(bytes.fromhex("b574062b42a5b3d76ea141d3b89a4a1096f7797bafe625770047380448622420")),
)

respond_signage_point = full_node_protocol.RespondSignagePoint(
    uint8(111),
    vdf_info,
    vdf_proof,
    vdf_info,
    vdf_proof,
)

respond_end_of_subslot = full_node_protocol.RespondEndOfSubSlot(
    end_of_subslot_bundle,
)

request_mempool_transaction = full_node_protocol.RequestMempoolTransactions(
    bytes([0] * 32),
)

new_compact_vdf = full_node_protocol.NewCompactVDF(
    uint32(1333973478),
    bytes32(bytes.fromhex("e2188779d4a8e8fdf9cbe3103878b4c3f5f25a999fa8d04551c4ae01046c634e")),
    uint8(169),
    vdf_info,
)

request_compact_vdf = full_node_protocol.RequestCompactVDF(
    uint32(3529778757),
    bytes32(bytes.fromhex("1c02dfbf437c464cfd3f71d2da283c22bd04b2061e3c6b4bfd8b859092957d96")),
    uint8(207),
    vdf_info,
)

respond_compact_vdf = full_node_protocol.RespondCompactVDF(
    uint32(2759248594),
    bytes32(bytes.fromhex("51f2e23ac76179d69bc9232420f47e2a332b8c2495c24ceef7f730feb53c9117")),
    uint8(167),
    vdf_info,
    vdf_proof,
)

request_peers = full_node_protocol.RequestPeers()

timestamped_peer_info = TimestampedPeerInfo("127.0.0.1", uint16(8444), uint64(10796))

respond_peers = full_node_protocol.RespondPeers([timestamped_peer_info])


## WALLET PROTOCOL
request_puzzle_solution = wallet_protocol.RequestPuzzleSolution(
    bytes32(bytes.fromhex("6edddb46bd154f50566b49c95812e0f1131a0a7162630349fc8d1d696e463e47")),
    uint32(3905474497),
)

program = Program.fromhex(
    "ff01ffff33ffa0f8912302fb33b8188046662785704afc3dd945074e4b45499a7173946e044695ff8203e880ffff33ffa03eaa52e850322dbc281c6b922e9d8819c7b4120ee054c4aa79db50be516a2bcaff8207d08080"
)

puzzle_solution_response = wallet_protocol.PuzzleSolutionResponse(
    bytes32(bytes.fromhex("45c4451fdeef92aa0706def2448adfaed8e4a1c0b08a6d303c57de661509c442")),
    uint32(3776325015),
    program,
    program,
)

respond_puzzle_solution = wallet_protocol.RespondPuzzleSolution(
    puzzle_solution_response,
)

reject_puzzle_solution = wallet_protocol.RejectPuzzleSolution(
    bytes32(bytes.fromhex("2f16254e8e7a0b3fbe7bc709d29c5e7d2daa23ce1a2964e3f77b9413055029dd")),
    uint32(2039721496),
)

send_transaction = wallet_protocol.SendTransaction(
    spend_bundle,
)

transaction_ack = wallet_protocol.TransactionAck(
    bytes32(bytes.fromhex("fc30d2df70f4ca0a138d5135d352611ddf268ea46c59cde48c29c43d9472532c")),
    uint8(30),
    "None",
)

new_peak_wallet = wallet_protocol.NewPeakWallet(
    bytes32(bytes.fromhex("ee50e45652cb6a60e3ab0031aa425a6019648fe5344ae860e6fc14af1aa3c2fa")),
    uint32(1093428752),
    uint128(207496292293729126634170184354599452208),
    uint32(133681371),
)

request_block_header = wallet_protocol.RequestBlockHeader(
    uint32(3562957314),
)

request_block_headers = wallet_protocol.RequestBlockHeaders(
    uint32(1234970524),
    uint32(234653234),
    False,
)

respond_header_block = wallet_protocol.RespondBlockHeader(
    header_block,
)

respond_block_headers = wallet_protocol.RespondBlockHeaders(
    uint32(923662371),
    uint32(992357623),
    [header_block],
)

reject_header_request = wallet_protocol.RejectHeaderRequest(
    uint32(17867635),
)

request_removals = wallet_protocol.RequestRemovals(
    uint32(3500751918),
    bytes32(bytes.fromhex("b44bc0e0fce20331a57081107dfd30ef39fc436e6e6ce4f6f0ab8db4f981d114")),
    [bytes32(bytes.fromhex("ab62cfb2abaf9e1a475b707c3d3de35d6ef4a298b31137802fd9ea47d48ff0d5"))],
)

respond_removals = wallet_protocol.RespondRemovals(
    uint32(461268095),
    bytes32(bytes.fromhex("e2db23a6484b05d9ae1033efe8dcfcf5894fc600a6b93b03782fab8dd1cba8a4")),
    [(bytes32(bytes.fromhex("f800ab7a0d1598c473e31700b21a7cc590c1619f10e72a707d1c66f090e4e078")), coin_1)],
    [(bytes32(bytes.fromhex("652c312e1dd9f32bf074e17ae8b658bf47711bd1a5e6c937adfb0c80b51fa49d")), bytes(b"a" * 10))],
)

reject_removals_request = wallet_protocol.RejectRemovalsRequest(
    uint32(3247661701),
    bytes32(bytes.fromhex("d5eee2d2ad56663c1c1d1cbde69329862dcf29010683aa7a0da91712d6876caf")),
)

request_additions = wallet_protocol.RequestAdditions(
    uint32(2566479739),
    bytes32(bytes.fromhex("17262e35437ddc95d43431d20657c096cff95f7ba93a39367f56f1f9df0f0277")),
    [bytes32(bytes.fromhex("6fc7b72bc37f462dc820d4b39c9e69e9e65b590ee1a6b0a06b5105d048c278d4"))],
)

respond_additions = wallet_protocol.RespondAdditions(
    uint32(1992350400),
    bytes32(bytes.fromhex("449ba349ce403c1acfcd46108758e7ada3a455e7a82dbee90860ec73adb090c9")),
    [(bytes32(bytes.fromhex("ed8daaf9233ed82e773ef4d1e89f2958fec0570137cf2c267ae22099ab43a9a4")), [coin_1, coin_1])],
    [
        (
            bytes32(bytes.fromhex("8bb1381ff8ee01944d6d6c7e2df4b2fc84343a0c6c0fb93e8ef6d75e5c8b3048")),
            bytes(b"a" * 10),
            bytes(b"a" * 10),
        )
    ],
)

reject_additions = wallet_protocol.RejectAdditionsRequest(
    uint32(3457211200),
    bytes32(bytes.fromhex("4eb659e6dd727bc22191795692aae576922e56ae309871c352eede0c9dd8bb12")),
)

request_header_blocks = wallet_protocol.RequestHeaderBlocks(
    uint32(2858301848),
    uint32(720941539),
)

reject_header_blocks = wallet_protocol.RejectHeaderBlocks(
    uint32(876520264),
    uint32(2908717391),
)

reject_block_headers = wallet_protocol.RejectBlockHeaders(
    uint32(543373229),
    uint32(2347869036),
)

respond_header_blocks = wallet_protocol.RespondHeaderBlocks(
    uint32(4130100992),
    uint32(17664086),
    [header_block],
)

coin_state = wallet_protocol.CoinState(
    coin_1,
    uint32(2287030048),
    uint32(3361305811),
)

register_for_ph_updates = wallet_protocol.RegisterForPhUpdates(
    [bytes32(bytes.fromhex("df24b7dc1d5ffa12f112e198cd26385b5ab302b5c2e5f9d589e5cd3f7b900510"))],
    uint32(874269130),
)

respond_to_ph_updates = wallet_protocol.RespondToPhUpdates(
    [bytes32(bytes.fromhex("1be3bdc54b84901554e4e843966cfa3be3380054c968bebc41cc6be4aa65322f"))],
    uint32(3664709982),
    [coin_state],
)

register_for_coin_updates = wallet_protocol.RegisterForCoinUpdates(
    [bytes32(bytes.fromhex("1d7748531ece395e8bb8468b112d4ccdd1cea027359abd03c0b015edf666eec8"))],
    uint32(3566185528),
)

respond_to_coin_updates = wallet_protocol.RespondToCoinUpdates(
    [bytes32(bytes.fromhex("db8bad6bd9de34d4884380176135f31a655dca18e9a5fadfb567145b81b6a9e0"))],
    uint32(3818814774),
    [coin_state],
)

coin_state_update = wallet_protocol.CoinStateUpdate(
    uint32(855344561),
    uint32(1659753011),
    bytes32(bytes.fromhex("8512cc80a2976c81186e8963bc7af9d6d5732ccae5227fffee823f0bf3081e76")),
    [coin_state],
)

request_children = wallet_protocol.RequestChildren(
    bytes32(bytes.fromhex("15beeed2e6dd0cf1b81a3f68a49845c020912218e4c1f002a1b3f43333495478")),
)

respond_children = wallet_protocol.RespondChildren(
    [coin_state],
)

request_ses_info = wallet_protocol.RequestSESInfo(
    uint32(2704205398),
    uint32(2050258406),
)

respond_ses_info = wallet_protocol.RespondSESInfo(
    [bytes32(bytes.fromhex("b61cb91773995e99cb8259609c0985f915a5734a1706aeab9342a2d1c5abf71b"))],
    [[uint32(1), uint32(2), uint32(3)], [uint32(4), uint32(606340525)]],
)


### HARVESTER PROTOCOL
pool_difficulty = harvester_protocol.PoolDifficulty(
    uint64(14819251421858580996),
    uint64(12852879676624401630),
    bytes32(bytes.fromhex("c9423123ea65e6923e973b95531b4874570dae942cb757a2daec4a6971753886")),
)

harvester_handhsake = harvester_protocol.HarvesterHandshake(
    [
        G1Element(
            bytes.fromhex(
                "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
            ),
        ),
    ],
    [
        G1Element(
            bytes.fromhex(
                "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
            ),
        ),
    ],
)

new_signage_point_harvester = harvester_protocol.NewSignagePointHarvester(
    bytes32(bytes.fromhex("e342c21b4aeaa52349d42492be934692db58494ca9bce4a8697d06fdf8e583bb")),
    uint64(15615706268399948682),
    uint64(10520767421667792980),
    uint8(148),
    bytes32(bytes.fromhex("b78c9fca155e9742df835cbe84bb7e518bee70d78b6be6e39996c0a02e0cfe4c")),
    [pool_difficulty],
)

new_proof_of_space = harvester_protocol.NewProofOfSpace(
    bytes32(bytes.fromhex("1b64ec6bf3fe33bb80eca5b64ff1c88be07771eaed1e98a7199510522087e56e")),
    bytes32(bytes.fromhex("ad1f8a74376ce8c5c93b7fbb355c2fb6d689ae4f4a7134166593d95265a3da30")),
    "plot_1",
    proof_of_space,
    uint8(160),
)

request_signatures = harvester_protocol.RequestSignatures(
    "plot_1",
    bytes32(bytes.fromhex("b5fa873020fa8b959d89bc2ffc5797501bf870ac8b30437cd6b4fcdea0812789")),
    bytes32(bytes.fromhex("bccb7744192771f3a7abca2bce6ea03ed53f1f0d991c13bd2711ce32a2fb3777")),
    [bytes32(bytes.fromhex("3fc12545f50a9f0621371688f60b29eff05805dd51b42c90063f5e3c6698fc75"))],
)

respond_signatures = harvester_protocol.RespondSignatures(
    "plot_1",
    bytes32(bytes.fromhex("59468dce63b5b08490ec4eec4c461fc84b69b6f80a64f4c76b0d55780f7e7e7a")),
    bytes32(bytes.fromhex("270b5fc00545db714077aba3b60245d769f492563f108a73b2b8502503d12b9e")),
    G1Element(
        bytes.fromhex(
            "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
        ),
    ),
    G1Element(
        bytes.fromhex(
            "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
        ),
    ),
    [(bytes32(bytes.fromhex("c32fd5310f5e8623697561930dca73cb9da5b3ddb903f52818724bb3bdd9349c")), g2_element)],
)

plot = harvester_protocol.Plot(
    "plot_1",
    uint8(124),
    bytes32(bytes.fromhex("b2eb7e5c5239e8610a9dd0e137e185966ebb430faf31ae4a0e55d86251065b98")),
    G1Element(
        bytes.fromhex(
            "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
        ),
    ),
    bytes32(bytes.fromhex("1c96d26def7be696f12e7ebb91d50211e6217ce5d9087c9cd1b84782d5d4b237")),
    G1Element(
        bytes.fromhex(
            "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
        ),
    ),
    uint64(3368414292564311420),
    uint64(2573238947935295522),
)

request_plots = harvester_protocol.RequestPlots()

respond_plots = harvester_protocol.RespondPlots(
    [plot],
    ["str"],
    ["str"],
)

### INTRODUCER PROTOCOL
request_peers_introducer = introducer_protocol.RequestPeersIntroducer()

respond_peers_introducer = introducer_protocol.RespondPeersIntroducer(
    [
        TimestampedPeerInfo(
            "127.0.0.1",
            uint16(49878),
            uint64(15079028934557257795),
        )
    ]
)


### POOL PROTOCOL
authentication_payload = pool_protocol.AuthenticationPayload(
    "method",
    bytes32(bytes.fromhex("0251e3b3a1aacc689091b6b085be7a8d319bd9d1a015faae969cb76d8a45607c")),
    bytes32(bytes.fromhex("9de241b508b5e9e2073b7645291cfaa9458d33935340399a861acf2ee1770440")),
    uint64(4676522834655707230),
)

get_pool_info_response = pool_protocol.GetPoolInfoResponse(
    "pool_name",
    "pool_name",
    uint64(7020711482626732214),
    uint32(3407308703),
    uint8(129),
    "fee",
    "pool description.",
    bytes32(bytes.fromhex("f6b5120ff1ab7ba661e3b2c91c8b373a8aceea8e4eb6ce3f085f3e80a8655b36")),
    uint8(76),
)

post_partial_payload = pool_protocol.PostPartialPayload(
    bytes32(bytes.fromhex("dada61e179e67e5e8bc7aaab16e192facf0f15871f0c479d2a96ac5f85721a1a")),
    uint64(2491521039628830788),
    proof_of_space,
    bytes32(bytes.fromhex("929287fab514e2204808821e2afe8c4d84f0093c75554b067fe4fca272890c9d")),
    False,
    bytes32(bytes.fromhex("f98dff6bdcc3926b33cb8ab22e11bd15c13d6a9b6832ac948b3273f5ccd8e7ec")),
)

post_partial_request = pool_protocol.PostPartialRequest(
    post_partial_payload,
    g2_element,
)

post_partial_response = pool_protocol.PostPartialResponse(
    uint64(5956480724816802941),
)

get_farmer_response = pool_protocol.GetFarmerResponse(
    G1Element(
        bytes.fromhex(
            "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
        ),
    ),
    "instructions",
    uint64(8362834206591090467),
    uint64(14310455844127802841),
)

post_farmer_payload = pool_protocol.PostFarmerPayload(
    bytes32(bytes.fromhex("d3785b251b4e066f87784d06afc8e6ac8dac5a4922d994902c1bad60b5fa7ad3")),
    uint64(5820795488800541986),
    G1Element(
        bytes.fromhex(
            "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
        ),
    ),
    "payout_instructions",
    uint64(1996244065095983466),
)

post_farmer_request = pool_protocol.PostFarmerRequest(
    post_farmer_payload,
    g2_element,
)

post_farmer_response = pool_protocol.PostFarmerResponse(
    "welcome",
)

put_farmer_payload = pool_protocol.PutFarmerPayload(
    bytes32(bytes.fromhex("78aec4d523b0bea49829a1322d5de92a86a553ce8774690b8c8ad5fc1f7540a8")),
    uint64(15049374353843709257),
    G1Element(
        bytes.fromhex(
            "a04c6b5ac7dfb935f6feecfdd72348ccf1d4be4fe7e26acf271ea3b7d308da61e0a308f7a62495328a81f5147b66634c"
        ),
    ),
    "payload",
    uint64(201241879360854600),
)

put_farmer_request = pool_protocol.PutFarmerRequest(
    put_farmer_payload,
    g2_element,
)

put_farmer_response = pool_protocol.PutFarmerResponse(
    False,
    False,
    True,
)

error_response = pool_protocol.ErrorResponse(
    uint16(47018),
    "err",
)

### TIMELORD PROTOCOL
sub_epoch_summary = SubEpochSummary(
    bytes32(bytes.fromhex("2d0550de416467e7b57e56e962c712b79bee29cae29c73cc908da5978fc9789e")),
    bytes32(bytes.fromhex("3d29f5a3fe067ce7edea76c9cebaf3a3afdebc0eb9fbd530f807f1a28ed2df6d")),
    uint8(4),
    uint64(14666749803532899046),
    uint64(10901191956946573440),
)

new_peak_timelord = timelord_protocol.NewPeakTimelord(
    reward_chain_block,
    uint64(7661623532867338566),
    uint8(202),
    uint64(16623089924886538940),
    sub_epoch_summary,
    [
        (
            bytes32(bytes.fromhex("5bb65d8662d561ed2fc17e4177ba61c43017ee7e5418091d38968e36ce380d11")),
            uint128(134240022887890669757150210097251845335),
        )
    ],
    uint128(42058411995615810488183751196800190575),
    True,
)

new_unfinished_block_timelord = timelord_protocol.NewUnfinishedBlockTimelord(
    reward_chain_block.get_unfinished(),
    uint64(601152037470280666),
    uint64(14270340639924562415),
    foliage,
    sub_epoch_summary,
    bytes32(bytes.fromhex("0f90296b605904a794e4e98852e3b22e0d9bee2fa07abb12df6cecbdb778e1e5")),
)

new_infusion_point_vdf = timelord_protocol.NewInfusionPointVDF(
    bytes32(bytes.fromhex("3d3b977d3a3dab50f0cd72b74b2f08f5018fb5ef826a8773161b7a499dafa60f")),
    vdf_info,
    vdf_proof,
    vdf_info,
    vdf_proof,
    vdf_info,
    vdf_proof,
)

new_signage_point_vdf = timelord_protocol.NewSignagePointVDF(
    uint8(182),
    vdf_info,
    vdf_proof,
    vdf_info,
    vdf_proof,
)

new_end_of_sub_slot_bundle = timelord_protocol.NewEndOfSubSlotVDF(
    end_of_subslot_bundle,
)

request_compact_proof_of_time = timelord_protocol.RequestCompactProofOfTime(
    vdf_info,
    bytes32(bytes.fromhex("ad71f7e66dc12c4fd7dca7d0c7b4e1825dfd55b93dd590111d2c44bc4f4d66de")),
    uint32(4134186845),
    uint8(237),
)

respond_compact_proof_of_time = timelord_protocol.RespondCompactProofOfTime(
    vdf_info,
    vdf_proof,
    bytes32(bytes.fromhex("071bef40d098cfadc2614d8b57db924788f7f2ea0fde8cf4bfaeae2894caa442")),
    uint32(386395693),
    uint8(224),
)
