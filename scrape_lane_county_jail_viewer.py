#!/usr/bin/env python3
"""
Scrape account information from
https://apps.lanecounty.org/PropertyAccountInformation/
"""

from collections import namedtuple
from itertools import chain
import re

from playwright.sync_api import (
    Playwright,
    sync_playwright,
)

from lcapps import (
    argparse,
    configure_logging,
    get_parser,
    log_name,
    logging,
    retry,
    write_csv,
)

INMATE_INFORMATION = "http://inmateinformation.lanecounty.org"
SEARCH_DETAIL = f"{INMATE_INFORMATION}/Home/BookingSearchDetail"
SEARCH_RESULT = f"{INMATE_INFORMATION}/Home/BookingSearchResult"

Filter = namedtuple(
    "Filter",
    ["last_name", "first_name", "booking_begin_date", "booking_end_date"],
)
EMPTY_FILTER = Filter("%", "%", None, None)


def extract_field(
    locator, prefix: str, role="cell", index=None, regex=None
) -> str:
    """
    Accept a Playwright locator,
    a prefix to strip (and by default to search for),
    optional role (default "cell"),
    optional index,
    optional regex (use instead of prefix to search).
    Return the stripped text after the search, at index (or last)
    """
    if regex is None:
        search = prefix
    else:
        search = regex
    located = locator.get_by_role(role, name=search)
    if index is None:
        cell = located.last
    else:
        cell = located.nth(index)
    return cell.text_content().strip().removeprefix(prefix).strip()


def get_charge(tbody, inmate_id, booking_number, index) -> dict:
    """
    Accept tbody (charges table body from BookingSearchDetail),
    inmate_id, booking_number,
    index (which charge to scrape)
    Return a dict of the charge.
    """
    return {
        "booking_number": booking_number,
        "inmate_id": inmate_id,
        "violation": extract_field(tbody, "Violation:", index=index),
        "level": extract_field(tbody, "Level:", index=index),
        "additional_description": extract_field(
            tbody, "Add. Desc.:", index=index
        ),
        "OBTS_number": extract_field(tbody, "OBTS #:", index=index),
        "warrant_number:": extract_field(tbody, "War.#:", index=index),
        "end_of_sentence_date": extract_field(
            tbody, "End Of Sentence Date:", index=index
        ),
        "clearance": extract_field(tbody, "Clearance:", index=index),
        "arrest_agency": extract_field(tbody, "Arrest Agency:", index=index),
        "case_number": extract_field(
            tbody,
            "Case #:",
            regex=re.compile(r"^\s*Case #:"),
            index=index,
        ),
        "arrest_date": extract_field(tbody, "Arrest Date:", index=index),
        "court_type": extract_field(tbody, "Court Type:", index=index),
        "court_case_number": extract_field(
            tbody, "Court Case #:", index=index
        ),
        "next_court_date": extract_field(
            tbody, "Next Court Date", index=index
        ),
        "required_bond_bail": extract_field(
            tbody, "Req. Bond/Bail:", index=index
        ),
        "bond_group_number": extract_field(
            tbody, "Bond Group #:", index=index
        ),
        "required_bond_amount": extract_field(
            tbody, "Req. Bond Amt:", index=index
        ),
        "required_cash_amount": extract_field(
            tbody, "Req. Cash Amt:", index=index
        ),
        "bond_company_number": extract_field(
            tbody, "Bond Co. #:", index=index
        ),
    }


def get_charges(page, inmate_id: str, booking_number: str) -> list:
    """
    Accept page (BookingSearchDetail),
    Return a list of dicts (charges)
    """
    tbody = page.locator("tbody").filter(has_text="Violation: ").first
    charges = tbody.get_by_role("cell", name="Violation:").all()
    logging.debug("found %d charges", len(charges))
    return [
        get_charge(tbody, inmate_id, booking_number, index)
        for index in range(len(charges))
    ]


@retry()
def get_booking(row, context) -> dict:
    """
    Accept row from inmateinformation.lanecounty.org/Home/BookingSearchResult?
    Return a dict of information about the booking.
    """
    booking_id = row.get_by_role("cell").nth(1).text_content().strip()
    first_name = row.get_by_role("cell").nth(2).text_content().strip()
    last_name = row.get_by_role("cell").nth(3).text_content().strip()
    middle_name = row.get_by_role("cell").nth(4).text_content().strip()
    page = context.new_page()
    url = f"{SEARCH_DETAIL}?BookingNumber={booking_id}"
    page.goto(url)
    page.wait_for_url(url)
    page.wait_for_load_state()
    logging.debug("get_booking on %s", page.url)

    booking_number = extract_field(page, "Booking Number:")
    assert booking_id == booking_number
    inmate_id = extract_field(page, "Inmate ID:")
    n_charges = int(extract_field(page, "Charges:", role="heading"))
    charges = get_charges(page, inmate_id, booking_number)
    found_charges = len(charges)
    try:
        assert n_charges == found_charges
    except AssertionError:
        logging.error(
            "booking ID: %s expected %d charges, got %d",
            booking_id,
            n_charges,
            found_charges,
        )
        raise
    logging.info("booking ID: %s has %d charges", booking_id, n_charges)

    results = {
        "booking_number": booking_number,
        "inmate_id": inmate_id,
        "first_name": first_name,
        "last_name": last_name,
        "middle_name": middle_name,
        "n_charges": n_charges,
        "booking_date": extract_field(page, "Booking Date:"),
        "scheduled_release": extract_field(page, "Sched. Release:"),
        "released": extract_field(page, "Released:"),
        "age": extract_field(page, "Age:"),
        "sex": extract_field(page, "Sex:"),
        "race": extract_field(page, "Race:"),
        "hair": extract_field(page, "Hair:"),
        "eyes": extract_field(page, "Eyes:"),
        "height": extract_field(page, "Height:"),
        "weight": extract_field(page, "Weight:"),
        "in_custody_as_of": extract_field(
            page, "IN CUSTODY as of", role="link"
        ),
        "charges": charges,
    }
    page.close()
    return results


def get_page(page, context) -> list:
    """
    Accept page (BookingSearchResult)
    and context.
    Return a list of the bookings on that page.
    """
    page.wait_for_load_state()
    logging.debug("get_page on %s", page.url)
    tbody = page.locator("tbody").first
    rows = tbody.get_by_role("row").all()
    return [get_booking(row, context) for row in rows]


def get_paginated(page, context) -> list:
    """
    Accept page (BookingSearchResult)
    and context.
    Return a list of the bookings on that page
    and all of its paginated successors.
    """
    results = get_page(page, context)

    while True:
        table_pager = page.locator("tfoot")
        if ">" in table_pager.text_content():
            page.get_by_role("link", name=">", exact=True).click()
            results += get_page(page, context)
        else:
            break
    return results


def fill_from_filters(page, filters: Filter):
    """
    Accept page (BookingSearchQuery)
    and filters.
    Fill fields in the page based on filters.
    """
    for field in filters._fields:
        # booking_begin_date -> Booking Begin Date
        label = " ".join([word.capitalize() for word in field.split("_")])
        value = getattr(filters, field)
        if value is not None:
            page.get_by_label(label).fill(value)


def run(playwright: Playwright, headless=True, filters=EMPTY_FILTER) -> list:
    """
    Run playwright against http://inmateinformation.lanecounty.org/.
    Return a list of dicts of inmate bookings.
    """
    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context()
    page = context.new_page()
    page.goto(f"{INMATE_INFORMATION}/")
    page.get_by_role("link", name="Access Site").click()
    fill_from_filters(page, filters)
    page.get_by_role("button", name="Search").click()
    page.wait_for_url(f"{SEARCH_RESULT}**")
    page.wait_for_load_state()
    n_candidates = int(
        extract_field(page, "Total Candidates:", role="heading")
    )
    logging.info("expect %d candidates", n_candidates)
    if n_candidates > 15:
        results = get_paginated(page, context)
    else:
        results = get_page(page, context)
    if n_candidates != len(results):
        logging.error("expected %d, got %d", n_candidates, len(results))
    return results


def custom_parser() -> argparse.ArgumentParser:
    """
    Return a parser for this script.
    """
    log = log_name(__file__)
    arguments = [
        {
            "args": ["-n", "--last-name"],
            "kwargs": {
                "help": "Last name, wildcarded.",
                "default": "%",
            },
        },
        {
            "args": ["-f", "--first-name"],
            "kwargs": {
                "help": "First name, wildcarded.",
                "default": "%",
            },
        },
        {
            "args": ["-b", "--booking-begin-date"],
            "kwargs": {
                "help": "Booking From Date.",
                "default": None,
            },
        },
        {
            "args": ["-e", "--booking-end-date"],
            "kwargs": {
                "help": "Booking To Date.",
                "default": None,
            },
        },
    ]
    return get_parser(*arguments, log=log)


def main():
    """
    Entry point.
    Parse command line arguments,
    set up logging,
    scrape,
    and write output.
    """
    parser = custom_parser()
    args = parser.parse_args()
    filters = Filter(
        args.last_name,
        args.first_name,
        args.booking_begin_date,
        args.booking_end_date,
    )

    configure_logging(args.log, args.log_level)
    headless = not args.no_headless
    with sync_playwright() as playwright:
        results = run(playwright, headless=headless, filters=filters)

        bookings = [
            {
                k: v
                for k, v in result.items()
                if k not in ["charges", "in_custody_as_of"]
            }
            for result in results
        ]
        write_csv("bookings.csv", bookings)

        custody = [
            {
                k: v
                for k, v in result.items()
                if k in ["booking_number", "inmate_id", "in_custody_as_of"]
            }
            for result in results
        ]
        write_csv("custody.csv", custody)

        charges = list(chain.from_iterable([el["charges"] for el in results]))
        write_csv("charges.csv", charges)


if __name__ == "__main__":
    main()
