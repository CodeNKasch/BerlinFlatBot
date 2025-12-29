"""Global session management for HTTP requests."""

import ssl

import aiohttp
import certifi

# Global session for connection pooling
_global_session = None


async def get_session() -> aiohttp.ClientSession:
    """Get or create the global aiohttp session."""
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
            enable_cleanup_closed=True,
        )

        # Create session with optimized settings
        _global_session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=30),
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.4 Safari/605.1.15",
                "Accept": "*/*",
                "Accept-Language": "en-GB,en;q=0.9",
            },
        )
    return _global_session


async def close_session():
    """Close the global session."""
    global _global_session
    if _global_session and not _global_session.closed:
        await _global_session.close()
        _global_session = None
