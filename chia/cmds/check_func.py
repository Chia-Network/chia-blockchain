from __future__ import annotations

import pathlib
import re


def check_shielding(use_file_ignore: bool) -> int:
    exclude = {"mozilla-ca"}
    roots = [path.parent for path in sorted(pathlib.Path(".").glob("*/__init__.py")) if path.parent.name not in exclude]

    count = 0
    for root in roots:
        for path in sorted(root.glob("**/*.py")):
            if use_file_ignore and path.as_posix() in hardcoded_file_ignore_list:
                continue

            lines = path.read_text().splitlines()

            for line_index, line in enumerate(lines):
                line_number = line_index + 1

                this_match = re.search(r"^ *(async def [^(]*(close|stop)|(except|finally)\b)[^:]*:", line)
                if this_match is not None:
                    next_line_index = line_index + 1
                    if next_line_index < len(lines):
                        next_line = lines[line_index + 1]

                        ignore_match = re.search(r"^ *# shielding not required: .{10,}", next_line)
                        if ignore_match is not None:
                            continue

                        next_match = re.search(r"^ *with anyio.CancelScope\(shield=True\):", next_line)
                    else:
                        next_match = None
                    if next_match is None:
                        for def_line in reversed(lines[:line_index]):
                            def_match = re.search(r"^ *def", def_line)
                            if def_match is not None:
                                # not async, doesn't need to be shielded
                                break

                            async_def_match = re.search(r"^ *async def", def_line)
                            if async_def_match is not None:
                                count += 1
                                print(f"{path.as_posix()}:{line_number}: {line}")
                                break

    return count


# chia dev check shielding --no-file-ignore &| sed -nE 's/^([^:]*):[0-9]*:.*/    "\1",/p' | sort | uniq
hardcoded_file_ignore_list = {
    "benchmarks/utils.py",
    "chia/cmds/check_wallet_db.py",
    "chia/cmds/cmds_util.py",
    "chia/cmds/coin_funcs.py",
    "chia/cmds/dao_funcs.py",
    "chia/cmds/farm_funcs.py",
    "chia/cmds/passphrase_funcs.py",
    "chia/cmds/peer_funcs.py",
    "chia/cmds/plotnft_funcs.py",
    "chia/cmds/rpc.py",
    "chia/cmds/sim_funcs.py",
    "chia/cmds/start_funcs.py",
    "chia/cmds/wallet_funcs.py",
    "chia/consensus/blockchain.py",
    "chia/consensus/multiprocess_validation.py",
    "chia/daemon/client.py",
    "chia/daemon/keychain_proxy.py",
    "chia/daemon/keychain_server.py",
    "chia/daemon/server.py",
    "chia/data_layer/data_layer.py",
    "chia/data_layer/data_layer_wallet.py",
    "chia/data_layer/data_store.py",
    "chia/data_layer/download_data.py",
    "chia/data_layer/s3_plugin_service.py",
    "chia/farmer/farmer_api.py",
    "chia/farmer/farmer.py",
    "chia/full_node/block_height_map.py",
    "chia/full_node/block_store.py",
    "chia/full_node/full_node_api.py",
    "chia/full_node/full_node.py",
    "chia/full_node/mempool_manager.py",
    "chia/full_node/mempool.py",
    "chia/harvester/harvester_api.py",
    "chia/harvester/harvester.py",
    "chia/introducer/introducer.py",
    "chia/plot_sync/receiver.py",
    "chia/plot_sync/sender.py",
    "chia/plotting/create_plots.py",
    "chia/pools/pool_wallet.py",
    "chia/rpc/crawler_rpc_api.py",
    "chia/rpc/data_layer_rpc_api.py",
    "chia/rpc/farmer_rpc_client.py",
    "chia/rpc/full_node_rpc_api.py",
    "chia/rpc/full_node_rpc_client.py",
    "chia/rpc/rpc_client.py",
    "chia/rpc/rpc_server.py",
    "chia/rpc/util.py",
    "chia/rpc/wallet_rpc_api.py",
    "chia/rpc/wallet_rpc_client.py",
    "chia/seeder/crawler.py",
    "chia/seeder/crawl_store.py",
    "chia/seeder/dns_server.py",
    "chia/server/address_manager_store.py",
    "chia/server/chia_policy.py",
    "chia/server/node_discovery.py",
    "chia/server/server.py",
    "chia/server/signal_handlers.py",
    "chia/server/start_service.py",
    "chia/server/ws_connection.py",
    "chia/simulator/block_tools.py",
    "chia/simulator/setup_services.py",
    "chia/_tests/blockchain/blockchain_test_utils.py",
    "chia/_tests/clvm/test_singletons.py",
    "chia/_tests/conftest.py",
    "chia/_tests/core/data_layer/test_data_rpc.py",
    "chia/_tests/core/data_layer/test_data_store.py",
    "chia/_tests/core/full_node/full_sync/test_full_sync.py",
    "chia/_tests/core/full_node/ram_db.py",
    "chia/_tests/core/full_node/stores/test_coin_store.py",
    "chia/_tests/core/mempool/test_mempool_manager.py",
    "chia/_tests/core/server/flood.py",
    "chia/_tests/core/server/serve.py",
    "chia/_tests/core/server/test_event_loop.py",
    "chia/_tests/core/server/test_loop.py",
    "chia/_tests/core/services/test_services.py",
    "chia/_tests/core/test_farmer_harvester_rpc.py",
    "chia/_tests/core/test_full_node_rpc.py",
    "chia/_tests/db/test_db_wrapper.py",
    "chia/_tests/environments/wallet.py",
    "chia/_tests/pools/test_pool_rpc.py",
    "chia/_tests/pools/test_wallet_pool_store.py",
    "chia/_tests/rpc/test_rpc_client.py",
    "chia/_tests/rpc/test_rpc_server.py",
    "chia/_tests/simulation/test_start_simulator.py",
    "chia/_tests/util/blockchain.py",
    "chia/_tests/util/misc.py",
    "chia/_tests/util/spend_sim.py",
    "chia/_tests/util/split_managers.py",
    "chia/_tests/util/test_async_pool.py",
    "chia/_tests/util/test_priority_mutex.py",
    "chia/_tests/util/time_out_assert.py",
    "chia/_tests/wallet/clawback/test_clawback_metadata.py",
    "chia/_tests/wallet/dao_wallet/test_dao_wallets.py",
    "chia/_tests/wallet/nft_wallet/test_nft_bulk_mint.py",
    "chia/_tests/wallet/rpc/test_dl_wallet_rpc.py",
    "chia/_tests/wallet/rpc/test_wallet_rpc.py",
    "chia/_tests/wallet/sync/test_wallet_sync.py",
    "chia/timelord/timelord_api.py",
    "chia/timelord/timelord_launcher.py",
    "chia/timelord/timelord.py",
    "chia/types/eligible_coin_spends.py",
    "chia/util/action_scope.py",
    "chia/util/async_pool.py",
    "chia/util/beta_metrics.py",
    "chia/util/db_version.py",
    "chia/util/db_wrapper.py",
    "chia/util/files.py",
    "chia/util/limited_semaphore.py",
    "chia/util/network.py",
    "chia/util/priority_mutex.py",
    "chia/util/profiler.py",
    "chia/wallet/cat_wallet/cat_wallet.py",
    "chia/wallet/cat_wallet/dao_cat_wallet.py",
    "chia/wallet/dao_wallet/dao_wallet.py",
    "chia/wallet/did_wallet/did_wallet.py",
    "chia/wallet/nft_wallet/nft_wallet.py",
    "chia/wallet/notification_store.py",
    "chia/wallet/trade_manager.py",
    "chia/wallet/trading/trade_store.py",
    "chia/wallet/vc_wallet/cr_cat_wallet.py",
    "chia/wallet/vc_wallet/vc_wallet.py",
    "chia/wallet/wallet_coin_store.py",
    "chia/wallet/wallet_nft_store.py",
    "chia/wallet/wallet_node_api.py",
    "chia/wallet/wallet_node.py",
    "chia/wallet/wallet_puzzle_store.py",
    "chia/wallet/wallet_state_manager.py",
    "chia/wallet/wallet_transaction_store.py",
}
