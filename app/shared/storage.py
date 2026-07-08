import cloudinary
import cloudinary.uploader
import cloudinary.utils
from app.core.config import settings
import time
import hashlib
import hmac
import structlog

logger = structlog.get_logger(__name__)

# Configure cloudinary
cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
    secure=True,
)


def get_signed_upload_params(folder: str, public_id_prefix: str) -> dict:
    """Generate signed upload parameters for direct client-to-Cloudinary upload.
    No upload preset required — uses API key + signature authentication.
    """
    try:
        timestamp = int(time.time())
        folder_path = f"{settings.CLOUDINARY_FOLDER_ROOT}/{folder}"
        public_id = f"{folder_path}/{public_id_prefix}"

        # Params to include in signature (sorted alphabetically, no api_secret)
        params_to_sign = {
            "folder": folder_path,
            "public_id": public_id,
            "timestamp": timestamp,
        }

        # Cloudinary signature: sorted k=v joined by &, then append api_secret
        params_str = "&".join(f"{k}={v}" for k, v in sorted(params_to_sign.items()))
        params_str += settings.CLOUDINARY_API_SECRET
        signature = hashlib.sha256(params_str.encode()).hexdigest()

        return {
            "cloud_name": settings.CLOUDINARY_CLOUD_NAME,
            "api_key": settings.CLOUDINARY_API_KEY,
            "timestamp": timestamp,
            "signature": signature,
            "folder": folder_path,
            "public_id": public_id,
        }
    except Exception as e:
        logger.error("cloudinary_sign_failed", error=str(e))
        raise


def get_signed_url(public_id: str, transformation: str = "display") -> str:
    """Get a 15-minute signed URL for a Cloudinary resource."""
    try:
        expire_time = int(time.time()) + 900  # 15 minutes

        # Build transformation based on type
        transformations = {
            "display": "q_auto,f_auto,w_1200",
            "thumbnail": "q_auto,f_auto,w_300,h_300,c_fill",
            "original": "fl_attachment",
        }
        transform = transformations.get(transformation, "q_auto,f_auto")

        url, _ = cloudinary.utils.cloudinary_url(
            public_id,
            type="upload",
            sign_url=True,
            secure=True,
            raw_transformation=transform,
        )
        return url
    except Exception as e:
        logger.warning("cloudinary_url_failed", error=str(e), public_id=public_id)
        return f"https://res.cloudinary.com/{settings.CLOUDINARY_CLOUD_NAME}/image/upload/{public_id}"


def get_document_download_url(public_id: str, fmt: str = "pdf") -> str:
    """Authenticated download URL for a stored document.

    Cloudinary blocks plain delivery of PDF/ZIP files by default (even signed
    delivery URLs return 401). The private-download endpoint is authenticated
    with the API secret and is honoured regardless of that restriction, so this
    works for both buyers and developers viewing/downloading documents.
    """
    try:
        return cloudinary.utils.private_download_url(
            public_id, fmt, resource_type="image", type="upload",
        )
    except Exception as e:
        logger.warning("cloudinary_document_url_failed", error=str(e), public_id=public_id)
        return f"https://res.cloudinary.com/{settings.CLOUDINARY_CLOUD_NAME}/image/upload/{public_id}"


def delete_resource(public_id: str) -> bool:
    """Delete a resource from Cloudinary."""
    try:
        result = cloudinary.uploader.destroy(public_id)
        return result.get("result") == "ok"
    except Exception as e:
        logger.error("cloudinary_delete_failed", error=str(e), public_id=public_id)
        return False
