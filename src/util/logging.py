import logging
import colorlog
from typing import Dict

from src.path import mkdir, path_from_root


def initialize_logging(prefix: str, logging_config: Dict):
    log_path = path_from_root("log") / "debug.log"
    mkdir(log_path.parent)
    if logging_config["log_stdout"]:
        handler = colorlog.StreamHandler()
        handler.setFormatter(
            colorlog.ColoredFormatter(
                f"{prefix}: %(log_color)s%(levelname)-8s%(reset)s %(asctime)s.%(msecs)03d %(message)s",
                datefmt="%H:%M:%S",
                reset=True,
            )
        )

        logger = colorlog.getLogger()
        logger.addHandler(handler)
    else:
        print(
            f"Starting process and logging to {log_path}. Run with & to run in the background."
        )
        logging.basicConfig(
            filename=log_path,
            filemode="a",
            format=f"{prefix}: %(levelname)-8s %(asctime)s.%(msecs)03d %(message)s",
            datefmt="%H:%M:%S",
        )
        logger = logging.getLogger()
    logger.setLevel(logging.INFO)
