import json
import logging
from datetime import datetime, timedelta, timezone

import redis
from botocore.signers import CloudFrontSigner
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from config import CLOUDFRONT_DOMAIN, CLOUDFRONT_KEY_ID, CLOUDFRONT_PRIVATE_KEY_PATH, REDIS_URL

logger = logging.getLogger("radio.cloudfront")

# Load private key once at module load
_private_key = None

# Redis client (lazy initialized)
_redis_client = None
CACHE_KEY_PREFIX = "signed_url_radio:"
BUFFER_SECONDS = 3600  # 1 hour buffer before expiry


def _get_private_key():
    global _private_key
    if _private_key is None:
        with open(CLOUDFRONT_PRIVATE_KEY_PATH, "rb") as f:
            _private_key = load_pem_private_key(f.read(), password=None)
        logger.info("Loaded CloudFront private key")
    return _private_key


def _get_redis_client():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        logger.info("Initialized Redis client for URL caching")
    return _redis_client


def _rsa_signer(message: bytes) -> bytes:
    """RSA signer function for CloudFrontSigner."""
    key = _get_private_key()
    assert isinstance(key, RSAPrivateKey)
    return key.sign(message, padding.PKCS1v15(), hashes.SHA1())


def _generate_signed_url(filename: str, expires_days: int = 3) -> tuple[str, int]:
    """
    Generate a new CloudFront signed URL.

    Returns:
        Tuple of (signed_url, expires_at_timestamp)
    """
    url = f"https://{CLOUDFRONT_DOMAIN}/audio/{filename}"
    expires = datetime.now(timezone.utc) + timedelta(days=expires_days)
    expires_timestamp = int(expires.timestamp())

    signer = CloudFrontSigner(CLOUDFRONT_KEY_ID, _rsa_signer)
    signed_url = signer.generate_presigned_url(url, date_less_than=expires)

    return signed_url, expires_timestamp


def get_signed_url(filename: str, expires_days: int = 3) -> str:
    """
    Get a CloudFront signed URL for an audio file, using cache when available.

    Args:
        filename: The audio filename (e.g., "haunting_tavern_remst_fullmix.mp3")
        expires_days: URL validity in days (default: 3)

    Returns:
        Signed CloudFront URL (cached or freshly generated)
    """
    cache_key = f"{CACHE_KEY_PREFIX}{filename}"
    now = int(datetime.now(timezone.utc).timestamp())

    # Try to get from cache
    try:
        client = _get_redis_client()
        cached = client.get(cache_key)
        if cached:
            data = json.loads(cached)
            expires_at = data["expires_at"]
            # Return cached URL if it has more than 1 hour left
            if expires_at - now > BUFFER_SECONDS:
                logger.debug(f"Cache hit for {filename}")
                return data["url"]
            logger.debug(f"Cache expired (within buffer) for {filename}")
    except Exception as e:
        logger.warning(f"Redis error, falling back to fresh URL: {e}")
        # Fall through to generate fresh URL
        signed_url, _ = _generate_signed_url(filename, expires_days)
        return signed_url

    # Generate new URL and cache it
    signed_url, expires_at = _generate_signed_url(filename, expires_days)

    try:
        ttl_seconds = expires_at - now
        client.set(
            cache_key,
            json.dumps({"url": signed_url, "expires_at": expires_at}),
            ex=ttl_seconds,
        )
        logger.debug(f"Cached signed URL for {filename}, TTL={ttl_seconds}s")
    except Exception as e:
        logger.warning(f"Failed to cache URL: {e}")

    return signed_url
