"""Cache management for seen flats."""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, List, Set

if TYPE_CHECKING:
    from .base import FlatDetails

logger = logging.getLogger(__name__)

# Global set to track seen flat IDs
_seen_flat_ids: Set[str] = set()
# Cache file for persisting seen flat IDs (in /dev/shm which is guaranteed RAM disk)
_SEEN_FLATS_CACHE_FILE = "/dev/shm/seen_flats_cache.json"
# Track if cache has been modified since last save
_cache_modified = False
# Counter for pending cache writes (only write every N modifications to reduce writes)
_cache_write_counter = 0
_CACHE_WRITE_THRESHOLD = 10  # Write to disk every 10 new flats


def load_seen_flats():
    """Load seen flat IDs from cache file in RAM disk (/dev/shm)."""
    global _seen_flat_ids, _cache_modified, _cache_write_counter
    cache_file = Path(_SEEN_FLATS_CACHE_FILE)
    if cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                data = json.load(f)
                # Handle both old format {"seen_ids": [...]} and new format [...]
                if isinstance(data, dict):
                    _seen_flat_ids = set(data.get("seen_ids", []))
                else:
                    _seen_flat_ids = set(data)
                logger.info(f"Loaded {len(_seen_flat_ids)} seen flat IDs from RAM cache")
                _cache_modified = False
                _cache_write_counter = 0
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load seen flats cache: {e}")
            _seen_flat_ids = set()
            _cache_modified = False
            _cache_write_counter = 0
    else:
        logger.info("No seen flats cache file found, starting fresh")
        _seen_flat_ids = set()
        _cache_modified = False
        _cache_write_counter = 0


def save_seen_flats(force: bool = False):
    """Save seen flat IDs to cache file only if modified and threshold reached.

    Args:
        force: If True, save even if threshold not reached (e.g., on shutdown)
    """
    global _seen_flat_ids, _cache_modified, _cache_write_counter

    # Only write if:
    # 1. Force flag is set (shutdown/manual save), OR
    # 2. Cache was modified AND write counter threshold reached
    if not force:
        if not _cache_modified:
            return
        if _cache_write_counter < _CACHE_WRITE_THRESHOLD:
            return

    try:
        cache_file = Path(_SEEN_FLATS_CACHE_FILE)
        # Write compact JSON (no spaces/indentation) to minimize size
        with open(cache_file, "w") as f:
            json.dump(list(_seen_flat_ids), f, separators=(',', ':'))
        logger.info(f"Saved {len(_seen_flat_ids)} seen flat IDs to RAM cache")
        _cache_modified = False
        _cache_write_counter = 0
    except IOError as e:
        logger.error(f"Failed to save seen flats cache: {e}")


def reset_seen_flats():
    """Reset the set of seen flat IDs and delete cache file."""
    global _seen_flat_ids, _cache_modified, _cache_write_counter
    _seen_flat_ids.clear()
    _cache_modified = False
    _cache_write_counter = 0
    cache_file = Path(_SEEN_FLATS_CACHE_FILE)
    if cache_file.exists():
        try:
            cache_file.unlink()
            logger.info("Cleared seen flats cache file")
        except IOError as e:
            logger.error(f"Failed to delete seen flats cache file: {e}")


def mark_flats_as_seen(flats: List['FlatDetails']):
    """Mark a list of flats as seen in the global cache."""
    global _seen_flat_ids, _cache_modified, _cache_write_counter
    for flat in flats:
        if flat.id not in _seen_flat_ids:
            _seen_flat_ids.add(flat.id)
            _cache_modified = True
            _cache_write_counter += 1


def mark_flat_seen(flat_id: str):
    """Mark a single flat ID as seen."""
    global _seen_flat_ids, _cache_modified, _cache_write_counter
    if flat_id not in _seen_flat_ids:
        _seen_flat_ids.add(flat_id)
        _cache_modified = True
        _cache_write_counter += 1


def is_flat_seen(flat_id: str) -> bool:
    """Check if a flat ID has been seen before."""
    return flat_id in _seen_flat_ids
