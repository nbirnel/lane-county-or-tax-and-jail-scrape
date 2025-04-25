"""
Helper functions for scraping Lane County, OR informational pages.
"""

import argparse
import csv
from functools import wraps
import logging
import os
import re
from time import sleep


def retry(times_to_retry=5):
    """
    Decorate a function to retry.
    Back off by number of retries cubed seconds each time,
    eg: 1, 8, 27, 64...
    """

    def decorate(func):
        @wraps(func)
        def wrapper(*args, n_tries=0, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as err:
                if (n_tries := n_tries + 1) > times_to_retry:
                    logging.error(
                        "%s failed after %d tries with args %s and kwargs %s",
                        func.__name__,
                        times_to_retry,
                        args,
                        kwargs,
                    )
                    raise
                logging.warning(
                    "%s: error %s: will sleep %d seconds before retry %d",
                    func.__name__,
                    err,
                    sleep_duration := n_tries**3,
                    n_tries,
                )
                sleep(sleep_duration)
                return wrapper(*args, n_tries=n_tries, **kwargs)

        return wrapper

    return decorate


def configure_logging(filename, level="WARN"):
    """
    Accept filename (file-like object),
    optional level (str, default WARN).
    Configure logging.
    """
    numeric_level = getattr(logging, level.upper())

    logging.basicConfig(
        filename=filename,
        format="%(asctime)s %(levelname)-8s %(message)s",
        level=numeric_level,
        datefmt="%Y%m%dT%H:%M:%S",
    )


def strip(text: str) -> str:
    """
    Accept text.
    Return with extra whitespace removed.
    """
    return re.sub(r"\s+", " ", text.strip())


def write_csv(output, rows: iter, dest=""):
    """
    Accept output, rows (iter of dicts).
    Write or append to a csv.
    """
    if not rows:
        return
    fieldnames = rows[0].keys()
    if not fieldnames:
        return
    logging.debug("writing %d lines to %s", len(rows), output)
    if dest:
        os.makedirs(dest, exist_ok=True)
        output = os.path.join(dest, output)
    with open(output, "a", encoding="utf8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if os.stat(output).st_size == 0:
            writer.writeheader()
        writer.writerows(rows)


def get_parser(*args, **kwargs) -> argparse.ArgumentParser:
    """
    Accept args (a list of arguments to insert before universal args),
    and kwargs.
    """
    log = kwargs.get("log", "lcapp.log")
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    for arg in args:
        parser.add_argument(*arg["args"], **arg["kwargs"])
    parser.add_argument(
        "-l",
        "--log",
        help="""
            File to log to.
            """,
        default=log,
    )
    parser.add_argument(
        "-L",
        "--log-level",
        help="""
            Log level. 
            """,
        default="INFO",
        choices=["NOTSET", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    parser.add_argument(
        "-d",
        "--dry-run",
        help="""
            Do not scrape; merely print what would be scraped.
            """,
        action="store_true",
    )
    parser.add_argument(
        "-H",
        "--no-headless",
        help="""
            Do not run headless.
            """,
        action="store_true",
    )
    return parser


def load_file(read) -> list:
    """
    Accept read (file to be read).
    Return as a list of stripped non-empty lines.
    """
    logging.info("reading %s", read)
    with open(read, "r", encoding="utf8") as source:
        return [line.strip() for line in source if line.strip()]


def log_name(script):
    """
    Accept script (path).
    Return the basename, with the file extension changed to ".log".
    """
    basename = os.path.basename(script)
    return f"{os.path.splitext(basename)[0]}.log"
