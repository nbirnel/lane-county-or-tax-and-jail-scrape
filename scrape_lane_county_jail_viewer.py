#!/usr/bin/env python3
"""
Scrape account information from
https://apps.lanecounty.org/PropertyAccountInformation/
"""

from playwright.sync_api import (
    Playwright,
    sync_playwright,
)

from lcapps import (
    write_csv,
    configure_logging,
    logging,
    get_parser,
    log_name,
    retry,
)

INMATE_INFORMATION = "http://inmateinformation.lanecounty.org"
SEARCH_DETAIL = f"{INMATE_INFORMATION}/Home/BookingSearchDetail"
SEARCH_RESULT = f"{INMATE_INFORMATION}/Home/BookingSearchResult"

def extract_field(locator, name: str, role="cell") -> str:
    """
    Accept a Playwright locator,
    a name to search for, 
    optional role (default "cell").
    Return the stripped text after that name.
    """
    cell = locator.get_by_role(role, name=name).last
    return cell.text_content().strip().removeprefix(name).strip()


def get_booking(row, context) -> dict:
    """
    Accept row from inmateinformation.lanecounty.org/Home/BookingSearchResult?
    Return a dict of information about the booking.
    """
    booking_id = row.get_by_role("cell").nth(1).text_content().strip()
    # row.get_by_role("link").click(button="middle")
    page = context.new_page()
    url = f"{SEARCH_DETAIL}?BookingNumber={booking_id}"
    page.goto(url)
    page.wait_for_url(url)
    page.wait_for_load_state()
    logging.debug("get_booking on %s", page.url)

    results = {
        "booking_number": extract_field(page, "Booking Number:"),
        "inmate_id": extract_field(page, "Inmate ID:"),
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
        "n_charges": int(extract_field(page, "Charges:", role="heading")),
    }
    page.close()
    return results


def frun(context) -> None:
    page1 = context.new_page()
    page1.goto(
        "http://inmateinformation.lanecounty.org/Home/BookingSearchDetail?BookingNumber=24003685"
    )
    page1.get_by_role("heading", name="Charges:").click()
    page1.get_by_role(
        "cell", name="Violation: 163.190 - MENACING -"
    ).first.click()
    page1.get_by_role("cell", name="Level: M").first.click()
    page1.get_by_role("cell", name="Add. Desc.:").first.click()
    page1.get_by_role("cell", name="OBTS #:").first.click()
    page1.get_by_role("cell", name="War.#:").first.click()
    page1.get_by_role("cell", name="End Of Sentence Date:").first.click()
    page1.get_by_role("cell", name="Clearance:").first.click()
    page1.get_by_role(
        "cell", name="Arrest Agency: OR0200600 OR"
    ).first.click()
    page1.get_by_role("cell", name="Case #: 24-").first.click()
    page1.get_by_role("cell", name="Arrest Date: 05/04/").first.click()
    page1.get_by_role("cell", name="Court Type:").first.click()
    page1.get_by_role("cell", name="Court Case #: 24CR23376").first.click()
    page1.get_by_role("cell", name="Next Court Date").first.click()
    page1.get_by_role("cell", name="Req. Bond/Bail: SECURITY").first.click()
    page1.get_by_role("cell", name="Bond Group #:").first.click()
    page1.get_by_role("cell", name="Req. Bond Amt: $").first.click()
    page1.get_by_role("cell", name="Req. Cash Amt: $").first.click()
    page1.get_by_role("cell", name="Bond Co. #:").first.click()
    page1.locator("table").filter(has_text="1 Violation: 163.190 -").click()
    # page.get_by_role("link", name=">", exact=True).click()
    # page.get_by_role("link", name=">", exact=True).click()
    # page.get_by_role("heading", name="Total Candidates:").click()

    # ---------------------
    # context.close()
    # browser.close()


def get_paginated(page, context) -> list:
    results = get_page(page, context)

    while True:
        table_pager = page.locator("tfoot")
        if ">" in table_pager.text_content():
            page.get_by_role("link", name=">", exact=True).click()
            results += get_page(page, context)
        if "<<" in table_pager.text_content():
            break
        else:
            break
    return results


def get_page(page, context) -> list:
    page.wait_for_load_state()
    logging.debug("get_page on %s", page.url)
    tbody = page.locator("tbody").first
    rows = tbody.get_by_role("row").all()
    return [get_booking(row, context) for row in rows]


@retry()
def run(playwright: Playwright, headless=True) -> list:
    """
    Run playwright.
    Return a list of dicts.
    """
    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context()
    page = context.new_page()
    page.goto(f"{INMATE_INFORMATION}/")
    page.get_by_role("link", name="Access Site").click()
    page.get_by_label("Last Name").fill("%")
    page.get_by_label("Last Name").press("Tab")
    page.get_by_label("First Name").fill("%")
    page.get_by_role("button", name="Search").click()
    page.wait_for_url(f"{SEARCH_RESULT}**")
    page.wait_for_load_state()
    n_candidates = int(
        extract_field(page, "Total Candidates:", role="heading")
    )

    return get_paginated(page, context)


def main():
    """
    Entry point.
    Parse command line arguments,
    set up logging,
    and loop over items to scrape.
    """
    parser = get_parser()
    args = parser.parse_args()

    configure_logging(args.log, args.log_level)
    headless = not args.no_headless
    with sync_playwright() as playwright:
        result = run(playwright, headless=headless)
        print(result)
        # if result:
        #    for key, value in result.items():
        #        write_csv(f"{key}.csv", value, dest='.')


if __name__ == "__main__":
    main()
