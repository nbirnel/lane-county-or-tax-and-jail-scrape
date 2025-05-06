#!/usr/bin/env python3
"""
Scrape information from
https://apps.lanecounty.org/PropertyAccountInformation/
"""

import argparse
from itertools import chain
import re
from time import sleep

from playwright.sync_api import Playwright, sync_playwright

from lcapps import (
    configure_logging,
    get_parser,
    load_file,
    logging,
    log_name,
    strip,
    write_csv,
)

import sections


def get_16ths_of_multiple_sections(section_list: iter) -> list:
    """
    Accept an iterable of 6 digit land sections.
    Return all of their 16th sections in one list.
    """
    return chain.from_iterable(
        [get_16ths(section) for section in section_list]
    )


def get_16ths(section: int) -> list:
    """
    Accept a 6 digit land section.
    Return its 16th sections.
    """
    return [
        section * 100 + m * 10 + n for m in range(1, 5) for n in range(1, 5)
    ]


def parse_row(row) -> dict:
    """
    Accept a locator("tr") object.
    Return a dict of Lane County property look-up fields.
    """
    cells = row.locator("td")
    return {
        "account": strip(cells.nth(1).text_content()),
        "map_and_tax_lot": strip(cells.nth(2).text_content()),
        "tax_payer": strip(cells.nth(3).text_content()),
        "owner": strip(cells.nth(4).text_content()),
        "situs_address": strip(cells.nth(5).text_content()),
    }


def scrape(page) -> list:
    """
    Accept a playwright page.
    Return a list of dicts of property info.
    """
    rows = page.locator("tbody").locator("tr").all()
    return [parse_row(row) for row in rows]


def search(page, prefix: int) -> list:
    """
    Search the lane county property page for prefix.
    Return a list of dicts.
    """
    logging.info("%d", prefix)
    page.get_by_placeholder("Enter partial ").fill(str(prefix))
    page.get_by_role("button", name="Save Search").click()
    sleep(4)
    page.get_by_label("select").locator("span").click()
    page.get_by_role("option", name="All").click()
    pager = page.locator("div").filter(
        has=page.get_by_label("Go to the last page")
    )
    items_found = pager.locator("span").last.text_content()
    if items_found.endswith("No items to display"):
        logging.info("%d: No items found.", prefix)
        return []
    if items_found.endswith("of 100 items"):
        logging.info(
            "%d: 100 or more items found. Calling recursively.", prefix
        )
        return list(
            chain.from_iterable(
                [search(page, prefix * 10 + n) for n in range(10)]
            )
        )
    m = re.search(" of ([1-9][0-9]*) items", items_found)
    if m:
        found = int(m.groups()[0])
        logging.info("%d: %d items found", prefix, found)
        scraped = scrape(page)
        n_scraped = len(scraped)
        if n_scraped != found:
            message = (
                f"{prefix}: expected {found} items, but scraped {n_scraped}"
            )
            logging.error(message)
            raise ValueError(message)
        logging.debug("%d: %d items scraped", prefix, n_scraped)
        return scraped
    message = f"{prefix}: something weird with items found: {items_found}"
    logging.error(message)
    raise ValueError(message)


def run(playwright: Playwright, prefix: int, headless=True, **kwargs) -> list:
    """
    Run playwrite
    """
    search_by = kwargs["search_by"]
    logging.info("%s: scraping", prefix)
    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context()
    context.set_default_timeout(100_000)
    page = context.new_page()
    page.goto("https://apps.lanecounty.org/PropertyAccountInformation/#")
    page.get_by_role("button", name="Search by Account Number").click()
    page.get_by_role("menuitem", name=search_by).click()
    return search(page, prefix)


def custom_parser() -> argparse.ArgumentParser:
    """
    Return a parser for this script
    """
    log = log_name(__file__)
    arguments = [
        {
            "args": ["-c", "--city"],
            "kwargs": {
                "help": "City to scrape.",
                "choices": sections.cities.keys(),
                "default": "eugene",
            },
        },
        {
            "args": ["-r", "--read-file"],
            "kwargs": {
                "help": "File to read tax maps from. Overrides -c",
                "default": None,
            },
        },
        {
            "args": ["-n", "--read-names"],
            "kwargs": {
                "help": "File to read names from. Overrides -c, -f",
            },
        },
        {
            "args": ["-o", "--output"],
            "kwargs": {
                "help": "File to write results to.",
                "default": "lane-county-property.csv",
            },
        },
    ]
    return get_parser(*arguments, log=log)


def main():
    """
    parse args, set up logging, and scrape.
    """

    parser = custom_parser()
    args = parser.parse_args()

    configure_logging(args.log, args.log_level)

    city = args.city
    read_file = args.read_file
    read_names = args.read_names

    if read_names:
        searches = load_file(read_names)
        search_by = "Search by Name"
    elif read_file:
        searches = [ int(i) for i in load_file(read_file) ]
        search_by = "Search by Map and Taxlot"
    elif city:
        searches = sections.cities[city]
        search_by = "Search by Map and Taxlot"
    else:
        parser.error("we need one of -c, -r, or -n")
    print(args)

    for search_f in searches:
        if args.dry_run:
            print(search_f)
        else:
            with sync_playwright() as playwright:
                results = run(playwright, search_f, search_by=search_by)
                if (number_of_results := len(results)) >= 1:
                    write_csv(args.output, results)
                logging.info(
                    "%s search by %s: %d total items found",
                    search_f,
                    search_by,
                    number_of_results,
                )


if __name__ == "__main__":
    main()
