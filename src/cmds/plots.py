from pathlib import Path
from secrets import token_bytes
import logging
from chiapos import Verifier
from collections import Counter
from blspy import PrivateKey, PublicKey
from chiapos import DiskPlotter
from datetime import datetime
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.keychain import Keychain
from src.util.config import config_path_for_filename, load_config, save_config
from src.util.path import mkdir
from src.util.plot_tools import get_plot_filenames, stream_plot_info, load_plots
from src.util.hash import std_hash
from src.util.logging import initialize_logging


log = logging.getLogger(__name__)


def get_default_public_key() -> PublicKey:
    keychain: Keychain = Keychain()
    epk = keychain.get_first_public_key()
    if epk is None:
        raise RuntimeError(
            "No keys, please run 'chia keys generate' or provide a public key with -f"
        )
    return PublicKey.from_bytes(bytes(epk.public_child(0).get_public_key()))


command_list = [
    "create",
    "check",
    "add",
]


def help_message():
    print("usage: chia plots command")
    print(f"command can be any of {command_list}")
    print("")
    print(
        f"chia plots create -k [size] -n [number of plots] -s [sk_seed] -i [index] -b [memory buffer size]"
        f" -f [farmer pk] -p [pool pk] -t [tmp dir] -2 [tmp dir 2] -d [final dir]  (creates plots)"
    )
    print("chia plots check -n [num checks]  (checks plots)")
    print("chia plots add -d [directory] (adds a directory of plots)")


def make_parser(parser):
    parser.add_argument("-k", "--size", help="Plot size", type=int, default=26)
    parser.add_argument(
        "-n", "--num", help="Number of plots or challenges", type=int, default=None
    )
    parser.add_argument(
        "-i", "--index", help="First plot index", type=int, default=None
    )
    parser.add_argument(
        "-b", "--buffer", help="Megabytes for sort/plot buffer", type=int, default=2048
    )
    parser.add_argument(
        "-f",
        "--farmer_public_key",
        help="Hex farmer public key",
        type=str,
        default=None,
    )
    parser.add_argument(
        "-p", "--pool_public_key", help="Hex public key of pool", type=str, default=None
    )
    parser.add_argument(
        "-s", "--sk_seed", help="Secret key seed in hex", type=str, default=None
    )
    parser.add_argument(
        "-t",
        "--tmp_dir",
        help="Temporary directory for plotting files",
        type=Path,
        default=Path("."),
    )
    parser.add_argument(
        "-2",
        "--tmp2_dir",
        help="Second temporary directory for plotting files",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "-d",
        "--final_dir",
        help="Final directory for plots (relative or absolute)",
        type=Path,
        default=Path("."),
    )
    parser.add_argument(
        "command",
        help=f"Command can be any one of {command_list}",
        type=str,
        nargs="?",
    )

    parser.set_defaults(function=handler)
    parser.print_help = lambda self=parser: help_message()


def create_plots(args, root_path):
    initialize_logging("", {"log_stdout": True}, root_path)
    config_filename = config_path_for_filename(root_path, "config.yaml")

    if args.sk_seed is None and args.index is not None:
        log.info(
            "You have specified the -i (index) argument without the -s (sk_seed) argument."
            " The program has changes, so that the sk_seed is now generated randomly, so -i is no longer necessary."
            " Please run the program without -i."
        )
        quit()
    if args.tmp2_dir is None:
        args.tmp2_dir = args.final_dir

    if args.index is None:
        args.index = 0

    # The seed is what will be used to generate a private key for each plot
    if args.sk_seed is not None:
        sk_seed: bytes = bytes.fromhex(args.sk_seed)
        log.info(f"Using the provided sk_seed {sk_seed.hex()}.")
    else:
        sk_seed = token_bytes(32)
        log.info(
            f"Using sk_seed {sk_seed.hex()}. Note that sk seed is now generated randomly. "
            f"If you want to use a specific seed, use the -s argument."
        )

    farmer_public_key: PublicKey
    if args.farmer_public_key is not None:
        farmer_public_key = PublicKey.from_bytes(bytes.fromhex(args.farmer_public_key))
    else:
        farmer_public_key = get_default_public_key()

    pool_public_key: PublicKey
    if args.pool_public_key is not None:
        pool_public_key = bytes.fromhex(args.pool_public_key)
    else:
        pool_public_key = get_default_public_key()
    if args.num is not None:
        num = args.num
    else:
        num = 1
    log.info(
        f"Creating {num} plots, from index {args.index} to "
        f"{args.index + num - 1}, of size {args.size}, sk_seed "
        f"{sk_seed.hex()} pool public key "
        f"{bytes(pool_public_key).hex()} farmer public key {bytes(farmer_public_key).hex()}"
    )

    mkdir(args.tmp_dir)
    mkdir(args.tmp2_dir)
    mkdir(args.final_dir)
    finished_filenames = []
    for i in range(args.index, args.index + num):
        # Generate a sk based on the seed, plot size (k), and index
        sk: PrivateKey = PrivateKey.from_seed(
            sk_seed + args.size.to_bytes(1, "big") + i.to_bytes(4, "big")
        )

        # The plot public key is the combination of the harvester and farmer keys
        plot_public_key = ProofOfSpace.generate_plot_public_key(
            sk.get_public_key(), farmer_public_key
        )

        # The plot seed is based on the harvester, farmer, and pool keys
        plot_seed: bytes32 = ProofOfSpace.calculate_plot_seed(
            pool_public_key, plot_public_key
        )
        dt_string = datetime.now().strftime("%Y-%m-%d-%H-%M")

        filename: str = f"plot-k{args.size}-{dt_string}-{plot_seed}.plot"
        full_path: Path = args.final_dir / filename

        config = load_config(root_path, config_filename)
        plot_filenames = get_plot_filenames(config["harvester"])
        if args.final_dir.resolve() not in plot_filenames:
            # Adds the directory to the plot directories if it is not present
            config["harvester"]["plot_directories"].append(
                str(args.final_dir.resolve())
            )
            save_config(root_path, config_filename, config)

        if not full_path.exists():
            # Creates the plot. This will take a long time for larger plots.
            plotter: DiskPlotter = DiskPlotter()
            plotter.create_plot_disk(
                str(args.tmp_dir),
                str(args.tmp2_dir),
                str(args.final_dir),
                filename,
                args.size,
                stream_plot_info(pool_public_key, farmer_public_key, sk),
                plot_seed,
                args.buffer,
            )
            finished_filenames.append(filename)
        else:
            log.info(f"Plot {filename} already exists")

    log.info("Summary:")
    try:
        args.tmp_dir.rmdir()
    except Exception:
        log.info(
            f"warning: did not remove primary temporary folder {args.tmp_dir}, it may not be empty."
        )
    try:
        args.tmp2_dir.rmdir()
    except Exception:
        log.info(
            f"warning: did not remove secondary temporary folder {args.tmp2_dir}, it may not be empty."
        )
    log.info(f"Created a total of {len(finished_filenames)} new plots")
    for filename in finished_filenames:
        log.info(filename)


def check_plots(args, root_path):
    initialize_logging("", {"log_stdout": True}, root_path)
    config = load_config(root_path, "config.yaml")
    if args.num is not None:
        num = args.num
    else:
        num = 20

    v = Verifier()
    log.info("Loading plots in config.yaml using plot_tools loading code\n")
    kc: Keychain = Keychain()
    pks = [epk.public_child(0).get_public_key() for epk in kc.get_all_public_keys()]
    pool_public_keys = [
        PublicKey.from_bytes(bytes.fromhex(pk))
        for pk in config["farmer"]["pool_public_keys"]
    ]
    _, provers, failed_to_open_filenames, no_key_filenames = load_plots(
        {}, pks, pool_public_keys, root_path, open_no_key_filenames=True,
    )
    if len(provers) > 0:
        log.info("")
        log.info("")
        log.info(f"Starting to test each plot with {num} challenges each\n")
    total_good_plots: Counter = Counter()
    total_bad_plots = 0
    total_size = 0

    for plot_path, plot_info in provers.items():
        pr = plot_info.prover
        log.info(f"Testing plot {plot_path} k={pr.get_size()}")
        log.info(f"\tPool public key: {plot_info.pool_public_key}")
        log.info(f"\tFarmer public key: {plot_info.farmer_public_key}")
        log.info(f"\tHarvester sk: {plot_info.harvester_sk}")
        total_proofs = 0
        try:
            for i in range(num):
                challenge = std_hash(i.to_bytes(32, "big"))
                for index, quality_str in enumerate(
                    pr.get_qualities_for_challenge(challenge)
                ):
                    proof = pr.get_full_proof(challenge, index)
                    total_proofs += 1
                    ver_quality_str = v.validate_proof(
                        pr.get_id(), pr.get_size(), challenge, proof
                    )
                    assert quality_str == ver_quality_str
        except BaseException as e:
            if isinstance(e, KeyboardInterrupt):
                log.warning("Interrupted, closing")
                return
            log.error(f"{type(e)}: {e} error in proving/verifying for plot {plot_path}")
        if total_proofs > 0:
            log.info(
                f"\tProofs {total_proofs} / {num}, {round(total_proofs/float(num), 4)}"
            )
            total_good_plots[pr.get_size()] += 1
            total_size += plot_path.stat().st_size
        else:
            total_bad_plots += 1
            log.error(
                f"\tProofs {total_proofs} / {num}, {round(total_proofs/float(num), 4)}"
            )
    log.info("")
    log.info("")
    log.info("Summary")
    total_plots: int = sum(list(total_good_plots.values()))
    log.info(
        f"Found {total_plots} valid plots, total size {total_size / (1024 * 1024 * 1024 * 1024)} TB"
    )
    for (k, count) in sorted(dict(total_good_plots).items()):
        log.info(f"{count} plots of size {k}")
    grand_total_bad = total_bad_plots + len(failed_to_open_filenames)
    if grand_total_bad > 0:
        log.warning(f"{grand_total_bad} invalid plots")
    if len(no_key_filenames) > 0:
        log.warning(
            f"There are {len(no_key_filenames)} plots with a farmer or pool public key that "
            f"is not on this machine. The farmer private key must be in the keychain in order to "
            f"farm them, use 'chia keys' to transfer keys. The pool public keys must be in the config.yaml"
        )
    pass


def add_plot_directory(args, root_path):
    str_path = args.final_dir
    config = load_config(root_path, "config.yaml")
    if str(Path(str_path).resolve()) not in config["harvester"]["plot_directories"]:
        config["harvester"]["plot_directories"].append(str(Path(str_path).resolve()))
    save_config(root_path, "config.yaml", config)


def handler(args, parser):
    if args.command is None or len(args.command) < 1:
        help_message()
        parser.exit(1)

    root_path: Path = args.root_path
    if not root_path.is_dir():
        raise RuntimeError(
            "Please initialize (or migrate) your config directory with chia init."
        )

    command = args.command
    if command not in command_list:
        help_message()
        parser.exit(1)

    if command == "create":
        create_plots(args, root_path)
    elif command == "check":
        check_plots(args, root_path)
    elif command == "add":
        add_plot_directory(args, root_path)
