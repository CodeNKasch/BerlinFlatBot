import logging
from typing import List, Optional, Dict, Tuple, Set
from dataclasses import dataclass
import aiohttp
from bs4 import BeautifulSoup
import asyncio
from datetime import datetime, timedelta
import re
from urllib.parse import quote
import gc
import ssl
import certifi

logger = logging.getLogger(__name__)

# Global session for connection pooling
_global_session = None
# Global set to track seen flat IDs
_seen_flat_ids: Set[str] = set()

async def get_session() -> aiohttp.ClientSession:
    global _global_session
    if _global_session is None or _global_session.closed:
        # Create a custom SSL context that uses system certificates
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        
        # Configure TCP connector with optimized settings
        connector = aiohttp.TCPConnector(
            ssl=ssl_context,
            limit=5,  # Limit concurrent connections
            ttl_dns_cache=300,  # Cache DNS results for 5 minutes
            use_dns_cache=True,
            force_close=False,  # Keep connections alive
            enable_cleanup_closed=True
        )
        
        # Create session with optimized settings
        _global_session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=30),
            headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.4 Safari/605.1.15',
                'Accept': '*/*',
                'Accept-Language': 'en-GB,en;q=0.9',
            }
        )
    return _global_session

async def close_session():
    global _global_session
    if _global_session and not _global_session.closed:
        await _global_session.close()
        _global_session = None

def reset_seen_flats():
    """Reset the set of seen flat IDs."""
    global _seen_flat_ids
    _seen_flat_ids.clear()

@dataclass
class FlatDetails:
    id: str
    title: str
    link: Optional[str]
    details: Dict[str, str]
    wbs_required: bool
    source: str

    def __post_init__(self):
        # Optimize memory usage by converting to tuple for immutable data
        self.details = tuple(sorted(self.details.items()))

    def is_duplicate(self) -> bool:
        """Check if this flat has been seen before."""
        global _seen_flat_ids
        if self.id in _seen_flat_ids:
            return True
        _seen_flat_ids.add(self.id)
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
        self._parser = 'html.parser'  # Use html.parser instead of lxml for lower memory usage

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

    async def _make_request(self, session: aiohttp.ClientSession, method: str = 'GET', **kwargs) -> Tuple[bool, str]:
        if self._check_backoff():
            raise WebsiteUnavailableError(f"Website is in backoff period. Retry in {self.backoff_time} seconds.")

        for attempt in range(self.max_retries):
            try:
                async with session.request(method, self.url, **kwargs) as response:
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
                await asyncio.sleep(2 ** attempt)
            except aiohttp.ClientError as e:
                if attempt == self.max_retries - 1:
                    self._update_backoff()
                    raise WebsiteUnavailableError(f"Connection error: {str(e)}")
                await asyncio.sleep(2 ** attempt)

        return False, ""

    def _parse_html(self, html: str) -> BeautifulSoup:
        # Use html.parser for lower memory usage
        return BeautifulSoup(html, self._parser)

    def _cleanup(self):
        # Force garbage collection after processing
        gc.collect()

    def _filter_duplicates(self, flats: List[FlatDetails]) -> List[FlatDetails]:
        """Filter out duplicate flats based on their IDs."""
        return [flat for flat in flats if not flat.is_duplicate()]

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

                # Find all flat elements
                flat_elements = soup.find_all("article", class_="article-list__item article-list__item--immosearch")
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
                details["Adresse"] = address_element.text.strip()

            # Extract tags (e.g., Balkon/Loggia, Aufzug)
            tags = flat_element.find_all("li", class_="article__tags-item")
            if tags:
                details["Tags"] = ", ".join(tag.text.strip() for tag in tags)

            # Extract properties (e.g., Zimmer, Wohnfläche, Verfügbarkeit)
            properties = flat_element.find_all("li", class_="article__properties-item")
            for prop in properties:
                svg = prop.find("svg")
                if svg and "i-room" in svg.get("xlink:href", ""):
                    details["Zimmeranzahl"] = prop.find("span", class_="text").text.strip()
                elif svg and "i-squares" in svg.get("xlink:href", ""):
                    details["Wohnfläche"] = prop.find("span", class_="text").text.strip()
                elif svg and "i-calendar2" in svg.get("xlink:href", ""):
                    details["Verfügbarkeit"] = prop.find("span", class_="text").text.strip()

            # Extract price
            price_element = flat_element.find("div", class_="article__price-tag")
            if price_element:
                price_text = price_element.find("span", class_="price")
                if price_text:
                    details["Warmmiete"] = price_text.text.strip()

            # Determine if WBS is required
            wbs_required = "WBS" in title_text.upper()

            # Extract properties (e.g., Zimmer, Wohnfläche, Verfügbarkeit)
            properties = flat_element.find_all("li", class_="article__properties-item")
            for prop in properties:
                svg = prop.find("svg")
                if svg and "i-room" in svg.get("xlink:href", ""):
                    details["Zimmeranzahl"] = prop.find("span", class_="text").text.strip()
                elif svg and "i-squares" in svg.get("xlink:href", ""):
                    details["Wohnfläche"] = prop.find("span", class_="text").text.strip()
                elif svg and "i-calendar2" in svg.get("xlink:href", ""):
                    details["Verfügbarkeit"] = prop.find("span", class_="text").text.strip()

            # Extract price
            price_element = flat_element.find("div", class_="article__price-tag")
            if price_element:
                price_text = price_element.find("span", class_="price")
                if price_text:
                    details["Warmmiete"] = price_text.text.strip()

            # Determine if WBS is required
            wbs_required = "WBS" in title_text.upper()

            # Return the flat details
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

                # Find all flat elements
                flat_elements = soup.find_all("div", class_="teaserList__item")
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
                details["Adresse"] = address_element.text.strip()

            # Extract region
            region_element = flat_element.find("span", class_="meta__region")
            if region_element:
                details["Region"] = region_element.text.strip()

            # Extract apartment info (rooms, size, price)
            info_element = flat_element.find("div", class_="apartment__info")
            if info_element:
                info_spans = info_element.find_all("span")
                if len(info_spans) >= 3:
                    details["Zimmeranzahl"] = info_spans[0].text.strip()
                    details["Wohnfläche"] = info_spans[1].text.strip()
                    details["Warmmiete"] = info_spans[2].text.strip()

            # Check for WBS requirement
            wbs_required = "WBS" in title_text.upper()

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

                # Find all flat elements
                flat_elements = soup.find_all("article", class_="angebot-big-box")
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
                    details["Region"] = region_row.find("td").text.strip()

                # Extract address
                address_row = info_table.find("tr", class_="angebot-address")
                if address_row:
                    address_element = address_row.find("address")
                    if address_element:
                        details["Adresse"] = address_element.text.strip()

                # Extract area info
                area_row = info_table.find("tr", class_="angebot-area")
                if area_row:
                    details["Fläche"] = area_row.find("td").text.strip()

                # Extract availability
                availability_row = info_table.find("tr", class_="availability")
                if availability_row:
                    details["Frei ab"] = availability_row.find("td").text.strip()

                # Extract costs
                kosten_row = info_table.find("tr", class_="angebot-kosten")
                if kosten_row:
                    details["Gesamtmiete"] = kosten_row.find("td").text.strip()

                # Extract characteristics
                characteristics_row = info_table.find("tr", class_="angebot-characteristics")
                if characteristics_row:
                    characteristics = []
                    for li in characteristics_row.find_all("li"):
                        characteristics.append(li.text.strip())
                    if characteristics:
                        details["Besondere Eigenschaften"] = ", ".join(characteristics)

            # Check for WBS requirement
            wbs_required = "WBS" in title_text.upper()

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

class StadtUndLandScraper(BaseScraper):
    async def fetch_flats(self) -> List[FlatDetails]:
        logger.info("Fetching flats from Stadt und Land...")
        try:
            session = await get_session()
            headers = {
                'Content-Type': 'text/plain;charset=UTF-8',
                'Cache-Control': 'max-age=0',
                'Connection': 'keep-alive',
                'Host': 'd2396ha8oiavw0.cloudfront.net',
                'Origin': 'https://stadtundland.de',
                'Referer': 'https://stadtundland.de/wohnungssuche',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'cross-site',
            }
            
            api_url = "https://d2396ha8oiavw0.cloudfront.net/sul-main/immoSearch"
            payload = {
                "offset": 0,
                "cat": "wohnung"
            }
            
            # Make the API request directly instead of using _make_request
            async with session.post(
                api_url,
                json=payload,
                headers=headers,
                timeout=30,
                allow_redirects=True
            ) as response:
                if response.status != 200:
                    logger.error(f"API response status: {response.status}")
                    logger.error(f"API response headers: {response.headers}")
                    response_text = await response.text()
                    logger.error(f"API response text: {response_text}")
                    raise WebsiteUnavailableError(f"API returned status code {response.status}")
                
                try:
                    data = await response.json()
                    flats_data = data.get("data", [])
                    
                    if not flats_data:
                        return []
                    
                    flats = []
                    for flat_data in flats_data:
                        flat_details = self._extract_flat_details(flat_data)
                        if flat_details:
                            flats.append(flat_details)

                    # Filter out duplicates
                    flats = self._filter_duplicates(flats)
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
            address = ", ".join(filter(None, [
                address_data.get("street", ""),
                address_data.get("house_number", ""),
                address_data.get("precinct", ""),
                address_data.get("postal_code", ""),
                address_data.get("city", "")
            ]))
            
            # URL encode the flat ID
            encoded_id = quote(flat_id, safe='')
            link = f"https://stadtundland.de/wohnungssuche/{encoded_id}"

            # Optimize details dictionary construction
            costs_data = flat_data.get("costs", {})
            details = {
                "Adresse": address,
                "Zimmeranzahl": str(details_data.get("rooms", "")),
                "Wohnfläche": f"{details_data.get('livingSpace', '')} m²",
                "Kaltmiete": f"{costs_data.get('coldRent', '')} €",
                "Nebenkosten": f"{costs_data.get('additionalCosts', '')} €",
                "Heizkosten": f"{costs_data.get('heatingCosts', '')} €",
                "Gesamtmiete": f"{costs_data.get('totalRent', '')} €",
            }

            # Optimize special features list
            special_features = []
            if details_data.get("wheelchairFriendly"): special_features.append("Rollstuhlgerecht")
            if details_data.get("seniorsFriendly"): special_features.append("Seniorengerecht")
            if details_data.get("barrierFree"): special_features.append("Barrierefrei")
            if special_features:
                details["Besondere Eigenschaften"] = ", ".join(special_features)

            wbs_required = "WBS" in title.upper() or any("WBS" in str(v).upper() for v in details.values())

            return FlatDetails(
                id=flat_id,
                title=title,
                link=link,
                details=details,
                wbs_required=wbs_required,
                source="Stadt und Land"
            )
            
        except Exception as e:
            logger.error(f"Error extracting flat details: {e}")
            return None 
