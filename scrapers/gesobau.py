"""Gesobau scraper."""

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


class GesobauScraper(BaseScraper):
    async def fetch_flats(self) -> List[FlatDetails]:
        logger.info("Fetching flats from Gesobau...")
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
                flat_elements = soup.find_all("div", class_="teaserList__item")
                logger.info(f"Found {len(flat_elements)} flat elements in HTML")

                for flat in flat_elements:
                    flat_details = self._extract_flat_details(flat)
                    if flat_details:
                        flats.append(flat_details)

                # Filter out duplicates within this fetch
                flats = self._filter_duplicates(flats)
                return flats
        except (WebsiteUnavailableError, HighTrafficError) as e:
            logger.error(f"Error fetching flats from Gesobau: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching flats from Gesobau: {e}")
            return []

    def _extract_flat_details(self, flat_element) -> Optional[FlatDetails]:
        try:
            # Extract the unique ID from the article's ID attribute or generate one
            flat_id = flat_element.get("id", str(hash(flat_element.text)))

            # Extract the title and link
            title_element = flat_element.find("h3", class_="basicTeaser__title")
            if not title_element:
                return None

            title_link = title_element.find("a")
            if not title_link:
                return None

            title_text = title_link.text.strip()
            link = title_link.get("href")
            if link and not link.startswith("http"):
                link = f"https://www.gesobau.de{link}"

            # Extract details
            details = {}

            # Extract address
            address_element = flat_element.find("p", class_="basicTeaser__text")
            if address_element:
                details[StandardFields.ADDRESS] = address_element.text.strip()

            # Extract region
            region_element = flat_element.find("span", class_="meta__region")
            if region_element:
                details[StandardFields.DISTRICT] = region_element.text.strip()

            # Extract apartment info (rooms, size, price)
            info_element = flat_element.find("div", class_="apartment__info")
            if info_element:
                info_spans = info_element.find_all("span")
                if len(info_spans) >= 3:
                    details[StandardFields.ROOMS] = info_spans[0].text.strip()
                    details[StandardFields.AREA] = info_spans[1].text.strip()
                    details[StandardFields.RENT_WARM] = info_spans[2].text.strip()

            # Check for WBS requirement - check title and all details
            wbs_sources = [title_text] + [str(v) for v in details.values() if v]
            wbs_required = any(check_wbs_required(source) for source in wbs_sources)

            return FlatDetails(
                id=flat_id,
                title=title_text,
                link=link,
                details=details,
                wbs_required=wbs_required,
                source="Gesobau",
            )
        except Exception as e:
            logger.error(f"Error extracting flat details from Gesobau: {e}")
            return None
