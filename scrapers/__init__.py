"""Scrapers package for BerlinFlatBot.

This package contains web scrapers for various Berlin housing websites.
"""

# Base classes and utilities
from .base import (
    BaseScraper,
    FlatDetails,
    HighTrafficError,
    ScraperError,
    StandardFields,
    WebsiteUnavailableError,
    check_wbs_required,
)

# Cache management
from .cache import (
    load_seen_flats,
    mark_flat_seen,
    mark_flats_as_seen,
    reset_seen_flats,
    save_seen_flats,
)

# Session management
from .session import close_session, get_session

# Individual scrapers
from .degewo import DegewoScraper
from .gesobau import GesobauScraper
from .gewobag import GewobagScraper
from .inberlin import InBerlinWohnenScraper
from .stadtundland import StadtUndLandScraper

__all__ = [
    # Base classes and utilities
    "BaseScraper",
    "FlatDetails",
    "HighTrafficError",
    "ScraperError",
    "StandardFields",
    "WebsiteUnavailableError",
    "check_wbs_required",
    # Cache management
    "load_seen_flats",
    "mark_flat_seen",
    "mark_flats_as_seen",
    "reset_seen_flats",
    "save_seen_flats",
    # Session management
    "close_session",
    "get_session",
    # Scrapers
    "DegewoScraper",
    "GesobauScraper",
    "GewobagScraper",
    "InBerlinWohnenScraper",
    "StadtUndLandScraper",
]
