from enum import Enum


class ProtocolMessageTypes(Enum):
    # Shared protocol (all services)
    handshake = 1
    handshake_ack = 2

    # Harvester protocol (harvester <-> farmer)
    harvester_handshake = 3
    new_signage_point_harvester = 4
    new_proof_of_space = 5
    request_signatures = 6
    respond_signatures = 7

    # Farmer protocol (farmer <-> full_node)
    new_signage_point = 8
    declare_proof_of_space = 9
    request_signed_values = 10
    signed_values = 11
    farming_info = 12

    # Timelord protocol (timelord <-> full_node)
    new_peak_timelord = 13
    new_unfinished_block_timelord = 14
    new_infusion_point_vdf = 15
    new_signage_point_vdf = 16
    new_end_of_sub_slot_vdf = 17

    # Full node protocol (full_node <-> full_node)
    new_peak = 18
    new_transaction = 19
    request_transaction = 20
    respond_transaction = 21
    request_proof_of_weight = 22
    respond_proof_of_weight = 23
    request_block = 24
    respond_block = 25
    reject_block = 26
    request_blocks = 27
    respond_blocks = 28
    reject_blocks = 29
    new_unfinished_block = 30
    request_unfinished_block = 31
    respond_unfinished_block = 32
    new_signage_point_or_end_of_sub_slot = 33
    request_signage_point_or_end_of_sub_slot = 34
    respond_signage_point = 35
    respond_end_of_sub_slot = 36
    request_mempool_transactions = 37
    request_compact_vdfs = 38
    respond_compact_vdfs = 39
    request_peers = 40
    respond_peers = 41

    # Wallet protocol (wallet <-> full_node)
    request_puzzle_solution = 42
    respond_puzzle_solution = 43
    reject_puzzle_solution = 44
    send_transaction = 45
    transaction_ack = 46
    new_peak_wallet = 47
    request_block_header = 48
    respond_block_header = 49
    reject_header_request = 50
    request_removals = 51
    respond_removals = 52
    reject_removals_request = 53
    request_additions = 54
    respond_additions = 55
    reject_additions_request = 56
    request_header_blocks = 57
    reject_header_blocks = 58
    respond_header_blocks = 59

    # Introducer protocol (introducer <-> full_node)
    request_peers_introducer = 60
    respond_peers_introducer = 61

    # Simulator protocol
    farm_new_block = 62
