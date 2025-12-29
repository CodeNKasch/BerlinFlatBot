"""Base classes and utilities for apartment scrapers."""

import asyncio
import gc
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# Standard field names for FlatDetails.details dictionary
# All scrapers should use these canonical field names
class StandardFields:
    ADDRESS = "address"              # Full address (street, number, postal code, city)
    DISTRICT = "district"            # District/Region/Bezirk
    ROOMS = "rooms"                  # Number of rooms (Zimmer/Zimmeranzahl)
    AREA = "area"                    # Living area in m² (Wohnfläche/Fläche)
    RENT_COLD = "rent_cold"          # Cold rent (Kaltmiete)
    RENT_WARM = "rent_warm"          # Warm rent (Warmmiete/Gesamtmiete)
    RENT_ADDITIONAL = "rent_additional"  # Additional costs (Nebenkosten)
    RENT_HEATING = "rent_heating"    # Heating costs (Heizkosten)
    RENT_TOTAL = "rent_total"        # Total rent (if different from warm)
    AVAILABLE_FROM = "available_from"  # Availability date (Verfügbar ab/Frei ab)
    PROVIDER = "provider"            # Housing company/provider (Anbieter)
    OBJECT_ID = "object_id"          # Object/apartment ID (Objekt-ID)
    FEATURES = "features"            # Special features/amenities (Tags/Besondere Eigenschaften)


def check_wbs_required(text: str) -> bool:
    """
    Check if WBS is required based on text content.
    Logic:
    - If WBS not mentioned at all -> False (no WBS required)
    - If WBS mentioned AND explicitly negated (kein WBS, ohne WBS) -> False
    - If WBS mentioned but NOT negated -> True (WBS required)
    """
    if not text:
        return False

    text_lower = text.lower()

    # Check if WBS is mentioned at all
    if not re.search(r"\bwbs\b|wohnberechtigungsschein", text_lower):
        return False  # No WBS mentioned = no WBS required

    # Patterns that indicate WBS is NOT required
    not_required_patterns = [
        "kein wbs",
        "ohne wbs",
        "no wbs",
        "wbs nicht erforderlich",
        "wbs nicht notwendig",
        "wbs nicht nötig",
        "ohne wohnberechtigungsschein",
        "kein wohnberechtigungsschein",
    ]

    for pattern in not_required_patterns:
        if pattern in text_lower:
            return False

    # Check if it's followed by negation indicators
    if re.search(r"\bwbs\b[:\s-]*(nein|no|nicht)", text_lower):
        return False

    # WBS is mentioned but not negated -> assume required
    return True


@dataclass
class FlatDetails:
    id: str
    title: str
    link: Optional[str]
    details: Dict[str, str]
    wbs_required: bool
    source: str

    def __post_init__(self):
        # Convert details to a regular dictionary if it's a tuple
        if isinstance(self.details, tuple):
            self.details = dict(self.details)

    def is_duplicate(self) -> bool:
        """Check if this flat has been seen before."""
        from .cache import is_flat_seen, mark_flat_seen

        if is_flat_seen(self.id):
            return True
        mark_flat_seen(self.id)
        return False


class ScraperError(Exception):
    """Base exception for scraper errors"""
    pass


class WebsiteUnavailableError(ScraperError):
    """Raised when a website is temporarily unavailable"""
    pass


class HighTrafficError(ScraperError):
    """Raised when a website is experiencing high traffic"""
    pass


class BaseScraper:
    def __init__(self, url: str):
        self.url = url
        self.last_error_time: Optional[datetime] = None
        self.error_count: int = 0
        self.backoff_time: int = 60
        self.max_backoff_time: int = 3600
        self.max_retries: int = 3
        self._parser = (
            "html.parser"  # Use html.parser instead of lxml for lower memory usage
        )

    async def fetch_flats(self) -> List[FlatDetails]:
        """Base method to fetch flats from a website."""
        raise NotImplementedError("Subclasses must implement fetch_flats")

    def _check_backoff(self) -> bool:
        """Check if we should back off from making requests."""
        if self.last_error_time is None:
            return False

        time_since_error = datetime.now() - self.last_error_time
        if time_since_error < timedelta(seconds=self.backoff_time):
            return True
        return False

    def _update_backoff(self):
        """Update backoff time based on error count."""
        self.error_count += 1
        self.backoff_time = min(self.backoff_time * 2, self.max_backoff_time)
        self.last_error_time = datetime.now()

    def _reset_backoff(self):
        """Reset backoff time after successful request."""
        self.error_count = 0
        self.backoff_time = 60
        self.last_error_time = None

    async def _make_request(
        self, session: aiohttp.ClientSession, method: str = "GET", **kwargs
    ) -> Tuple[bool, str]:
        if self._check_backoff():
            raise WebsiteUnavailableError(
                f"Website is in backoff period. Retry in {self.backoff_time} seconds."
            )

        for attempt in range(self.max_retries):
            try:
                async with session.request(method, self.url, **kwargs) as response:
                    if response.status == 200:
                        self._reset_backoff()
                        return True, await response.text()
                    elif response.status == 503 or response.status == 429:
                        self._update_backoff()
                        raise HighTrafficError(
                            f"Website experiencing high traffic. Status: {response.status}"
                        )
                    else:
                        self._update_backoff()
                        raise WebsiteUnavailableError(
                            f"Website unavailable. Status: {response.status}"
                        )
            except asyncio.TimeoutError:
                if attempt == self.max_retries - 1:
                    self._update_backoff()
                    raise WebsiteUnavailableError("Request timed out")
                await asyncio.sleep(2**attempt)
            except aiohttp.ClientError as e:
                if attempt == self.max_retries - 1:
                    self._update_backoff()
                    raise WebsiteUnavailableError(f"Connection error: {str(e)}")
                await asyncio.sleep(2**attempt)

        return False, ""

    def _parse_html(self, html: str) -> BeautifulSoup:
        # Use html.parser for lower memory usage
        return BeautifulSoup(html, self._parser)

    def _cleanup(self):
        # Force garbage collection after processing
        gc.collect()

    def _filter_duplicates(self, flats: List[FlatDetails]) -> List[FlatDetails]:
        """Filter out duplicate flats based on their IDs within this batch only."""
        # Remove duplicates within this batch using a local set
        # Do NOT use global _seen_flat_ids here - that's handled by the bot
        seen_in_batch = set()
        unique_flats = []

        for flat in flats:
            if flat.id not in seen_in_batch:
                seen_in_batch.add(flat.id)
                unique_flats.append(flat)
            else:
                logger.debug(f"Filtered duplicate within batch: {flat.id} - {flat.title}")

        return unique_flats
