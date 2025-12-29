"""InBerlinWohnen scraper."""

import json
import logging
from typing import List, Optional

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


class InBerlinWohnenScraper(BaseScraper):
    def __init__(self, url: str):
        super().__init__(url)
        # Use custom headers that mimic a real browser more closely
        self.custom_headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }

    async def fetch_flats(self) -> List[FlatDetails]:
        logger.info("Fetching flats from InBerlinWohnen...")
        try:
            session = await get_session()

            # Get the main page to establish session and get apartment data
            async with session.get(
                self.url, headers=self.custom_headers, timeout=30
            ) as response:
                if response.status != 200:
                    raise WebsiteUnavailableError(
                        f"Website unavailable. Status: {response.status}"
                    )

                html = await response.text()

            soup = BeautifulSoup(html, "html.parser")
            flats = []

            # Check for high traffic message
            if (
                soup.find("div", class_="error-message")
                and "high traffic" in soup.text.lower()
            ):
                raise HighTrafficError("Website experiencing high traffic")

            # Look for Livewire component data embedded in the HTML
            # The data is in wire:snapshot attribute or script tags
            livewire_data = None

            # Try to find wire:snapshot attribute
            livewire_elements = soup.find_all(attrs={"wire:snapshot": True})
            for element in livewire_elements:
                try:
                    livewire_data = json.loads(element.get("wire:snapshot"))
                    break
                except (json.JSONDecodeError, TypeError):
                    continue

            # Extract apartment data from Livewire components
            apartment_data = self._extract_livewire_apartments(soup)
            if apartment_data:
                logger.info(f"Found {len(apartment_data)} apartments in Livewire data")
                # Log IDs to detect duplicates at source
                apt_ids = [apt.get("id", "no-id") for apt in apartment_data]
                if len(apt_ids) != len(set(apt_ids)):
                    logger.warning(
                        f"Duplicate apartment IDs found in Livewire data: {apt_ids}"
                    )

                for apt_data in apartment_data:
                    flat_details = self._parse_livewire_apartment(apt_data)
                    if flat_details:
                        flats.append(flat_details)

            # If no Livewire data found, fall back to traditional scraping
            if not flats:
                logger.info(
                    "No Livewire data found, falling back to traditional scraping"
                )
                flat_elements = self._find_apartment_elements(soup)

                for flat in flat_elements:
                    flat_details = self._extract_flat_details(flat)
                    if flat_details:
                        flats.append(flat_details)

            # Filter out duplicates within this fetch
            flats = self._filter_duplicates(flats)
            logger.info(
                f"Successfully extracted {len(flats)} flats from InBerlinWohnen"
            )
            return flats

        except (WebsiteUnavailableError, HighTrafficError) as e:
            logger.error(f"Error fetching flats from InBerlinWohnen: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching flats from InBerlinWohnen: {e}")
            return []

    def _find_apartment_elements(self, soup):
        """Find apartment listing elements using multiple strategies."""
        flat_elements = []

        # Strategy 1: Look for elements with apartment-related content
        # Check for elements containing room and area information
        potential_containers = soup.find_all()
        for elem in potential_containers:
            text = elem.get_text()
            # Look for patterns like "2 Zimmer" and "65 m²"
            if ("zimmer" in text.lower() or "raum" in text.lower()) and "m²" in text:
                # Make sure it's not just a parent containing multiple apartments
                if (
                    len(elem.find_all(string=lambda x: x and "zimmer" in x.lower()))
                    <= 2
                ):  # Not a container with many apartments
                    flat_elements.append(elem)

        # Strategy 2: Look for structured apartment data
        if not flat_elements:
            # Look for cards or article elements
            candidates = soup.find_all(
                ["article", "div"],
                class_=lambda x: x
                and any(
                    keyword in str(x).lower()
                    for keyword in [
                        "apartment",
                        "flat",
                        "card",
                        "item",
                        "listing",
                        "teaser",
                    ]
                ),
            )

            for candidate in candidates:
                # Check if it contains apartment-like information
                text = candidate.get_text()
                if any(
                    keyword in text.lower()
                    for keyword in ["zimmer", "miete", "m²", "euro"]
                ):
                    flat_elements.append(candidate)

        # Strategy 3: Look for any elements with links to apartment details
        if not flat_elements:
            all_elements = soup.find_all()
            for elem in all_elements:
                links = elem.find_all("a", href=True)
                for link in links:
                    href = link.get("href", "")
                    if "wohnung" in href or "apartment" in href or "detail" in href:
                        # Get the parent container that likely contains the apartment info
                        parent = link.find_parent()
                        if parent and parent not in flat_elements:
                            flat_elements.append(parent)

        return flat_elements[
            :20
        ]  # Limit to first 20 to avoid processing too many false positives

    def _extract_livewire_apartments(self, soup):
        """Extract apartment data from Livewire components embedded in the HTML."""
        apartments = []
        apartment_details = {}

        # Find all Livewire elements
        livewire_elements = soup.find_all(attrs={"wire:snapshot": True})

        for element in livewire_elements:
            try:
                livewire_data = json.loads(element.get("wire:snapshot"))

                # Look for apartment item data (main apartment info)
                if "data" in livewire_data and "item" in livewire_data["data"]:
                    item_data = livewire_data["data"]["item"]
                    if isinstance(item_data, list) and len(item_data) > 0:
                        apartment = item_data[
                            0
                        ]  # Get the first (and usually only) item
                        apartments.append(apartment)

                # Look for apartment details data (address info)
                elif "data" in livewire_data and "itemId" in livewire_data["data"]:
                    item_id = livewire_data["data"]["itemId"]
                    apartment_details[item_id] = livewire_data["data"]

            except (json.JSONDecodeError, TypeError, KeyError):
                continue

        # Merge apartment data with their details
        enriched_apartments = []
        for apartment in apartments:
            apartment_id = apartment.get("id")
            if apartment_id in apartment_details:
                # Merge the detail data into the apartment data
                apartment.update(apartment_details[apartment_id])
            enriched_apartments.append(apartment)

        return enriched_apartments

    def _parse_livewire_apartment(self, apartment_data):
        """Parse apartment data from Livewire JSON format."""
        try:
            # Extract basic information
            title = apartment_data.get("title", "")
            object_id = apartment_data.get("objectId", "")
            deeplink = apartment_data.get("deeplink", "")

            # Use objectId as the unique identifier
            flat_id = object_id

            if not flat_id or not title:
                return None

            # Build details dictionary
            details = {}

            # Extract location information (can be in address object or directly in apartment_data)
            address_parts = []

            # Try direct fields first (from itemId components)
            if "street" in apartment_data:
                address_parts.append(apartment_data["street"])
            if "number" in apartment_data:
                address_parts.append(apartment_data["number"])
            if "zipCode" in apartment_data:
                address_parts.append(apartment_data["zipCode"])
            if "district" in apartment_data:
                address_parts.append(apartment_data["district"])

            # Fallback to address object
            if not address_parts and "address" in apartment_data:
                address_data = apartment_data["address"]
                if "street" in address_data:
                    address_parts.append(address_data["street"])
                if "number" in address_data:
                    address_parts.append(address_data["number"])
                if "zipCode" in address_data:
                    address_parts.append(address_data["zipCode"])
                if "district" in address_data:
                    address_parts.append(address_data["district"])

            if address_parts:
                details[StandardFields.ADDRESS] = " ".join(address_parts)

            # Extract apartment specifications
            if "rooms" in apartment_data:
                details[StandardFields.ROOMS] = str(apartment_data["rooms"]).replace(".", ",")
            if "area" in apartment_data:
                details[StandardFields.AREA] = (
                    f"{str(apartment_data['area']).replace('.', ',')} m²"
                )

            # Debug: Log all rent-related fields
            rent_fields = {k: v for k, v in apartment_data.items() if 'rent' in k.lower() or 'cost' in k.lower() or 'miete' in k.lower()}
            if rent_fields:
                logger.debug(f"Rent fields found for flat {flat_id}: {rent_fields}")

            # Helper function to parse and format rent values in German format
            def format_rent(value):
                """Parse rent value and format in German style (1.234,56 €)."""
                # Parse the value first
                if isinstance(value, (int, float)):
                    amount = float(value)
                else:
                    # If it's a string, clean it: remove dots (thousand separator) and replace comma with dot
                    value_str = str(value).replace('.', '').replace(',', '.')
                    amount = float(value_str)

                # Format with German locale style: thousand separator (.) and decimal comma (,)
                formatted = f"{amount:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
                return f"{formatted} €"

            # Extract rent information - try various field names
            if "rentNet" in apartment_data:
                details[StandardFields.RENT_COLD] = format_rent(apartment_data['rentNet'])
            if "rentTotal" in apartment_data:
                details[StandardFields.RENT_WARM] = format_rent(apartment_data['rentTotal'])
            # Also check for alternative field names
            if "rentGross" in apartment_data:
                details[StandardFields.RENT_WARM] = format_rent(apartment_data['rentGross'])
            if "additionalCosts" in apartment_data:
                details[StandardFields.RENT_ADDITIONAL] = format_rent(apartment_data['additionalCosts'])

            # Extract availability - try multiple field names
            availability_fields = ["occupationDate", "availableFrom", "available", "freeFrom", "availabilityDate", "moveInDate", "vacancy"]
            for field in availability_fields:
                if field in apartment_data and apartment_data[field]:
                    avail_value = str(apartment_data[field]).strip()
                    # Only set if not empty or placeholder values
                    if avail_value and avail_value.lower() not in ['null', 'none', '', 'n/a']:
                        details[StandardFields.AVAILABLE_FROM] = avail_value
                        break

            # Extract company information
            if "company" in apartment_data:
                company_data = apartment_data["company"]
                if isinstance(company_data, list) and len(company_data) > 0:
                    # Extract company name from the company data structure
                    company_info = company_data[0]
                    if isinstance(company_info, dict) and "name" in company_info:
                        details[StandardFields.PROVIDER] = company_info["name"].strip()
                elif isinstance(company_data, str):
                    details[StandardFields.PROVIDER] = company_data

            # Add object ID if available
            if object_id:
                details[StandardFields.OBJECT_ID] = object_id

            # Check for WBS requirement
            wbs_sources = [title]
            if "wbs" in apartment_data:
                wbs_sources.append(str(apartment_data["wbs"]))
            # Also check all detail values
            wbs_sources.extend(str(v) for v in details.values() if v)

            wbs_required = any(
                check_wbs_required(source) for source in wbs_sources if source
            )

            return FlatDetails(
                id=flat_id,
                title=title,
                link=deeplink,
                details=details,
                wbs_required=wbs_required,
                source="InBerlinWohnen",
            )

        except Exception as e:
            logger.error(f"Error parsing Livewire apartment data: {e}")
            return None

    def _extract_flat_details(self, flat_element) -> Optional[FlatDetails]:
        try:
            # Try to get a unique ID from various sources
            flat_id = flat_element.get("id", "")
            if not flat_id:
                # Generate ID from href or text content
                link_elem = flat_element.find("a", href=True)
                if link_elem:
                    flat_id = str(hash(link_elem.get("href")))
                else:
                    flat_id = str(hash(flat_element.get_text()[:100]))

            # Try multiple selectors for title
            title = None
            title_selectors = [
                "h2",
                "h3",
                "h4",
                ".title",
                ".headline",
                ".apartment-title",
            ]
            for selector in title_selectors:
                title = flat_element.find(
                    selector.replace(".", ""),
                    class_=selector.replace(".", "") if "." in selector else None,
                )
                if not title and "." in selector:
                    title = flat_element.find(class_=selector.replace(".", ""))
                if title:
                    break

            title_text = title.text.strip() if title else "No title"

            # Try multiple selectors for links
            link = None
            link_selectors = [
                ("a", "org-but"),
                ("a", "btn"),
                ("a", "button"),
                ("a", "link"),
                ("a", None),  # Any link
            ]

            for tag, class_name in link_selectors:
                if class_name:
                    link_element = flat_element.find(tag, class_=class_name)
                else:
                    link_element = flat_element.find(tag, href=True)

                if link_element and link_element.get("href"):
                    link = link_element["href"]
                    if not link.startswith("http"):
                        if link.startswith("/"):
                            link = f"https://www.inberlinwohnen.de{link}"
                        else:
                            link = f"https://www.inberlinwohnen.de/{link}"
                    break

            details = {}

            # Try extracting from tables (old format)
            tables = flat_element.find_all("table", class_="tb-small-data")
            for table in tables:
                for row in table.find_all("tr"):
                    th = row.find("th")
                    td = row.find("td")
                    if th and td:
                        key = th.text.strip().rstrip(":")
                        value = td.text.strip()
                        details[key] = value

            # Try extracting from divs with specific classes (new format)
            if not details:
                # Look for common apartment detail patterns
                detail_selectors = [
                    (".details", "div"),
                    (".apartment-details", "div"),
                    (".property-details", "div"),
                    (".info", "div"),
                    ("dl", None),  # Definition lists
                    (".data-table", "div"),
                ]

                for selector, tag in detail_selectors:
                    if tag:
                        detail_container = flat_element.find(
                            tag, class_=selector.replace(".", "")
                        )
                    else:
                        detail_container = flat_element.find(selector.replace(".", ""))

                    if detail_container:
                        # Try extracting key-value pairs
                        dt_elements = detail_container.find_all("dt")
                        dd_elements = detail_container.find_all("dd")

                        if (
                            dt_elements
                            and dd_elements
                            and len(dt_elements) == len(dd_elements)
                        ):
                            for dt, dd in zip(dt_elements, dd_elements):
                                key = dt.text.strip().rstrip(":")
                                value = dd.text.strip()
                                details[key] = value
                        break

            # Extract features/amenities
            features = []
            feature_selectors = [
                ("span", "hackerl"),
                ("li", "feature"),
                ("div", "amenity"),
                ("span", "tag"),
            ]

            for tag, class_name in feature_selectors:
                feature_spans = flat_element.find_all(tag, class_=class_name)
                for span in feature_spans:
                    feature_text = span.text.strip()
                    if feature_text:
                        features.append(feature_text)
                if features:
                    break

            if features:
                details["Features"] = ", ".join(features)

            # Try to extract basic info from text if structured data not found
            if not details:
                text_content = flat_element.get_text()

                # Look for common patterns
                import re

                # Room count
                room_match = re.search(
                    r"(\d+(?:[.,]\d+)?)\s*(?:Zimmer|Raum|rooms?)",
                    text_content,
                    re.IGNORECASE,
                )
                if room_match:
                    details[StandardFields.ROOMS] = room_match.group(1)

                # Area
                area_match = re.search(r"(\d+(?:[.,]\d+)?)\s*m²", text_content)
                if area_match:
                    details[StandardFields.AREA] = f"{area_match.group(1)} m²"

                # Price
                price_match = re.search(r"(\d+(?:[.,]\d+)?)\s*€", text_content)
                if price_match:
                    details[StandardFields.RENT_WARM] = f"{price_match.group(1)} €"

            # Check for WBS requirement - check title, details, and full element text
            wbs_sources = [title_text, flat_element.get_text()]
            # Also check all detail values
            wbs_sources.extend(str(v) for v in details.values() if v)

            wbs_required = any(
                check_wbs_required(source) for source in wbs_sources if source
            )

            # Only return valid flats
            if flat_id and title_text and title_text != "No title":
                return FlatDetails(
                    id=flat_id,
                    title=title_text,
                    link=link,
                    details=details,
                    wbs_required=wbs_required,
                    source="InBerlinWohnen",
                )
            else:
                return None

        except Exception as e:
            logger.error(f"Error extracting flat details from InBerlinWohnen: {e}")
            return None
