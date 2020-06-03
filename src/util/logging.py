import logging
import colorlog

from pathlib import Path
from typing import Dict

from src.util.path import mkdir, path_from_root
from logging.handlers import RotatingFileHandler


def initialize_logging(prefix: str, logging_config: Dict, root_path: Path):
    log_path = path_from_root(
        root_path, logging_config.get("log_filename", "log/debug.log")
    )
    mkdir(str(log_path.parent))
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
        logging.basicConfig(
            filename=log_path,
            filemode="a",
            format=f"{prefix}: %(levelname)-8s %(asctime)s.%(msecs)03d %(message)s",
            datefmt="%H:%M:%S",
        )

        logger = logging.getLogger()
        handler = RotatingFileHandler(log_path, maxBytes=20000000, backupCount=7)
        logger.addHandler(handler)

    logger.setLevel(logging.INFO)
