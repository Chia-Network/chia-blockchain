
import logging
from logging.handlers import QueueHandler, QueueListener
from queue import Queue


def initialize_logging() -> Queue:
    log_queue: Queue = Queue(-1)
    queue_handler = QueueHandler(log_queue)

    logging.basicConfig(format='FullNode %(name)-23s: %(levelname)-8s %(asctime)s.%(msecs)03d %(message)s',
                        level=logging.INFO,
                        datefmt='%H:%M:%S'
                        )
    main_logger = logging.getLogger()
    main_logger.handlers = []
    main_logger.addHandler(queue_handler)
    listener = QueueListener(log_queue)
    listener.start()
    return log_queue
