import logging
from datetime import datetime
from pathlib import Path
from secrets import token_bytes
from typing import Dict, List, Optional, Tuple

from blspy import AugSchemeMPL, G1Element, PrivateKey
from chiapos import DiskPlotter

from chia.daemon.keychain_proxy import KeychainProxy, connect_to_keychain_and_validate, wrap_local_keychain
from chia.plotting.util import add_plot_directory, stream_plot_info_ph, stream_plot_info_pk
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import decode_puzzle_hash
from chia.util.config import config_path_for_filename, load_config
from chia.util.keychain import Keychain
from chia.util.path import mkdir
from chia.wallet.derive_keys import master_sk_to_farmer_sk, master_sk_to_local_sk, master_sk_to_pool_sk

log = logging.getLogger(__name__)


class PlotKeys:
    def __init__(
        self,
        farmer_public_key: G1Element,
        pool_public_key: Optional[G1Element],
        pool_contract_address: Optional[str],
    ):
        self.farmer_public_key = farmer_public_key
        self.pool_public_key = pool_public_key
        self.pool_contract_address = pool_contract_address

    @property
    def pool_contract_puzzle_hash(self) -> Optional[bytes32]:
        if self.pool_contract_address is not None:
            return decode_puzzle_hash(self.pool_contract_address)
        return None


class PlotKeysResolver:
    def __init__(
        self,
        farmer_public_key: str,
        alt_fingerprint: int,
        pool_public_key: str,
        pool_contract_address: str,
        root_path: Path,
        log: logging.Logger,
        connect_to_daemon=False,
    ):
        self.farmer_public_key = farmer_public_key
        self.alt_fingerprint = alt_fingerprint
        self.pool_public_key = pool_public_key
        self.pool_contract_address = pool_contract_address
        self.root_path = root_path
        self.log = log
        self.connect_to_daemon = connect_to_daemon
        self.resolved_keys: Optional[PlotKeys] = None

    async def resolve(self) -> PlotKeys:
        if self.resolved_keys is not None:
            return self.resolved_keys

        keychain_proxy: Optional[KeychainProxy] = None
        if self.connect_to_daemon:
            keychain_proxy = await connect_to_keychain_and_validate(self.root_path, self.log)
        else:
            keychain_proxy = wrap_local_keychain(Keychain(), log=self.log)

        farmer_public_key: G1Element
        if self.farmer_public_key is not None:
            farmer_public_key = G1Element.from_bytes(bytes.fromhex(self.farmer_public_key))
        else:
            farmer_public_key = await self.get_farmer_public_key(keychain_proxy)

        pool_public_key: Optional[G1Element] = None
        if self.pool_public_key is not None:
            if self.pool_contract_address is not None:
                raise RuntimeError("Choose one of pool_contract_address and pool_public_key")
            pool_public_key = G1Element.from_bytes(bytes.fromhex(self.pool_public_key))
        else:
            if self.pool_contract_address is None:
                # If nothing is set, farms to the provided key (or the first key)
                pool_public_key = await self.get_pool_public_key(keychain_proxy)

        self.resolved_keys = PlotKeys(farmer_public_key, pool_public_key, self.pool_contract_address)
        return self.resolved_keys

    async def get_sk(self, keychain_proxy: Optional[KeychainProxy] = None) -> Optional[Tuple[PrivateKey, bytes]]:
        sk: Optional[PrivateKey] = None
        if keychain_proxy:
            try:
                if self.alt_fingerprint is not None:
                    sk = await keychain_proxy.get_key_for_fingerprint(self.alt_fingerprint)
                else:
                    sk = await keychain_proxy.get_first_private_key()
            except Exception as e:
                log.error(f"Keychain proxy failed with error: {e}")
        else:
            sk_ent: Optional[Tuple[PrivateKey, bytes]] = None
            keychain: Keychain = Keychain()
            if self.alt_fingerprint is not None:
                sk_ent = keychain.get_private_key_by_fingerprint(self.alt_fingerprint)
            else:
                sk_ent = keychain.get_first_private_key()

            if sk_ent:
                sk = sk_ent[0]
        return sk

    async def get_farmer_public_key(self, keychain_proxy: Optional[KeychainProxy] = None) -> G1Element:
        sk: Optional[PrivateKey] = await self.get_sk(keychain_proxy)
        if sk is None:
            raise RuntimeError(
                "No keys, please run 'sit keys add', 'sit keys generate' or provide a public key with -f"
            )
        return master_sk_to_farmer_sk(sk).get_g1()

    async def get_pool_public_key(self, keychain_proxy: Optional[KeychainProxy] = None) -> G1Element:
        sk: Optional[PrivateKey] = await self.get_sk(keychain_proxy)
        if sk is None:
            raise RuntimeError(
                "No keys, please run 'sit keys add', 'sit keys generate' or provide a public key with -p"
            )
        return master_sk_to_pool_sk(sk).get_g1()


async def resolve_plot_keys(
    farmer_public_key: str,
    alt_fingerprint: int,
    pool_public_key: str,
    pool_contract_address: str,
    root_path: Path,
    log: logging.Logger,
    connect_to_daemon=False,
) -> PlotKeys:
    return await PlotKeysResolver(
        farmer_public_key, alt_fingerprint, pool_public_key, pool_contract_address, root_path, log, connect_to_daemon
    ).resolve()


async def create_plots(
    args, keys: PlotKeys, root_path, use_datetime=True, test_private_keys: Optional[List] = None
) -> Tuple[Dict[bytes32, Path], Dict[bytes32, Path]]:

    config_filename = config_path_for_filename(root_path, "config.yaml")
    config = load_config(root_path, config_filename)

    if args.tmp2_dir is None:
        args.tmp2_dir = args.tmp_dir

    assert (keys.pool_public_key is None) != (keys.pool_contract_puzzle_hash is None)
    num = args.num

    if args.size < config["min_mainnet_k_size"] and test_private_keys is None:
        log.warning(f"Creating plots with size k={args.size}, which is less than the minimum required for mainnet")
    if args.size < 22:
        log.warning("k under 22 is not supported. Increasing k to 22")
        args.size = 22

    if keys.pool_public_key is not None:
        log.info(
            f"Creating {num} plots of size {args.size}, pool public key:  "
            f"{bytes(keys.pool_public_key).hex()} farmer public key: {bytes(keys.farmer_public_key).hex()}"
        )
    else:
        assert keys.pool_contract_puzzle_hash is not None
        log.info(
            f"Creating {num} plots of size {args.size}, pool contract address:  "
            f"{keys.pool_contract_address} farmer public key: {bytes(keys.farmer_public_key).hex()}"
        )

    tmp_dir_created = False
    if not args.tmp_dir.exists():
        mkdir(args.tmp_dir)
        tmp_dir_created = True

    tmp2_dir_created = False
    if not args.tmp2_dir.exists():
        mkdir(args.tmp2_dir)
        tmp2_dir_created = True

    mkdir(args.final_dir)

    created_plots: Dict[bytes32, Path] = {}
    existing_plots: Dict[bytes32, Path] = {}
    for i in range(num):
        # Generate a random master secret key
        if test_private_keys is not None:
            assert len(test_private_keys) == num
            sk: PrivateKey = test_private_keys[i]
        else:
            sk = AugSchemeMPL.key_gen(token_bytes(32))

        # The plot public key is the combination of the harvester and farmer keys
        # New plots will also include a taproot of the keys, for extensibility
        include_taproot: bool = keys.pool_contract_puzzle_hash is not None
        plot_public_key = ProofOfSpace.generate_plot_public_key(
            master_sk_to_local_sk(sk).get_g1(), keys.farmer_public_key, include_taproot
        )

        # The plot id is based on the harvester, farmer, and pool keys
        if keys.pool_public_key is not None:
            plot_id: bytes32 = ProofOfSpace.calculate_plot_id_pk(keys.pool_public_key, plot_public_key)
            plot_memo: bytes32 = stream_plot_info_pk(keys.pool_public_key, keys.farmer_public_key, sk)
        else:
            assert keys.pool_contract_puzzle_hash is not None
            plot_id = ProofOfSpace.calculate_plot_id_ph(keys.pool_contract_puzzle_hash, plot_public_key)
            plot_memo = stream_plot_info_ph(keys.pool_contract_puzzle_hash, keys.farmer_public_key, sk)

        if args.plotid is not None:
            log.info(f"Debug plot ID: {args.plotid}")
            plot_id = bytes32(bytes.fromhex(args.plotid))

        if args.memo is not None:
            log.info(f"Debug memo: {args.memo}")
            plot_memo = bytes.fromhex(args.memo)

        # Uncomment next two lines if memo is needed for dev debug
        plot_memo_str: str = plot_memo.hex()
        log.info(f"Memo: {plot_memo_str}")

        dt_string = datetime.now().strftime("%Y-%m-%d-%H-%M")

        if use_datetime:
            filename: str = f"plot-k{args.size}-{dt_string}-{plot_id}.plot"
        else:
            filename = f"plot-k{args.size}-{plot_id}.plot"
        full_path: Path = args.final_dir / filename

        resolved_final_dir: str = str(Path(args.final_dir).resolve())
        plot_directories_list: str = config["harvester"]["plot_directories"]

        if args.exclude_final_dir:
            log.info(f"NOT adding directory {resolved_final_dir} to harvester for farming")
            if resolved_final_dir in plot_directories_list:
                log.warning(f"Directory {resolved_final_dir} already exists for harvester, please remove it manually")
        else:
            if resolved_final_dir not in plot_directories_list:
                # Adds the directory to the plot directories if it is not present
                log.info(f"Adding directory {resolved_final_dir} to harvester for farming")
                config = add_plot_directory(root_path, resolved_final_dir)

        if not full_path.exists():
            log.info(f"Starting plot {i + 1}/{num}")
            # Creates the plot. This will take a long time for larger plots.
            plotter: DiskPlotter = DiskPlotter()
            plotter.create_plot_disk(
                str(args.tmp_dir),
                str(args.tmp2_dir),
                str(args.final_dir),
                filename,
                args.size,
                plot_memo,
                plot_id,
                args.buffer,
                args.buckets,
                args.stripe_size,
                args.num_threads,
                args.nobitfield,
            )
            created_plots[plot_id] = full_path
        else:
            log.info(f"Plot {filename} already exists")
            existing_plots[plot_id] = full_path

    log.info("Summary:")

    if tmp_dir_created:
        try:
            args.tmp_dir.rmdir()
        except Exception:
            log.info(f"warning: did not remove primary temporary folder {args.tmp_dir}, it may not be empty.")

    if tmp2_dir_created:
        try:
            args.tmp2_dir.rmdir()
        except Exception:
            log.info(f"warning: did not remove secondary temporary folder {args.tmp2_dir}, it may not be empty.")

    log.info(f"Created a total of {len(created_plots)} new plots")
    for created_path in created_plots.values():
        log.info(created_path.name)

    return created_plots, existing_plots
