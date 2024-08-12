import re
import sys

from playwright.sync_api import Playwright, sync_playwright, expect

from lcapps import strip

def run(playwright: Playwright, account: str) -> dict:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://apps.lanecounty.org/PropertyAccountInformation/")
    page.get_by_placeholder("Enter partial account #").fill(account)
    page.get_by_role("button", name="Save Search").click()
    page.get_by_role("link", name=account).click()

    account_div = page.locator("div").filter(has=page.get_by_text("Account Information"))
    rows = account_div.locator("tbody").locator("tr")
    table_map = {
        0: "account_number",
        3: "tax_payer",
        #4: "owner",
        5: "situs_address",
        6: "mailing_address",
        7: "map_and_tax_lot_number",
        8: "acreage",
        9: "tca",
        10: "prop_class",
    }
    account_information = {
        "account_number": strip(rows.first.locator("td").last.text_content()),
        "tax_payer": strip(rows.nth(3).locator("td").last.text_content()),
        "situs_address": strip(rows.nth(5).locator("td").last.text_content()),
        "mailing_address": strip(rows.nth(6).locator("td").last.text_content()),
        "map_and_tax_lot_number": strip(rows.nth(7).locator("td").last.text_content()),
        "acreage": strip(rows.nth(8).locator("td").last.text_content()),
        "tca": strip(rows.nth(9).locator("td").last.text_content()),
        "prop_class": strip(rows.nth(10).locator("td").last.text_content()),
    }

    print(account_information)
    
    receipts_table = page.locator("table").filter(has=page.get_by_text("Amount Received"))
    rows = receipts_table.locator("tbody").locator("tr").all()
    receipts = [
        {
            "date": strip(row.locator("td").nth(0).text_content()),
            "amount_received": strip(row.locator("td").nth(1).text_content()),
            "tax": strip(row.locator("td").nth(2).text_content()),
            "discount": strip(row.locator("td").nth(3).text_content()),
            "interest": strip(row.locator("td").nth(4).text_content()),
        }
        for row in rows
    ]
    print(receipts)

    assessments_table = page.locator("table").filter(has=page.get_by_text("Assessed Value")).locator("table")
    headers = assessments_table.locator("thead").locator("tr").locator("th").all()
    years = [ int(th.text_content()) for th in headers ]
    rows = assessments_table.locator("tbody").locator("tr").all()

    av = [ td.text_content() for td in rows[0].locator("td").all() ]
    assessed_values = zip(years, av)
    print(dict(assessed_values))

    mav = [ td.text_content() for td in rows[1].locator("td").all() ]
    max_assessed_values = zip(years, mav)
    print(dict(max_assessed_values))

    rmv = [ td.text_content() for td in rows[1].locator("td").all() ]
    real_market_values = zip(years, rmv)
    print(dict(real_market_values))
    sys.exit()

    page.get_by_role("cell", name="Tax Payer").click()
    page.get_by_role("cell", name="Situs Address").click()
    page.get_by_role("cell", name="Mailing Address").click()
    page.get_by_role("cell", name="Map and Tax Lot #").click()
    page.get_by_role("cell", name="Acreage").click()
    page.get_by_role("cell", name="TCA").click()
    page.get_by_role("cell", name="Prop Class").click()
    page.get_by_role("heading", name="Remarks").click()
    page.get_by_text("Recent Receipts - Click here to check for any amounts owing. DateAmount").click()
    page.get_by_text("Valuation History More").click()
    page.locator("#ctl00_MainContentPlaceHolder_valuesGrid_ctl00_RowZone1").click()

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright, "0156701")
