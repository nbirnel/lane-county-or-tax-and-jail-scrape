import argparse
from decimal import Decimal
from itertools import dropwhile
import logging

from playwright.sync_api import (
    Playwright,
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

from lcapps import strip, write_csv, configure_logging, get_parser, log_name


def address_2(address: str) -> tuple:
    """
    Accept address.
    Return as a tuple of non-empty lines, with extra whitespace removed.
    """
    return tuple(elem.strip() for elem in address.split("\n") if elem.strip())


def address_4(address: str) -> tuple:
    """
    Accept address.
    Return as a tuple of lines, with extra whitespace removed.
    Discard empty lines at beginning and end.
    """

    def dropunless_and_reverse(iterable) -> list:
        return list(reversed(list(dropwhile(lambda x: not x, iterable))))

    lines = [elem.strip() for elem in address.split("\n")]
    return dropunless_and_reverse(dropunless_and_reverse(lines))


def money(dollars: str) -> Decimal:
    """
    Accept dollars (str).
    Return as a 100th precision Decimal.
    """
    cleaned = dollars.strip().lstrip("$").replace(",", "")
    return Decimal(cleaned).quantize(Decimal("1.00"))


def get_account_row(rows, idx: int, cleaner=strip):
    return cleaner(rows.nth(idx).locator("td").last.text_content())


def get_receipt_entry(row, idx: int, cleaner=strip):
    return cleaner(row.locator("td").nth(idx).text_content())


def get_assessments(rows, idx: int) -> list:
    return [money(td.text_content()) for td in rows[idx].locator("td").all()]


def run(playwright: Playwright, account: str) -> dict:
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
        logging.error("%s: get account link timed out")
        return {}

    account_div = page.locator("div").filter(
        has=page.get_by_text("Account Information")
    )
    rows = account_div.locator("tbody").locator("tr")
    logging.debug("%s: getting account info", account)
    site_address, site_city = get_account_row(rows, 5, cleaner=address_2)
    mailing_address_1, mailing_address_2, mailing_address_3, mailing_city = (
        get_account_row(rows, 6, cleaner=address_4)
    )
    account_information = {
        "account_number": get_account_row(rows, 0),
        "tax_payer": get_account_row(rows, 3),
        "situs_address": site_address,
        "situs_city": site_city,
        "mailing_address_1": mailing_address_1,
        "mailing_address_2": mailing_address_2,
        "mailing_address_3": mailing_address_3,
        "mailing_city": mailing_city,
        "map_and_tax_lot_number": get_account_row(rows, 7),
        "acreage": get_account_row(rows, 8),
        "tca": get_account_row(rows, 9),
        "prop_class": get_account_row(rows, 10),
    }

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
                "amount_received": get_receipt_entry(row, 1, cleaner=money),
                "tax": get_receipt_entry(row, 2, cleaner=money),
                "discount": get_receipt_entry(row, 3, cleaner=money),
                "interest": get_receipt_entry(row, 4, cleaner=money),
            }
            for row in rows
        ]
    except PlaywrightTimeoutError:
        logging.info("%s: no receipts info", account)
        try:
            receipts_table.get_by_text("No records to display").click()
            receipts = []
        except PlaywrightTimeoutError as exc:
            logging.error(
                "%s: Did not see 'No records to display'", account
            )
            raise ValueError("Did not see 'No records to display'") from exc

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

    assessed_values = get_assessments(rows, 0)
    max_assessed_values = get_assessments(rows, 1)
    real_market_values = get_assessments(rows, 2)
    assessments = [
        {
            "account_id": account,
            "year": year,
            "assessed_value": assessed_values[i],
            "max_assessed_value": max_assessed_values[i],
            "real_market_value": real_market_values[i],
        }
        for i, year in enumerate(years)
    ]

    return {
        "account_information": account_information,
        "receipts": receipts,
        "assessments": assessments,
    }


def load_file(read):
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
    ]
    return get_parser(*arguments, log=log)


def main():
    parser = custom_parser()
    args = parser.parse_args()

    configure_logging(args.log, args.log_level)
    read_file = args.read_file
    accounts = args.account
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
                    write_csv(
                        "accounts.csv", (result["account_information"],)
                    )
                    write_csv("receipts.csv", result["receipts"])
                    write_csv("assessments.csv", result["assessments"])


if __name__ == "__main__":
    main()
