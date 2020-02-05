import logging
import colorlog
from typing import Dict


def initialize_logging(prefix: str, logging_config: Dict):
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
            f"Starting process and logging to {logging_config['log_filename']}. Run with & to run in the background."
        )
        logging.basicConfig(
            filename=logging_config["log_filename"],
            filemode="a",
            format=f"{prefix}: %(levelname)-8s %(asctime)s.%(msecs)03d %(message)s",
            datefmt="%H:%M:%S",
        )
        logger = logging.getLogger()
    logger.setLevel(logging.INFO)
