"""Gewobag scraper."""

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


class GewobagScraper(BaseScraper):
    async def fetch_flats(self) -> List[FlatDetails]:
        logger.info("Fetching flats from Gewobag...")
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
                flat_elements = soup.find_all("article", class_="angebot-big-box")
                logger.info(f"Found {len(flat_elements)} flat elements in HTML")

                for flat in flat_elements:
                    flat_details = self._extract_flat_details(flat)
                    if flat_details:
                        flats.append(flat_details)

                # Filter out duplicates within this fetch
                flats = self._filter_duplicates(flats)
                return flats
        except (WebsiteUnavailableError, HighTrafficError) as e:
            logger.error(f"Error fetching flats from Gewobag: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching flats from Gewobag: {e}")
            return []

    def _extract_flat_details(self, flat_element) -> Optional[FlatDetails]:
        try:
            # Extract the unique ID from the article's ID attribute
            flat_id = flat_element.get("id", "").replace("post-", "")

            # Extract title and link
            title_element = flat_element.find("h3", class_="angebot-title")
            if not title_element:
                return None

            title_text = title_element.text.strip()

            # Extract link from the footer
            link_element = flat_element.find("a", class_="read-more-link")
            link = link_element.get("href") if link_element else None

            # Extract details from the info table
            details = {}
            info_table = flat_element.find("table", class_="angebot-info")
            if info_table:
                # Extract region
                region_row = info_table.find("tr", class_="angebot-region")
                if region_row:
                    details[StandardFields.DISTRICT] = region_row.find("td").text.strip()

                # Extract address
                address_row = info_table.find("tr", class_="angebot-address")
                if address_row:
                    address_element = address_row.find("address")
                    if address_element:
                        details[StandardFields.ADDRESS] = address_element.text.strip()

                # Extract area info
                area_row = info_table.find("tr", class_="angebot-area")
                if area_row:
                    details[StandardFields.AREA] = area_row.find("td").text.strip()

                # Extract availability
                availability_row = info_table.find("tr", class_="availability")
                if availability_row:
                    details[StandardFields.AVAILABLE_FROM] = availability_row.find("td").text.strip()

                # Extract costs
                kosten_row = info_table.find("tr", class_="angebot-kosten")
                if kosten_row:
                    details[StandardFields.RENT_WARM] = kosten_row.find("td").text.strip()

                # Extract characteristics
                characteristics_row = info_table.find(
                    "tr", class_="angebot-characteristics"
                )
                if characteristics_row:
                    characteristics = []
                    for li in characteristics_row.find_all("li"):
                        characteristics.append(li.text.strip())
                    if characteristics:
                        details[StandardFields.FEATURES] = ", ".join(characteristics)

            # Check for WBS requirement - check title and all details
            wbs_sources = [title_text] + [str(v) for v in details.values() if v]
            wbs_required = any(check_wbs_required(source) for source in wbs_sources)

            return FlatDetails(
                id=flat_id,
                title=title_text,
                link=link,
                details=details,
                wbs_required=wbs_required,
                source="Gewobag",
            )
        except Exception as e:
            logger.error(f"Error extracting flat details from Gewobag: {e}")
            return None
