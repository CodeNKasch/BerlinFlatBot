"""Degewo scraper."""

import logging
from typing import List, Optional

import aiohttp
from bs4 import BeautifulSoup

from .base import (
    BaseScraper,
    FlatDetails,
    HighTrafficError,
    StandardFields,
    WebsiteUnavailableError,
    check_wbs_required,
)

logger = logging.getLogger(__name__)


class DegewoScraper(BaseScraper):
    async def fetch_flats(self) -> List[FlatDetails]:
        logger.info("Fetching flats from Degewo...")
        try:
            async with aiohttp.ClientSession() as session:
                success, html = await self._make_request(session)
                if not success:
                    return []

                soup = BeautifulSoup(html, "html.parser")
                flats = []

                # Check for high traffic message
                if (
                    soup.find("div", class_="error-message")
                    and "high traffic" in soup.text.lower()
                ):
                    raise HighTrafficError("Website experiencing high traffic")

                # Find all flat elements
                flat_elements = soup.find_all(
                    "article",
                    class_="article-list__item article-list__item--immosearch",
                )
                logger.info(f"Found {len(flat_elements)} flat elements in HTML")

                for flat in flat_elements:
                    flat_details = self._extract_flat_details(flat)
                    if flat_details:
                        flats.append(flat_details)

                # Filter out duplicates within this fetch
                flats = self._filter_duplicates(flats)
                logger.debug(f"Flat IDs found: {[flat.id for flat in flats]}")
                return flats
        except (WebsiteUnavailableError, HighTrafficError) as e:
            logger.error(f"Error fetching flats from Degewo: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching flats from Degewo: {e}")
            return []

    def _extract_flat_details(self, flat_element) -> Optional[FlatDetails]:
        try:
            # Extract the unique ID from the article's ID attribute
            flat_id = flat_element.get("id", "").replace("immobilie-list-item-", "")

            # Extract the title of the flat
            title_element = flat_element.find("h2", class_="article__title")
            title_text = title_element.text.strip() if title_element else "No title"

            # Extract the link to the flat's details
            link_element = flat_element.find("a", href=True)
            link = link_element["href"] if link_element else None
            if link and not link.startswith("http"):
                link = f"https://www.degewo.de{link}"

            # Extract additional details
            details = {}
            address_element = flat_element.find("span", class_="article__meta")
            if address_element:
                details[StandardFields.ADDRESS] = address_element.text.strip()

            # Extract tags (e.g., Balkon/Loggia, Aufzug)
            tags = flat_element.find_all("li", class_="article__tags-item")
            if tags:
                details[StandardFields.FEATURES] = ", ".join(tag.text.strip() for tag in tags)

            # Extract properties (e.g., Zimmer, Wohnfläche, Verfügbarkeit)
            properties = flat_element.find_all("li", class_="article__properties-item")
            for prop in properties:
                svg = prop.find("svg")
                if svg and "i-room" in svg.get("xlink:href", ""):
                    details[StandardFields.ROOMS] = prop.find(
                        "span", class_="text"
                    ).text.strip()
                elif svg and "i-squares" in svg.get("xlink:href", ""):
                    details[StandardFields.AREA] = prop.find(
                        "span", class_="text"
                    ).text.strip()
                elif svg and "i-calendar2" in svg.get("xlink:href", ""):
                    details[StandardFields.AVAILABLE_FROM] = prop.find(
                        "span", class_="text"
                    ).text.strip()

            # Extract price
            price_element = flat_element.find("div", class_="article__price-tag")
            if price_element:
                price_text = price_element.find("span", class_="price")
                if price_text:
                    details[StandardFields.RENT_WARM] = price_text.text.strip()

            # Determine if WBS is required - check title and all details
            wbs_sources = [title_text] + [str(v) for v in details.values() if v]
            wbs_required = any(check_wbs_required(source) for source in wbs_sources)

            # Return the flat details
            return FlatDetails(
                id=flat_id,
                title=title_text,
                link=link,
                details=details,
                wbs_required=wbs_required,
                source="Degewo",
            )
        except Exception as e:
            logger.error(f"Error extracting flat details from Degewo: {e}")
            return None
