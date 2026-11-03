"""Shared process lock and bounded standard logging."""

import fcntl
import logging
import os
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler


@contextmanager
def process_lock(paths):
    paths.db.parent.mkdir(parents=True, exist_ok=True)
    with (paths.db.parent / "batch.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("別の収集・生成・配信処理が実行中です") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class SecretFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        key = os.environ.get("SARASHINA_API_KEY")
        if key:
            message = message.replace(key, "[REDACTED]")
        record.msg, record.args = message, ()
        return True


def configure_logging(paths, verbose=False):
    paths.logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    logger = logging.getLogger("literature_digest")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    handler = RotatingFileHandler(
        paths.logs / "literature-digest.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(SecretFilter())
    logger.addHandler(handler)
    return logger
