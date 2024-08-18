import argparse
import csv
import logging
import os
import re


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
    logging.debug("writing %d lines to %s", len(rows), output)
    fieldnames = rows[0].keys()
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


def log_name(script):
    """
    Accept script (path).
    Return the basename, with the file extension changed to ".log".
    """
    basename = os.path.basename(script)
    return f"{os.path.splitext(basename)[0]}.log"
