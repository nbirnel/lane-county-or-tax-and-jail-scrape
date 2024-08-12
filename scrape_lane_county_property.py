import csv
from itertools import chain
import logging
import os
import os.path
import re
from time import sleep

from playwright.sync_api import Playwright, sync_playwright

from lcapps import strip
import sections


def get_16ths_of_multiple_sections(section_list: iter) -> list:
    """
    Accept an iterable of 6 digit land sections.
    Return all of their 16th sections in one list.
    """
    return chain.from_iterable(
        [ get_16ths(section) for section in section_list ]
    )

def get_16ths(section: int) -> list:
    """
    Accept a 6 digit land section.
    Return its 16th sections.
    """
    return [
        section * 100 + m * 10 + n
        for m in range(1,5)
        for n in range(1,5)
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
    return [ parse_row(row) for row in rows ]

def search(page, prefix: int) -> list:
    """
    Search the lane county property page for prefix.
    Return a list of dicts.
    """
    logging.info("%d", prefix)
    page.get_by_placeholder("Enter partial map and taxlot").fill(str(prefix))
    page.get_by_role("button", name="Save Search").click()
    sleep(4)
    page.get_by_label("select").locator("span").click()
    page.get_by_role("option", name="All").click()
    pager = page.locator("div").filter(has=page.get_by_label("Go to the last page"))
    items_found = pager.locator("span").last.text_content()
    if items_found.endswith("No items to display"):
        logging.info("%d: No items found.", prefix)
        return []
    if items_found.endswith("of 100 items"):
        logging.info("%d: 100 or more items found. Calling recursively.", prefix)
        return list(chain.from_iterable(
            [
                search(page, prefix * 10 + n)
                for n in range(10)
            ]
        ))
    m = re.search(" of ([1-9][0-9]*) items", items_found)
    if m:
        found = int(m.groups()[0])
        logging.info("%d: %d items found", prefix, found)
        scraped = scrape(page)
        n_scraped = len(scraped)
        if n_scraped != found:
            message = f"{prefix}: expected {found} items, but scraped {n_scraped}"
            logging.error(message)
            raise ValueError(message)
        return scraped
    message = f"{prefix}: something weird with items found: {items_found}"
    logging.error(message)
    raise ValueError(message)


def run(playwright: Playwright, prefix: int, headless=True) -> list:
    """
    Run playwrite
    """
    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context()
    context.set_default_timeout(100_000)
    page = context.new_page()
    page.goto("https://apps.lanecounty.org/PropertyAccountInformation/#")
    page.get_by_role("button", name="Search by Account Number").click()
    page.get_by_role("menuitem", name="Search by Map and Taxlot").click()
    return search(page, prefix)

#    page.get_by_role("gridcell", name="1703311204300").click()
#    page.locator("tr:nth-child(98) > td:nth-child(4)").click()
#    page.locator("tr:nth-child(98) > td:nth-child(5)").click()
#    page.locator("tr:nth-child(98) > td:nth-child(6)").click()
#    page.get_by_role("link", name="0259265").click()
#    page.get_by_role("button", name="View Owners").click()
#    page.get_by_role("heading", name="Property Value and Taxes").click()
#    page.get_by_role("link", name="Taxable Value").click()
#    page.get_by_role("heading", name="Taxable Value").click()
#    page.get_by_text("Account Acreage").click()
#    page.locator("body").press("Escape")

    # ---------------------

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


def write_file(path, filename, rows, fieldnames):
    """
    Write our output csv
    """
    os.makedirs(path, exist_ok=True)
    output = os.path.join(path, filename)
    with open(output, "a", encoding="utf8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if not os.path.exists(output):
            writer.writeheader()
        writer.writerows(rows)

def main():
    configure_logging("lane-county-property-scrape.log", "INFO")

    for section in sections.sections['eugene']:
        with sync_playwright() as playwright:
            results = run(playwright, section)
            if (number_of_results := len(results) >= 1:
                fieldnames = results[0].keys()
                write_file(".", "results.csv", results, fieldnames)
            logging.info("%d SECTION: %d total items found", section, number_of_results)

if __name__ == "__main__":
    main()
