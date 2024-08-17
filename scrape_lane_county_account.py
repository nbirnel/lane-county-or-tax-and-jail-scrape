"""
Scrape account information from
https://apps.lanecounty.org/PropertyAccountInformation/
"""

import argparse
from decimal import Decimal
from itertools import dropwhile
import logging
import re
from time import sleep

from playwright.sync_api import (
    Playwright,
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

from lcapps import strip, write_csv, configure_logging, get_parser, log_name


def clean_address_2(address: str) -> tuple:
    """
    Accept 2 line situs address.
    Return as a tuple of non-empty lines, with extra whitespace removed.
    """
    return tuple(elem.strip() for elem in address.split("\n") if elem.strip())


def clean_address_4(address: str) -> tuple:
    """
    Accept 4 line mailing address.
    Return as a tuple of lines, with extra whitespace removed.
    Discard empty lines at beginning and end.
    """

    def dropunless_and_reverse(iterable) -> list:
        return list(reversed(list(dropwhile(lambda x: not x, iterable))))

    lines = [elem.strip() for elem in address.split("\n")]
    return dropunless_and_reverse(dropunless_and_reverse(lines))


def clean_more(entry: str) -> str:
    """
    "Located on" and "Related to" fields have "More..." appended to them.
    Accept entry, and return it with "More..." removed
    """
    return strip(entry).removesuffix("More...").strip()


def clean_money(dollars: str) -> Decimal:
    """
    Accept dollars (str).
    Return as a 100th precision Decimal.
    """
    prestripped = dollars.strip()
    # negative amounts are represented with parentheses around them:
    # -$12.01 is ($12.01)
    m = re.match(r"\((\$[0-9.]+)\)", prestripped)
    if m:
        prestripped = m.groups[0]
        sign = -1
    else:
        sign = 1

    cleaned = prestripped.strip().lstrip("$").replace(",", "")
    return Decimal(cleaned).quantize(Decimal("1.00")) * sign


def get_account_row(rows, label: str, cleaner=strip):
    """
    Accept rows, label, optional cleaner (default strip).
    Return cleaned text from the last element of row starting with label.
    """
    try:
        return cleaner(
            rows.filter(has_text=label).locator("td").last.text_content()
        )
    except PlaywrightTimeoutError:
        return ""


def get_account_info(page, account) -> dict:
    """
    Accept page, account.
    Return a dict of account information from that page.
    """
    logging.debug("%s: getting account info", account)
    account_div = page.locator("div").filter(
        has=page.get_by_text("Account Information")
    )
    rows = account_div.locator("tbody").locator("tr")
    # This failed on 0173839
    site_address, site_city = get_account_row(
        rows, "Situs Address", cleaner=clean_address_2
    )
    mailing_address_1, mailing_address_2, mailing_address_3, mailing_city = (
        get_account_row(rows, "Mailing Address", cleaner=clean_address_4)
    )
    logging.debug("%s: got account info", account)
    return {
        "account_number": get_account_row(rows, "Account Number"),
        "related_to_accounts": get_account_row(
            rows, "Related to Account(s)", cleaner=clean_more
        ),
        "located_on_account": get_account_row(
            rows, "Located on Account", cleaner=clean_more
        ),
        "tax_payer": get_account_row(rows, "Tax Payer"),
        "situs_address": site_address,
        "situs_city": site_city,
        "mailing_address_1": mailing_address_1,
        "mailing_address_2": mailing_address_2,
        "mailing_address_3": mailing_address_3,
        "mailing_city": mailing_city,
        "map_and_tax_lot_number": get_account_row(rows, "Map and Tax Lot #"),
        "acreage": get_account_row(rows, "Acreage"),
        "tca": get_account_row(rows, "TCA"),
        "prop_class": get_account_row(rows, "Prop Class"),
    }


def get_receipt_entry(row, idx: int, cleaner=strip):
    """
    Accept row, idx (int), optional cleaner (default strip).
    Return cleaned text from the index idx of row.
    """
    return cleaner(row.locator("td").nth(idx).text_content())


def get_receipts(page, account) -> list:
    """
    Accept page, account.
    Return list of dicts of receipt information from page.
    """
    logging.debug("%s: getting receipts", account)
    receipts_table = page.locator("table").filter(
        has=page.get_by_text("Amount Received")
    )
    # Some accounts have
    try:
        rows = receipts_table.locator("tbody").locator("tr").all()
        receipts = [
            {
                "account_number": account,
                "date": get_receipt_entry(row, 0),
                "amount_received": get_receipt_entry(
                    row, 1, cleaner=clean_money
                ),
                "tax": get_receipt_entry(row, 2, cleaner=clean_money),
                "discount": get_receipt_entry(row, 3, cleaner=clean_money),
                "interest": get_receipt_entry(row, 4, cleaner=clean_money),
            }
            for row in rows
        ]
    except PlaywrightTimeoutError:
        logging.info("%s: no receipts info", account)
        try:
            receipts_table.get_by_text("No records to display").click()
            receipts = []
        except PlaywrightTimeoutError as exc:
            logging.error("%s: Did not see 'No records to display'", account)
            raise ValueError("Did not see 'No records to display'") from exc
    logging.debug("%s: got receipts", account)
    return receipts


def get_assesments_row(rows, idx: int) -> list:
    """
    Accept rows, idx (int).
    Return assesment values for row at index idx.
    """
    return [
        clean_money(td.text_content()) for td in rows[idx].locator("td").all()
    ]


def get_assessments(page, account) -> list:
    """
    Accept page, account.
    Return list of dicts of assessment information from page.
    """
    logging.debug("%s: getting assessments", account)
    assessments_table = (
        page.locator("table")
        .filter(has=page.get_by_text("Assessed Value"))
        .locator("table")
    )
    headers = (
        assessments_table.locator("thead").locator("tr").locator("th").all()
    )
    years = [int(th.text_content()) for th in headers]
    rows = assessments_table.locator("tbody").locator("tr").all()

    try:
        assessed_values = get_assesments_row(rows, 0)
        max_assessed_values = get_assesments_row(rows, 1)
        real_market_values = get_assesments_row(rows, 2)
        logging.debug("%s: got assessments", account)
    except IndexError:
        logging.warning("%s: no assessments", account)
        return []

    return [
        {
            "account_id": account,
            "year": year,
            "assessed_value": assessed_values[i],
            "max_assessed_value": max_assessed_values[i],
            "real_market_value": real_market_values[i],
        }
        for i, year in enumerate(years)
    ]


def run(playwright: Playwright, account: str) -> dict:
    """
    Run playwright against account.
    Return a dict of lists of dicts: accounts, receipts, assessments.
    """
    logging.info("%s: scraping", account)
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    # context.set_default_timeout(100_000)
    page = context.new_page()
    page.goto("https://apps.lanecounty.org/PropertyAccountInformation/")
    page.get_by_placeholder("Enter partial account #").fill(account)
    page.get_by_role("button", name="Save Search").click()
    try:
        page.get_by_role("link", name=account).first.click()
    except PlaywrightTimeoutError:
        logging.error("%s: get account link timed out", account)
        return {}

    account_info = get_account_info(page, account)
    receipts = get_receipts(page, account)
    assessments = get_assessments(page, account)

    logging.info("%s: scraped", account)
    return {
        "accounts": [account_info],
        "receipts": receipts,
        "assessments": assessments,
    }


def load_file(read) -> list:
    """
    Accept read (file to be read).
    Return as a list of stripped non-empty lines.
    """
    logging.info("reading %s", read)
    with open(read, "r", encoding="utf8") as source:
        return [line.strip() for line in source if line.strip()]


def custom_parser() -> argparse.ArgumentParser:
    """
    Return a parser for this script.
    """
    log = log_name(__file__)
    arguments = [
        {
            "args": ["-r", "--read-file"],
            "kwargs": {
                "help": "File to read accounts from.",
            },
        },
        {
            "args": ["-a", "--account"],
            "kwargs": {
                "help": "Account to fetch.",
                "nargs": "*",
            },
        },
        {
            "args": ["-D", "--destination"],
            "kwargs": {
                "help": "Destination directory to place results in.",
                "default": ".",
            },
        },
    ]
    return get_parser(*arguments, log=log)


def main():
    """
    Entry point.
    Parse command line arguments,
    set up logging,
    and loop over items to scrape.
    """
    parser = custom_parser()
    args = parser.parse_args()

    configure_logging(args.log, args.log_level)
    read_file = args.read_file
    accounts = args.account
    dest = args.destination
    if not (accounts or read_file):
        parser.error("we need a read-file or at least one account")

    if not accounts:
        accounts = []
    if read_file:
        accounts += load_file(read_file)

    for account in accounts:
        if args.dry_run:
            print(account)
        else:
            with sync_playwright() as playwright:
                result = run(playwright, account)
                if result:
                    for key, value in result.items():
                        write_csv(f"{key}.csv", value, dest=dest)


if __name__ == "__main__":
    main()
