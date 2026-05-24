from app.shared.quotas import TIER_LIMITS


def get_tier_limits(tier: str) -> dict:
    return TIER_LIMITS.get(tier, TIER_LIMITS["trial"])
