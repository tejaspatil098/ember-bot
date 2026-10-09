from .admin import router as admin_router
from .leaderboard import router as leaderboard_router
from .referral import router as referral_router
from .start import router as start_router
from .support import router as support_router
from .verification import router as verification_router

__all__ = [
    "admin_router",
    "leaderboard_router",
    "referral_router",
    "start_router",
    "support_router",
    "verification_router",
]
