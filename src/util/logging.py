import logging
import colorlog


def initialize_logging(prefix):
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
    logger.setLevel(logging.INFO)
