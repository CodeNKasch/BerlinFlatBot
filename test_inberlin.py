#!/usr/bin/env python3
"""Test script to debug InBerlinWohnen scraper"""

import asyncio
import logging
from scrapers import InBerlinWohnenScraper

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG
)

async def main():
    scraper = InBerlinWohnenScraper("https://inberlinwohnen.de/wohnungsfinder/")

    try:
        flats = await scraper.fetch_flats()
        print(f"\nFound {len(flats)} flats:")
        for flat in flats:
            print(f"\n  ID: {flat.id}")
            print(f"  Title: {flat.title}")
            print(f"  Link: {flat.link}")
            print(f"  Details: {flat.details}")
            print(f"  WBS: {flat.wbs_required}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
