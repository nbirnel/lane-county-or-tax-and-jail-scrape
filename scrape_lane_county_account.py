"""
Scrape account information from
https://apps.lanecounty.org/PropertyAccountInformation/
"""

import argparse
from decimal import Decimal
from functools import wraps
from itertools import dropwhile
import logging
import re
from time import sleep

from playwright.sync_api import (
    Playwright,
    expect,
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

from lcapps import strip, write_csv, configure_logging, get_parser, log_name


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
            except Exception:
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
                    "%s: will sleep %d seconds before retry %d",
                    func.__name__,
                    sleep_duration := n_tries**3,
                    n_tries,
                )
                sleep(sleep_duration)
                return wrapper(*args, n_tries=n_tries, **kwargs)

        return wrapper

    return decorate


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
        prestripped = m.groups()[0]
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


def get_account_lot_payer_owner(page, account) -> dict:
    """
    Accept page, account.
    page is https://apps.lanecounty.org/PropertyAccountInformation/#
    with "search by Account number" and a single account line.
    Return a dict of account information from that page.
    """
    logging.debug("%s: getting account info", account)
    account_div = page.locator("div").filter(
        has=page.get_by_text("Account Information")
    )
    rows = account_div.locator("tbody").locator("tr")
    site_address, site_city_state_zip = get_account_row(
        rows, "Situs Address", cleaner=clean_address_2
    )
    m_address_1, m_address_2, m_address_3, m_city_state_zip = get_account_row(
        rows, "Mailing Address", cleaner=clean_address_4
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
        "situs_city_state_zip": site_city_state_zip,
        "mailing_address_1": m_address_1,
        "mailing_address_2": m_address_2,
        "mailing_address_3": m_address_3,
        "mailing_city_state_zip": m_city_state_zip,
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
    page is, eg https://apps.lanecounty.org/PropertyAccountInformation/Account/0259901.
    Return list of dicts of receipt information from page.
    """
    logging.debug("%s: getting receipts", account)
    receipts_table = page.locator("table").filter(
        has=page.get_by_text("Amount Received")
    )
    if "No records to display" in receipts_table.text_content():
        logging.info("%s: No records to display", account)
        return []
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
        logging.error("%s: unable to find receipts", account)
        raise ValueError("Unable to find receipts")
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
    page is, eg https://apps.lanecounty.org/PropertyAccountInformation/Account/0259901.
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


def get_owner_item(row, idx: int) -> str:
    """
    Accept owner row, idx.
    Return stripped item at index idx.
    """
    return row.locator("td").nth(idx).text_content().strip()


def get_building_floor(tbody, floor) -> dict:
    """
    Accept tbody (residential floors table body), floor.
    Return dict.
    """
    cells = (
        tbody.get_by_role("row").filter(has_text=floor).get_by_role("cell")
    )
    return {
        "base_sq_ft": cells.nth(1).text_content().strip(),
        "finished_sq_ft": cells.nth(2).text_content().strip(),
    }


def get_structure(tbody, structure) -> str:
    """
    Accept tbody (residential structures table body), structure.
    Return str of structure's square footage.
    """
    cell = tbody.locator("tr").filter(has_text=structure).locator("td")
    return cell.text_content().strip()


def get_manufactured_home_item(cells, idx: int) -> str:
    """
    Accept cells (row tds), index idx.
    Return stripped text from that cell.
    """
    return cells.nth(idx).text_content().strip()


def get_residential_text(page) -> str:
    """
    Accept page.
    page is, e.g., https://www.rlid.org/custom/lc/at/index.cfm?do=custom_LC_AT_propsearch.directqry&type=report&acctint=0259901
    Return the string of the "Residential Building" line.
    """
    return page.get_by_text("Residential Building").text_content().strip()


def get_residential_building(page, taxlot) -> dict:
    """
    Accept page.
    page is, e.g., https://www.rlid.org/custom/lc/at/index.cfm?do=custom_LC_AT_propsearch.directqry&type=report&acctint=0259901
    Return a dict about any residential building described on the page.
    """
    res_text = get_residential_text(page)
    if re.search(r"Residential Building\s*None", res_text):
        logging.debug("%s: No residential buildings", taxlot)
        return {}
    # We do not have a way of getting information on additional buildings
    # after the first.
    # Warn on them.
    if not res_text.endswith("(of 1)"):
        logging.warning("%s: %s", taxlot, res_text)
    res_supertable = page.locator(
        f"table:below(:text('{res_text}'))"
    ).locator("table")

    logging.debug("%s: looking for residential structure", taxlot)
    year_tr = res_supertable.locator("tr", has_text="Year Built").first
    try:
        expect(year_tr).to_be_visible()
        year_built = year_tr.locator("td").text_content().strip()
        building_tbody = res_supertable.locator("tbody").filter(
            has_text="Floor"
        )
        structures_tbody = res_supertable.locator("tbody").filter(
            has_text="Structure"
        )

        basement_floor = get_building_floor(building_tbody, "Basement")
        first_floor = get_building_floor(building_tbody, "First")
        second_floor = get_building_floor(building_tbody, "Second")
        attic_floor = get_building_floor(building_tbody, "Attic")
        total_floor = get_building_floor(building_tbody, "Total")
        return {
            "taxlot": taxlot,
            "year_built": year_built,
            "basement_floor_base": basement_floor["base_sq_ft"],
            "basement_floor_finished": basement_floor["finished_sq_ft"],
            "first_floor_base": first_floor["base_sq_ft"],
            "first_floor_finished": first_floor["finished_sq_ft"],
            "second_floor_base": second_floor["base_sq_ft"],
            "second_floor_finished": second_floor["finished_sq_ft"],
            "attic_floor_base": attic_floor["base_sq_ft"],
            "attic_floor_finished": attic_floor["finished_sq_ft"],
            "total_floor_base": total_floor["base_sq_ft"],
            "total_floor_finished": total_floor["finished_sq_ft"],
            "basement_garage": get_structure(structures_tbody, "Bsmt Garage"),
            "attached_garage": get_structure(structures_tbody, "Att Garage"),
            "detached_garage": get_structure(structures_tbody, "Det Garage"),
            "attached_carport": get_structure(
                structures_tbody, "Att Carport"
            ),
            "manufactured": "false",
            "manufactured_model_year": "N/A",
            "manufactured_make": "N/A",
            "manufactured_plate": "N/A",
            "manufactured_lois": "N/A",
        }
    except (AssertionError, PlaywrightTimeoutError) as error:
        logging.warning("%s: residential not found: %s", taxlot, error)
        logging.debug("%s: looking for manufactured structure", taxlot)
        try:
            manufactured_structure = page.get_by_text(
                "Manufactured Structure"
            )
            expect(manufactured_structure).to_be_visible()
            # We can scrape 1 manufactured home, whether it has data or not.
            # We have not yet seen multiple manufactured homes, so warn on them.
            logging.warning("%s: manufactured building", taxlot)
            tbody = page.locator(
                "tbody:below(:text('Manufactured Structure'))"
            ).first
            cells = tbody.locator("tr").last.locator("td")
            return {
                "taxlot": taxlot,
                "year_built": "N/A",
                "basement_floor_base": "N/A",
                "basement_floor_finished": "N/A",
                "first_floor_base": "N/A",
                "first_floor_finished": "N/A",
                "second_floor_base": "N/A",
                "second_floor_finished": "N/A",
                "attic_floor_base": "N/A",
                "attic_floor_finished": "N/A",
                "total_floor_base": "N/A",
                "total_floor_finished": "N/A",
                "basement_garage": "N/A",
                "attached_garage": "N/A",
                "detached_garage": "N/A",
                "attached_carport": "N/A",
                "manufactured": "true",
                "manufactured_model_year": get_manufactured_home_item(
                    cells, 0
                ),
                "manufactured_make": get_manufactured_home_item(cells, 1),
                "manufactured_plate": get_manufactured_home_item(cells, 2),
                "manufactured_lois": get_manufactured_home_item(cells, 3),
            }
        except AssertionError:
            logging.error("%s: unknown residential building", taxlot)
            return {}


def get_building_stat(rows, label: str, has_not_text=None) -> str:
    """
    Accept Commercial Building table rows, label, optional has_not_text.
    Select row that matches label but not has_not_text.
    Return that rows last cell's stripped text.
    """
    if has_not_text:
        matches = rows.filter(has_text=label).filter(
            has_not_text=has_not_text
        )
    else:
        matches = rows.filter(has_text=label)
    return matches.get_by_role("cell").last.text_content().strip()


def get_commercial_building(description, table, taxlot) -> dict:
    """
    Accept description, table, taxlot.
    Return dict of information about the building.
    """
    stats, sq_ft = table.get_by_role("table").all()
    stats_rows = stats.get_by_role("row")
    sq_ft_rows = sq_ft.get_by_role("row")
    return {
        "taxlot": taxlot,
        "description": description,
        "year_built": get_building_stat(
            stats_rows, "Year Built", has_not_text="Effective"
        ),
        "effective_year_built": get_building_stat(
            stats_rows, "Effective Year Built"
        ),
        "grade": get_building_stat(stats_rows, "Grade"),
        "floor_number": get_building_stat(stats_rows, "Floor Number"),
        "wall_height_ft": get_building_stat(stats_rows, "Wall Height Ft"),
        "occupancy_number": get_building_stat(stats_rows, "Occupancy Number"),
        "sq_ft": sq_ft_rows.first.get_by_role("cell")
        .last.text_content()
        .strip(),
        "fireproof_steel_sq_ft": get_building_stat(
            sq_ft_rows, "Fireproof Steel Sq Ft"
        ),
        "reinforced_concrete_sq_ft": get_building_stat(
            sq_ft_rows, "Reinforced Concrete Sq Ft"
        ),
        "fire_resistant_sq_ft": get_building_stat(
            sq_ft_rows, "Fire Resistant Sq Ft"
        ),
        "wood_joist_sq_ft": get_building_stat(sq_ft_rows, "Wood Joist Sq Ft"),
        "pole_frame_sq_ft": get_building_stat(sq_ft_rows, "Pole Frame Sq Ft"),
        "pre_engineered_steel_sq_ft": get_building_stat(
            sq_ft_rows, "Pre-engineered Steel Sq Ft"
        ),
    }


def get_commercial_improvements(page, taxlot) -> list:
    """
    Accept page.
    page is, e.g., https://www.rlid.org/custom/lc/at/index.cfm?do=custom_LC_AT_propsearch.directqry&type=report&acctint=0259901
    Return a list of commercial improvements.
    """
    res_text = get_residential_text(page)

    logging.debug("%s: looking for commercial improvements", taxlot)
    commercial_elems = [
        {
            "text": header.text_content().strip(),
            "header": header,
        }
        for header in page.locator(
            f"h3:below(:text('{res_text}'))", has_text="Commercial"
        ).all()
    ]

    commercial_header = None
    for elem in commercial_elems:
        if elem["text"] == "Commercial Improvements":
            commercial_header = elem["header"]
            break
        if re.match(r"Commercial Building\s*None", elem["text"]):
            logging.debug("%s: No commercial buildings", taxlot)
            return []

    if commercial_header is None:
        texts = ";".join([e["text"] for e in commercial_elems])
        logging.error(
            "%s: something wrong with commercial improvements: %s",
            taxlot,
            texts,
        )
        return []

    building_elems = [
        {
            "label": header.text_content().strip(),
            "table": header.locator("xpath=following::table[1]"),
        }
        for header in commercial_header.locator("xpath=following::h4").all()
    ]
    logging.debug(
        "%s: Finding %d commercial buildings", taxlot, len(building_elems)
    )

    return [
        get_commercial_building(building["label"], building["table"], taxlot)
        for building in building_elems
    ]


def get_taxlot_page(page, account: str) -> dict:
    """
    Accept page, account.
    page is, e.g., https://www.rlid.org/custom/lc/at/index.cfm?do=custom_LC_AT_propsearch.directqry&type=report&acctint=0259901
    Return a dict of owners information from that page.
    """
    logging.debug("%s: getting owner info", account)
    page.get_by_role("button", name="View Owners").click()
    page.wait_for_url("https://www.rlid.org/custom/lc/at/index.cfm**")
    page.wait_for_load_state()
    title = page.title()

    if title == "Lane County Assessment and Taxation Lane County A & T Property Search":
        logging.warning("%s: no Account Information", account)
        return {
            "owners": [],
            "residential_building": [],
            "commercial_improvements": [],
            "taxlot_accounts": [],
        }
    if title != "Lane County Assessment and Taxation Prop Info Report":
        logging.error("%s: unknown page title: %s", account, title)
        raise ValueError

    map_tax_s = "Map, Tax Lot & SIC "
    taxlot = (
        page.get_by_text(map_tax_s)
        .last.text_content()
        .removeprefix(map_tax_s)
        .strip()
        .replace("-", "")
        .replace(" ", "")
    )

    additional_s = "Additional Account Numbers for this Tax Lot"
    additional_accounts = [
        account.strip()
        for account in page.get_by_role("row")
        .filter(has_text=additional_s)
        .get_by_role("cell")
        .last.text_content()
        .strip()
        .removeprefix(additional_s)
        .split(";")
    ]
    if additional_accounts == [""]:
        all_accounts = [account]
    else:
        all_accounts = [account] + additional_accounts

    owner_table = page.locator("table").filter(
        has_text="Owner Address City State Zip"
    )

    account_type = (
        page.locator("tbody")
        .locator("tbody")
        .locator("tr")
        .filter(has_text="Account Type")
        .locator("td")
        .last.text_content()
        .strip()
    )

    taxlot_accounts = [
        {
            "account": acc,
            "taxlot": taxlot,
        }
        for acc in all_accounts
    ]
    owners = [
        {
            "account": account,
            "account_type": account_type,
            "owner": get_owner_item(row, 0),
            "address": get_owner_item(row, 1),
            "city_state_zip": get_owner_item(row, 2),
        }
        for row in owner_table.locator("tr").all()[1:]
    ]
    residential_building = get_residential_building(page, taxlot)
    commercial_improvements = get_commercial_improvements(page, taxlot)
    logging.debug("%s: got owner info", account)
    return {
        "owners": owners,
        "residential_building": [residential_building],
        "commercial_improvements": commercial_improvements,
        "taxlot_accounts": taxlot_accounts,
    }


@retry()
def run(playwright: Playwright, account: str, headless=True) -> dict:
    """
    Run playwright against account.
    Return a dict of lists of dicts: accounts, receipts, assessments.
    """
    logging.info("%s: scraping", account)
    browser = playwright.chromium.launch(headless=headless)
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
        raise

    account_lot_payer_owner = get_account_lot_payer_owner(page, account)
    receipts = get_receipts(page, account)
    assessments = get_assessments(page, account)

    taxlot = get_taxlot_page(page, account)
    logging.info("%s: scraped", account)
    return {
        "account_lot_payer_owner": [account_lot_payer_owner],
        "receipts": receipts,
        "assessments": assessments,
        "owners": taxlot["owners"],
        "residential_buildings": taxlot["residential_building"],
        "commercial_improvements": taxlot["commercial_improvements"],
        "taxlot_accounts": taxlot["taxlot_accounts"],
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
    headless = not args.no_headless
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
                result = run(playwright, account, headless=headless)
                if result:
                    for key, value in result.items():
                        write_csv(f"{key}.csv", value, dest=dest)


if __name__ == "__main__":
    main()
