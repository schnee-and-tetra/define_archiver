import atexit
import logging
import os
import queue
import threading
from datetime import datetime
from logging.handlers import QueueHandler, QueueListener
from zoneinfo import ZoneInfo

# Global lock to prevent race conditions during logger initialization.
_logger_lock = threading.Lock()

# Registry to keep track of active QueueListeners and prevent garbage collection.
_listeners: dict[str, QueueListener] = {}


class JSTFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(
            record.created,
            tz=ZoneInfo("Asia/Tokyo"),
        )
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat(timespec="milliseconds")


def get_plugin_logger(
    name: str = __name__,
    level: int = logging.INFO,
    queue_size: int = 1000,
) -> logging.Logger:
    """Gets or creates a thread-safe/async-safe logger for Dify plugins.

    This function configures a logger that uses a non-blocking QueueHandler to Avoid
    concurrency issues (such as gevent/greenlet deadlocks) in asynchronous environments.
    It ensures that only one QueueListener is created per logger name and prevents
    duplicate log outputs by disabling log propagation.

    Args:
        name: The name of the logger. Defaults to `__name__`.
        level: The logging level (e.g., logging.INFO). Defaults to logging.INFO.
        queue_size: The maximum number of log records the queue can hold.
            Defaults to 1000.

    Returns:
        logging.Logger: A configured logger instance equipped with a QueueHandler.
    """
    logger = logging.getLogger(name)

    # Prevent race conditions during initialization
    with _logger_lock:
        if not logger.handlers:
            logger.setLevel(level)
            logger.propagate = False

            log_queue: queue.Queue = queue.Queue(maxsize=queue_size)

            formatter = JSTFormatter(
                "[%(asctime)s] "
                "[%(levelname)s] "
                "[%(threadName)s] "
                "[%(name)s] "
                "[%(filename)s:%(lineno)d] "
                "%(message)s"
            )

            handlers = []

            log_dir = "/tmp/define_archiver/logs"
            os.makedirs(log_dir, exist_ok=True)

            safe_name = name.replace(":", "_").replace("/", "_")
            log_file = os.path.join(log_dir, f"{safe_name}.log")

            file_handler = logging.FileHandler(
                log_file,
                encoding="utf-8",
                mode="a",
            )
            file_handler.setFormatter(formatter)

            handlers.append(file_handler)

            listener = QueueListener(
                log_queue,
                *handlers,
                respect_handler_level=True,
            )
            listener.start()

            logger.addHandler(QueueHandler(log_queue))

            # Retain the listener reference to prevent unexpected garbage collection
            _listeners[name] = listener

    return logger


def shutdown_plugin_loggers() -> None:
    """Stops all active QueueListeners and flushes remaining logs.

    This function should be called when the plugin process terminates to ensure
    all background logging threads are cleanly stopped and resources are released.
    """
    with _logger_lock:
        for listener in _listeners.values():
            listener.stop()
        _listeners.clear()


# Register the shutdown handler to run automatically upon process exit.
atexit.register(shutdown_plugin_loggers)
