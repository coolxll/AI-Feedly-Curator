#!/usr/bin/env python3
import json
import logging
import os
import struct
import sys
import traceback
from logging.handlers import TimedRotatingFileHandler


def setup_native_logging():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.environ.get("RSS_NATIVE_LOG_DIR", os.path.join(current_dir, "logs"))
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception:
            log_dir = current_dir

    log_file = os.path.join(log_dir, "native_host.log")
    level_str = os.environ.get("RSS_NATIVE_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_str, logging.INFO)

    handler = TimedRotatingFileHandler(
        log_file, when="midnight", interval=1, backupCount=7, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for existing in root_logger.handlers[:]:
        root_logger.removeHandler(existing)
    root_logger.addHandler(handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    return log_file


LOG_FILE = setup_native_logging()
logging.info("Native Host starting")

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from rss_analyzer.backend_service import get_runtime_paths, handle_message

    runtime = get_runtime_paths()
    logging.info("Using shared backend service runtime: %s", runtime)
except Exception:
    logging.exception("Failed to import shared backend service")
    sys.exit(1)


def _read_message():
    try:
        raw_length = sys.stdin.buffer.read(4)
        if len(raw_length) == 0:
            return None
        if len(raw_length) != 4:
            logging.error("Invalid length header: %s bytes", len(raw_length))
            return None
        message_length = struct.unpack("<I", raw_length)[0]
        if message_length == 0:
            logging.warning("Message length is 0")
            return None
        message = sys.stdin.buffer.read(message_length)
        if not message:
            logging.error("Failed to read message body")
            return None
        return json.loads(message.decode("utf-8"))
    except Exception:
        logging.exception("Read message exception")
        return None


def _send_message(payload: dict):
    try:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()
    except Exception:
        logging.exception("Send message exception")


def main():
    logging.info("Entering native host loop")
    while True:
        msg = _read_message()
        if msg is None:
            break

        logging.debug("Received message: %s", json.dumps(msg, ensure_ascii=False))

        try:
            response = handle_message(msg)
        except Exception as exc:
            logging.exception("Unhandled backend exception")
            response = {
                "error": "exception",
                "detail": str(exc),
                "trace": traceback.format_exc(limit=3),
            }

        logging.debug("Sending response: %s", json.dumps(response, ensure_ascii=False))
        _send_message(response)


if __name__ == "__main__":
    main()
