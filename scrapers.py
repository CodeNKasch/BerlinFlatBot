import logging
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass
import aiohttp
from bs4 import BeautifulSoup
import asyncio
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

@dataclass
class FlatDetails:
    id: str
    title: str
    link: Optional[str]
    details: Dict[str, str]
    wbs_required: bool
    source: str  # Website source

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
        self.backoff_time: int = 60  # Initial backoff time in seconds
        self.max_backoff_time: int = 3600  # Maximum backoff time (1 hour)
        self.max_retries: int = 3

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

    async def _make_request(self, session: aiohttp.ClientSession) -> Tuple[bool, str]:
        """Make HTTP request with retry logic."""
        if self._check_backoff():
            raise WebsiteUnavailableError(f"Website is in backoff period. Retry in {self.backoff_time} seconds.")

        for attempt in range(self.max_retries):
            try:
                async with session.get(self.url, timeout=30) as response:
                    if response.status == 200:
                        self._reset_backoff()
                        return True, await response.text()
                    elif response.status == 503 or response.status == 429:
                        self._update_backoff()
                        raise HighTrafficError(f"Website experiencing high traffic. Status: {response.status}")
                    else:
                        self._update_backoff()
                        raise WebsiteUnavailableError(f"Website unavailable. Status: {response.status}")
            except asyncio.TimeoutError:
                if attempt == self.max_retries - 1:
                    self._update_backoff()
                    raise WebsiteUnavailableError("Request timed out")
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
            except aiohttp.ClientError as e:
                if attempt == self.max_retries - 1:
                    self._update_backoff()
                    raise WebsiteUnavailableError(f"Connection error: {str(e)}")
                await asyncio.sleep(2 ** attempt)

        return False, ""

class InBerlinWohnenScraper(BaseScraper):
    async def fetch_flats(self) -> List[FlatDetails]:
        logger.info("Fetching flats from InBerlinWohnen...")
        try:
            async with aiohttp.ClientSession() as session:
                success, html = await self._make_request(session)
                if not success:
                    return []

                soup = BeautifulSoup(html, "html.parser")
                flats = []

                # Check for high traffic message
                if soup.find("div", class_="error-message") and "high traffic" in soup.text.lower():
                    raise HighTrafficError("Website experiencing high traffic")

                flat_elements = soup.find_all("li", id=lambda x: x and x.startswith("flat_"))
                logger.info(f"Found {len(flat_elements)} flat elements in HTML")

                for flat in flat_elements:
                    flat_details = self._extract_flat_details(flat)
                    if flat_details:
                        flats.append(flat_details)

                return flats
        except (WebsiteUnavailableError, HighTrafficError) as e:
            logger.error(f"Error fetching flats from InBerlinWohnen: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching flats from InBerlinWohnen: {e}")
            return []

    def _extract_flat_details(self, flat_element) -> Optional[FlatDetails]:
        try:
            flat_id = flat_element.get("id", "")
            title = flat_element.find("h2")
            title_text = title.text.strip() if title else "No title"

            link = None
            link_element = flat_element.find("a", class_="org-but")
            if link_element:
                link = link_element["href"]
                if not link.startswith("http"):
                    link = f"https://inberlinwohnen.de{link}"

            details = {}
            tables = flat_element.find_all("table", class_="tb-small-data")
            for table in tables:
                for row in table.find_all("tr"):
                    th = row.find("th")
                    td = row.find("td")
                    if th and td:
                        key = th.text.strip().rstrip(":")
                        value = td.text.strip()
                        details[key] = value

            features = []
            feature_spans = flat_element.find_all("span", class_="hackerl")
            for span in feature_spans:
                features.append(span.text.strip())
            if features:
                details["Features"] = ", ".join(features)

            wbs_required = False
            wbs_text = details.get("WBS", "").lower()
            if "erforderlich" in wbs_text or "wbs" in wbs_text:
                wbs_required = True

            return FlatDetails(
                id=flat_id,
                title=title_text,
                link=link,
                details=details,
                wbs_required=wbs_required,
                source="InBerlinWohnen"
            )
        except Exception as e:
            logger.error(f"Error extracting flat details from InBerlinWohnen: {e}")
            return None

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
                if soup.find("div", class_="error-message") and "high traffic" in soup.text.lower():
                    raise HighTrafficError("Website experiencing high traffic")

                flat_elements = soup.find_all("div", class_="immo-item")
                logger.info(f"Found {len(flat_elements)} flat elements in HTML")

                for flat in flat_elements:
                    flat_details = self._extract_flat_details(flat)
                    if flat_details:
                        flats.append(flat_details)

                return flats
        except (WebsiteUnavailableError, HighTrafficError) as e:
            logger.error(f"Error fetching flats from Degewo: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching flats from Degewo: {e}")
            return []

    def _extract_flat_details(self, flat_element) -> Optional[FlatDetails]:
        try:
            flat_id = flat_element.get("data-id", str(hash(flat_element.text)))
            title_element = flat_element.find("h3", class_="immo-title")
            title_text = title_element.text.strip() if title_element else "No title"

            link = None
            link_element = flat_element.find("a", class_="immo-link")
            if link_element:
                link = link_element["href"]
                if not link.startswith("http"):
                    link = f"https://www.degewo.de{link}"

            details = {}
            details_element = flat_element.find("div", class_="immo-details")
            if details_element:
                for detail in details_element.find_all("div", class_="detail-item"):
                    key = detail.find("span", class_="label")
                    value = detail.find("span", class_="value")
                    if key and value:
                        details[key.text.strip().rstrip(":")] = value.text.strip()

            wbs_required = False
            wbs_element = flat_element.find("div", class_="wbs-badge")
            if wbs_element:
                wbs_required = "WBS" in wbs_element.text.upper()

            return FlatDetails(
                id=flat_id,
                title=title_text,
                link=link,
                details=details,
                wbs_required=wbs_required,
                source="Degewo"
            )
        except Exception as e:
            logger.error(f"Error extracting flat details from Degewo: {e}")
            return None

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
                if soup.find("div", class_="error-message") and "high traffic" in soup.text.lower():
                    raise HighTrafficError("Website experiencing high traffic")

                flat_elements = soup.find_all("div", class_="property-item")
                logger.info(f"Found {len(flat_elements)} flat elements in HTML")

                for flat in flat_elements:
                    flat_details = self._extract_flat_details(flat)
                    if flat_details:
                        flats.append(flat_details)

                return flats
        except (WebsiteUnavailableError, HighTrafficError) as e:
            logger.error(f"Error fetching flats from Gesobau: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching flats from Gesobau: {e}")
            return []

    def _extract_flat_details(self, flat_element) -> Optional[FlatDetails]:
        try:
            flat_id = flat_element.get("data-id", str(hash(flat_element.text)))
            title_element = flat_element.find("h2", class_="property-title")
            title_text = title_element.text.strip() if title_element else "No title"

            link = None
            link_element = flat_element.find("a", class_="property-link")
            if link_element:
                link = link_element["href"]
                if not link.startswith("http"):
                    link = f"https://www.gesobau.de{link}"

            details = {}
            details_element = flat_element.find("div", class_="property-details")
            if details_element:
                for detail in details_element.find_all("div", class_="detail-row"):
                    key = detail.find("span", class_="detail-label")
                    value = detail.find("span", class_="detail-value")
                    if key and value:
                        details[key.text.strip().rstrip(":")] = value.text.strip()

            wbs_required = False
            wbs_element = flat_element.find("div", class_="wbs-indicator")
            if wbs_element:
                wbs_required = "WBS" in wbs_element.text.upper()

            return FlatDetails(
                id=flat_id,
                title=title_text,
                link=link,
                details=details,
                wbs_required=wbs_required,
                source="Gesobau"
            )
        except Exception as e:
            logger.error(f"Error extracting flat details from Gesobau: {e}")
            return None

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
                if soup.find("div", class_="error-message") and "high traffic" in soup.text.lower():
                    raise HighTrafficError("Website experiencing high traffic")

                flat_elements = soup.find_all("div", class_="property-card")
                logger.info(f"Found {len(flat_elements)} flat elements in HTML")

                for flat in flat_elements:
                    flat_details = self._extract_flat_details(flat)
                    if flat_details:
                        flats.append(flat_details)

                return flats
        except (WebsiteUnavailableError, HighTrafficError) as e:
            logger.error(f"Error fetching flats from Gewobag: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching flats from Gewobag: {e}")
            return []

    def _extract_flat_details(self, flat_element) -> Optional[FlatDetails]:
        try:
            flat_id = flat_element.get("data-id", str(hash(flat_element.text)))
            title_element = flat_element.find("h3", class_="property-title")
            title_text = title_element.text.strip() if title_element else "No title"

            link = None
            link_element = flat_element.find("a", class_="property-link")
            if link_element:
                link = link_element["href"]
                if not link.startswith("http"):
                    link = f"https://www.gewobag.de{link}"

            details = {}
            details_element = flat_element.find("div", class_="property-info")
            if details_element:
                for detail in details_element.find_all("div", class_="info-item"):
                    key = detail.find("span", class_="info-label")
                    value = detail.find("span", class_="info-value")
                    if key and value:
                        details[key.text.strip().rstrip(":")] = value.text.strip()

            wbs_required = False
            wbs_element = flat_element.find("div", class_="wbs-tag")
            if wbs_element:
                wbs_required = "WBS" in wbs_element.text.upper()

            return FlatDetails(
                id=flat_id,
                title=title_text,
                link=link,
                details=details,
                wbs_required=wbs_required,
                source="Gewobag"
            )
        except Exception as e:
            logger.error(f"Error extracting flat details from Gewobag: {e}")
            return None 