import asyncio
import csv
import argparse
from playwright.async_api import async_playwright

# All requested fields
FIELDNAMES = [
    "id", "name", "address", "city", "district",
    "lat", "lon", "url_2gis", "parking_type", "paid",
    "tariff", "capacity", "parent_object", "hours",
    "rating", "review_count", "has_photos"
]

# District URLs to ensure we get all data
DISTRICTS = {
    "Almalinsky": "https://2gis.kz/almaty/search/парковка/district/546944355",
    "Bostandyksky": "https://2gis.kz/almaty/search/парковка/district/546944365",
    "Medeu": "https://2gis.kz/almaty/search/парковка/district/546944361",
    "Auezovsky": "https://2gis.kz/almaty/search/парковка/district/546944357",
    "Turksib": "https://2gis.kz/almaty/search/парковка/district/546944367",
    "Jetisu": "https://2gis.kz/almaty/search/парковка/district/546944363",
    "Nauryzbay": "https://2gis.kz/almaty/search/парковка/district/546944369",
    "Alatau": "https://2gis.kz/almaty/search/парковка/district/546944359"
}

def extract_attr(raw, *keywords):
    """Helper to extract specific data from attribute groups (e.g., tariff, capacity)."""
    groups = raw.get("attribute_groups", [])
    for group in groups:
        for attr in group.get("attributes", []):
            name = attr.get("name", "").lower()
            if any(k in name for k in keywords):
                val = attr.get("value", {})
                return str(val.get("text", val))
    return ""

def extract_schedule(raw):
    sched = raw.get("schedule", {})
    if not sched: return ""
    if sched.get("is_24x7"): return "24/7"
    return "See 2GIS" # Complex nested structure

def parking_type(name):
    n = name.lower()
    if any(k in n for k in ["бц", "бизнес"]): return "БЦ"
    if any(k in n for k in ["трк", "тц", "mall"]): return "ТЦ"
    if "город" in n: return "городская"
    return "частная"

def parse_item(raw):
    obj_id = str(raw.get("id", ""))
    adm = raw.get("adm_div", [])
    district = next((a.get("name") for a in adm if a.get("type") == "district"), "")
    
    return {
        "id": obj_id,
        "name": raw.get("name", ""),
        "address": raw.get("address", {}).get("name", ""),
        "city": "Алматы",
        "district": district,
        "lat": raw.get("point", {}).get("lat", ""),
        "lon": raw.get("point", {}).get("lon", ""),
        "url_2gis": f"https://2gis.kz/almaty/geo/{obj_id}",
        "parking_type": parking_type(raw.get("name", "")),
        "paid": extract_attr(raw, "оплата", "платн"),
        "tariff": extract_attr(raw, "тариф", "цена"),
        "capacity": extract_attr(raw, "мест", "capacity"),
        "parent_object": raw.get("org", {}).get("name", ""),
        "hours": extract_schedule(raw),
        "rating": raw.get("reviews", {}).get("general_rating", ""),
        "review_count": raw.get("reviews", {}).get("general_review_count", ""),
        "has_photos": bool(raw.get("flags", {}).get("photos"))
    }

async def run_scraper(output_file):
    results = []
    seen = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        async def handle_response(response):
            if "catalog.api.2gis" in response.url:
                try:
                    data = await response.json()
                    items = data.get("result", {}).get("items", [])
                    for item in items:
                        if item.get("id") not in seen:
                            parsed = parse_item(item)
                            results.append(parsed)
                            seen.add(item.get("id"))
                except: pass

        page.on("response", handle_response)

        for district, url in DISTRICTS.items():
            print(f"\n--- Scraping District: {district} ---")
            await page.goto(url)
            await page.wait_for_timeout(3000)
            
            # Simple scroll to trigger loading
            container = page.locator('div[data-scroll="true"]').first
            for _ in range(10):
                await container.evaluate("el => el.scrollTop = el.scrollHeight")
                await page.wait_for_timeout(1500)

        await browser.close()

    with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(results)
    print(f"\n✅ Done. Saved {len(results)} parkings with full details.")

if __name__ == "__main__":
    asyncio.run(run_scraper("parkings_almaty.csv"))




