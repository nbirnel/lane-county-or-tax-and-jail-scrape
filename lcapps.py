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


def write_csv(output, rows: iter):
    """
    Accept output, rows (iter of dicts).
    Write or append to a csv.
    """
    if not rows:
        return
    fieldnames = rows[0].keys()
    with open(output, "a", encoding="utf8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if os.stat(output).st_size == 0:
            writer.writeheader()
        writer.writerows(rows)
