from __future__ import annotations

from enum import Enum


class ProtocolMessageTypes(Enum):
    # Shared protocol (all services)
    handshake = 1

    # Harvester protocol (harvester <-> farmer)
    harvester_handshake = 3
    # new_signage_point_harvester = 4 Changed to 66 in new protocol
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
    request_compact_proof_of_time = 18
    respond_compact_proof_of_time = 19

    # Full node protocol (full_node <-> full_node)
    new_peak = 20
    new_transaction = 21
    request_transaction = 22
    respond_transaction = 23
    request_proof_of_weight = 24
    respond_proof_of_weight = 25
    request_block = 26
    respond_block = 27
    reject_block = 28
    request_blocks = 29
    respond_blocks = 30
    reject_blocks = 31
    new_unfinished_block = 32
    request_unfinished_block = 33
    respond_unfinished_block = 34
    new_signage_point_or_end_of_sub_slot = 35
    request_signage_point_or_end_of_sub_slot = 36
    respond_signage_point = 37
    respond_end_of_sub_slot = 38
    request_mempool_transactions = 39
    request_compact_vdf = 40
    respond_compact_vdf = 41
    new_compact_vdf = 42
    request_peers = 43
    respond_peers = 44
    none_response = 91

    # Wallet protocol (wallet <-> full_node)
    request_puzzle_solution = 45
    respond_puzzle_solution = 46
    reject_puzzle_solution = 47
    send_transaction = 48
    transaction_ack = 49
    new_peak_wallet = 50
    request_block_header = 51
    respond_block_header = 52
    reject_header_request = 53
    request_removals = 54
    respond_removals = 55
    reject_removals_request = 56
    request_additions = 57
    respond_additions = 58
    reject_additions_request = 59
    request_header_blocks = 60
    reject_header_blocks = 61
    respond_header_blocks = 62

    # Introducer protocol (introducer <-> full_node)
    request_peers_introducer = 63
    respond_peers_introducer = 64

    # Simulator protocol
    farm_new_block = 65

    # New harvester protocol
    new_signage_point_harvester = 66
    request_plots = 67
    respond_plots = 68
    plot_sync_start = 78
    plot_sync_loaded = 79
    plot_sync_removed = 80
    plot_sync_invalid = 81
    plot_sync_keys_missing = 82
    plot_sync_duplicates = 83
    plot_sync_done = 84
    plot_sync_response = 85

    # More wallet protocol
    coin_state_update = 69
    register_interest_in_puzzle_hash = 70
    respond_to_ph_update = 71
    register_interest_in_coin = 72
    respond_to_coin_update = 73
    request_children = 74
    respond_children = 75
    request_ses_hashes = 76
    respond_ses_hashes = 77
    request_block_headers = 86
    reject_block_headers = 87
    respond_block_headers = 88
    request_fee_estimates = 89
    respond_fee_estimates = 90

    # new Full Node protocol messages
    new_unfinished_block2 = 92
    request_unfinished_block2 = 93

    # New wallet sync protocol
    request_remove_puzzle_subscriptions = 94
    respond_remove_puzzle_subscriptions = 95
    request_remove_coin_subscriptions = 96
    respond_remove_coin_subscriptions = 97
    request_puzzle_state = 98
    respond_puzzle_state = 99
    reject_puzzle_state = 100
    request_coin_state = 101
    respond_coin_state = 102
    reject_coin_state = 103

    # Wallet protocol mempool updates
    mempool_items_added = 104
    mempool_items_removed = 105
    request_cost_info = 106
    respond_cost_info = 107

    error = 255
