"""
Who can see and deal with whom.

Campus Swap has two sides: learners (under 18) and adults. The sides never see each
other's listings or profiles, never message each other and never trade. The rule
is applied here, on the server, in one place, so a hidden page cannot be reached by
typing its address.

  * a visitor who is not signed in sees the adult side only
  * a learner sees learners only; an adult sees adults only
  * administrators can see everything (they need to, to keep people safe)
  * a person with no date of birth yet is on neither side until they enter one
"""

from datetime import date

from app.age_rules import eighteen_cutoff
from app.models import User, Listing, ListingStatus


def viewer_side(viewer):
    """'learner', 'adult', or None for an administrator (sees both)."""
    if viewer is None or not getattr(viewer, "is_authenticated", False):
        return "adult"
    if viewer.is_admin:
        return None
    return viewer.side or "adult"


def side_clause(side, today=None):
    """A database condition on User.date_of_birth for one side (None = no restriction)."""
    if side is None:
        return User.id.isnot(None)
    cutoff = eighteen_cutoff(today or date.today())
    return User.date_of_birth > cutoff if side == "learner" else User.date_of_birth <= cutoff


def visible_listings(viewer=None):
    """Listings the viewer may see: from sellers on the same side whose account is active
    and not paused. Add your own filters (status, category...) to the result."""
    query = (Listing.query.join(User, User.id == Listing.seller_id)
             .filter(side_clause(viewer_side(viewer)), User.is_active_account.is_(True),
                     User.deleted_at.is_(None), User.parent_paused.is_(False)))
    return query


def can_view_listing(viewer, listing):
    """True if this viewer may open this listing."""
    if viewer is not None and getattr(viewer, "is_authenticated", False):
        if viewer.is_admin or viewer.id == listing.seller_id:
            return True
    # Anyone else only sees listings that are live or finished, never removed or waiting for approval.
    if listing.status in (ListingStatus.REMOVED, ListingStatus.PENDING_APPROVAL):
        return False
    seller = listing.seller
    if seller is None or not seller.is_active_account or seller.deleted_at or seller.parent_paused:
        return False
    side = viewer_side(viewer)
    return side is None or seller.side == side


def same_side(user_a, user_b):
    """True if two people may message and trade (administrators are not restricted)."""
    if user_a.is_admin or user_b.is_admin:
        return True
    return user_a.side is not None and user_a.side == user_b.side


def can_view_profile(viewer, profile_user):
    if viewer is not None and getattr(viewer, "is_authenticated", False):
        if viewer.is_admin or viewer.id == profile_user.id:
            return True
    if profile_user.deleted_at or not profile_user.is_active_account or profile_user.side is None:
        return False
    side = viewer_side(viewer)
    return side is None or profile_user.side == side
