from pathlib import Path
from secrets import token_bytes
from typing import Optional, List, Tuple
import logging
from blspy import AugSchemeMPL, G1Element, PrivateKey
from chiapos import DiskPlotter
from datetime import datetime
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.keychain import Keychain
from src.util.config import config_path_for_filename, load_config
from src.util.path import mkdir
from src.plotting.plot_tools import (
    get_plot_filenames,
    stream_plot_info,
    add_plot_directory,
)
from src.wallet.derive_keys import (
    master_sk_to_farmer_sk,
    master_sk_to_pool_sk,
    master_sk_to_local_sk,
)


log = logging.getLogger(__name__)


def get_farmer_public_key(alt_fingerprint: Optional[int] = None) -> G1Element:
    sk_ent: Optional[Tuple[PrivateKey, bytes]]
    keychain: Keychain = Keychain()
    if alt_fingerprint is not None:
        sk_ent = keychain.get_private_key_by_fingerprint(alt_fingerprint)
    else:
        sk_ent = keychain.get_first_private_key()
    if sk_ent is None:
        raise RuntimeError("No keys, please run 'chia keys add', 'chia keys generate' or provide a public key with -f")
    return master_sk_to_farmer_sk(sk_ent[0]).get_g1()


def get_pool_public_key(alt_fingerprint: Optional[int] = None) -> G1Element:
    sk_ent: Optional[Tuple[PrivateKey, bytes]]
    keychain: Keychain = Keychain()
    if alt_fingerprint is not None:
        sk_ent = keychain.get_private_key_by_fingerprint(alt_fingerprint)
    else:
        sk_ent = keychain.get_first_private_key()
    if sk_ent is None:
        raise RuntimeError("No keys, please run 'chia keys add', 'chia keys generate' or provide a public key with -p")
    return master_sk_to_pool_sk(sk_ent[0]).get_g1()


def create_plots(args, root_path, use_datetime=True, test_private_keys: Optional[List] = None):
    config_filename = config_path_for_filename(root_path, "config.yaml")

    if args.tmp2_dir is None:
        args.tmp2_dir = args.tmp_dir

    farmer_public_key: G1Element
    if args.farmer_public_key is not None:
        farmer_public_key = G1Element.from_bytes(bytes.fromhex(args.farmer_public_key))
    else:
        farmer_public_key = get_farmer_public_key(args.alt_fingerprint)

    pool_public_key: G1Element
    if args.pool_public_key is not None:
        pool_public_key = bytes.fromhex(args.pool_public_key)
    else:
        pool_public_key = get_pool_public_key(args.alt_fingerprint)
    if args.num is not None:
        num = args.num
    else:
        num = 1
    log.info(
        f"Creating {num} plots of size {args.size}, pool public key:  "
        f"{bytes(pool_public_key).hex()} farmer public key: {bytes(farmer_public_key).hex()}"
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

    finished_filenames = []
    config = load_config(root_path, config_filename)
    plot_filenames = get_plot_filenames(config["harvester"])
    for i in range(num):
        # Generate a random master secret key
        if test_private_keys is not None:
            assert len(test_private_keys) == num
            sk: PrivateKey = test_private_keys[i]
        else:
            sk = AugSchemeMPL.key_gen(token_bytes(32))

        # The plot public key is the combination of the harvester and farmer keys
        plot_public_key = ProofOfSpace.generate_plot_public_key(master_sk_to_local_sk(sk).get_g1(), farmer_public_key)

        # The plot id is based on the harvester, farmer, and pool keys
        plot_id: bytes32 = ProofOfSpace.calculate_plot_id_pk(pool_public_key, plot_public_key)
        if args.plotid is not None:
            log.info(f"Debug plot ID: {args.plotid}")
            plot_id: bytes32 = bytes32(bytes.fromhex(args.plotid))

        plot_memo: bytes32 = stream_plot_info(pool_public_key, farmer_public_key, sk)
        if args.memo is not None:
            log.info(f"Debug memo: {args.memo}")
            plot_memo: bytes32 = bytes.fromhex(args.memo)

        dt_string = datetime.now().strftime("%Y-%m-%d-%H-%M")

        if use_datetime:
            filename: str = f"plot-k{args.size}-{dt_string}-{plot_id}.plot"
        else:
            filename = f"plot-k{args.size}-{plot_id}.plot"
        full_path: Path = args.final_dir / filename

        if args.final_dir.resolve() not in plot_filenames:
            if str(args.final_dir.resolve()) not in config["harvester"]["plot_directories"]:
                # Adds the directory to the plot directories if it is not present
                config = add_plot_directory(str(args.final_dir.resolve()), root_path)

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
            finished_filenames.append(filename)
        else:
            log.info(f"Plot {filename} already exists")

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

    log.info(f"Created a total of {len(finished_filenames)} new plots")
    for filename in finished_filenames:
        log.info(filename)
