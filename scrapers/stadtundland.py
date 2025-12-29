"""Stadt und Land scraper."""

import logging
from typing import List, Optional
from urllib.parse import quote

from bs4 import BeautifulSoup

from .base import (
    BaseScraper,
    FlatDetails,
    HighTrafficError,
    StandardFields,
    WebsiteUnavailableError,
    check_wbs_required,
)
from .session import get_session

logger = logging.getLogger(__name__)


class StadtUndLandScraper(BaseScraper):
    async def fetch_flats(self) -> List[FlatDetails]:
        logger.info("Fetching flats from Stadt und Land...")
        try:
            session = await get_session()
            headers = {
                "Content-Type": "application/json",
                "Cache-Control": "max-age=0",
                "Connection": "keep-alive",
                "Host": "d2396ha8oiavw0.cloudfront.net",
                "Origin": "https://stadtundland.de",
                "Referer": "https://stadtundland.de/wohnungssuche",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "cross-site",
            }

            api_url = "https://d2396ha8oiavw0.cloudfront.net/sul-main/immoSearch"
            payload = {"offset": 0, "cat": "wohnung"}

            # Make the API request directly
            async with session.post(
                api_url, json=payload, headers=headers, timeout=30, allow_redirects=True
            ) as response:
                if response.status != 200:
                    logger.error(f"API response status: {response.status}")
                    logger.error(f"API response headers: {response.headers}")
                    response_text = await response.text()
                    logger.error(f"API response text: {response_text}")
                    raise WebsiteUnavailableError(
                        f"API returned status code {response.status}"
                    )

                try:
                    data = await response.json()
                    flats_data = data.get("data", [])

                    if not flats_data:
                        logger.info("No flats found in Stadt und Land response")
                        return []

                    flats = []
                    for flat_data in flats_data:
                        flat_details = self._extract_flat_details(flat_data)
                        if flat_details:
                            flats.append(flat_details)

                    # Filter out duplicates
                    flats = self._filter_duplicates(flats)
                    logger.info(f"Found {len(flats)} flats from Stadt und Land")
                    self._cleanup()
                    return flats

                except Exception as e:
                    logger.error(f"Failed to parse JSON response: {e}")
                    raise WebsiteUnavailableError("Failed to parse API response")

        except (WebsiteUnavailableError, HighTrafficError) as e:
            logger.error(f"Error fetching flats from Stadt und Land: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching flats from Stadt und Land: {e}")
            return []

    def _extract_flat_details(self, flat_data: dict) -> Optional[FlatDetails]:
        try:
            details_data = flat_data.get("details", {})
            flat_id = str(details_data.get("immoNumber", ""))
            title = flat_data.get("headline", "")

            if not flat_id or not title:
                return None

            # Optimize address construction
            address_data = flat_data.get("address", {})
            address = ", ".join(
                filter(
                    None,
                    [
                        address_data.get("street", ""),
                        address_data.get("house_number", ""),
                        address_data.get("precinct", ""),
                        address_data.get("postal_code", ""),
                        address_data.get("city", ""),
                    ],
                )
            )

            # URL encode the flat ID
            encoded_id = quote(flat_id, safe="")
            link = f"https://stadtundland.de/wohnungssuche/{encoded_id}"

            # Optimize details dictionary construction
            costs_data = flat_data.get("costs", {})
            details = {
                StandardFields.ADDRESS: address,
                StandardFields.ROOMS: str(details_data.get("rooms", "")),
                StandardFields.AREA: f"{details_data.get('livingSpace', '')} m²",
                StandardFields.RENT_COLD: f"{costs_data.get('coldRent', '')} €",
                StandardFields.RENT_ADDITIONAL: f"{costs_data.get('additionalCosts', '')} €",
                StandardFields.RENT_HEATING: f"{costs_data.get('heatingCosts', '')} €",
                StandardFields.RENT_TOTAL: f"{costs_data.get('totalRent', '')} €",
            }

            # Optimize special features list
            special_features = []
            if details_data.get("wheelchairFriendly"):
                special_features.append("Rollstuhlgerecht")
            if details_data.get("seniorsFriendly"):
                special_features.append("Seniorengerecht")
            if details_data.get("barrierFree"):
                special_features.append("Barrierefrei")
            if special_features:
                details[StandardFields.FEATURES] = ", ".join(special_features)

            wbs_sources = [title] + [str(v) for v in details.values() if v]
            wbs_required = any(check_wbs_required(source) for source in wbs_sources)

            return FlatDetails(
                id=flat_id,
                title=title,
                link=link,
                details=details,
                wbs_required=wbs_required,
                source="Stadt und Land",
            )

        except Exception as e:
            logger.error(f"Error extracting flat details: {e}")
            return None
