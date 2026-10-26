from flask import render_template, redirect, url_for, flash, request, jsonify, abort
from flask_login import login_required, current_user

from app.marketplace import marketplace_bp
from app.extensions import db
from app.forms import ListingForm, ReportForm, SearchForm
from app.models import (
    Listing, ListingImage, Category, ListingStatus, ListingType,
    ListingCondition, Report, ReportStatus, Wishlist
)
from app.utils import save_uploaded_image, sort_listings_for_user
from app.marketplace.price_guide import price_guide
from app.sides import visible_listings, can_view_listing


# ---------------------------------------------------------------------------
# Browse / Search
# ---------------------------------------------------------------------------

@marketplace_bp.route("/browse")
def browse():
    form = SearchForm(request.args)
    form.category.choices = [("", "All Categories")] + [
        (c.slug, c.name) for c in Category.query.order_by(Category.name).all()
    ]

    # Only listings from the viewer's own side (learners / adults), from active sellers.
    query = visible_listings(current_user).filter(Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.RESERVED]))

    q = request.args.get("q", "").strip()[:100]
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        query = query.filter(db.or_(Listing.title.ilike(like, escape="\\"),
                                    Listing.description.ilike(like, escape="\\")))

    category_slug = request.args.get("category", "")
    if category_slug:
        category = Category.query.filter_by(slug=category_slug).first()
        if category:
            query = query.filter(Listing.category_id == category.id)

    campus = request.args.get("campus", "")
    if campus:
        query = query.filter(Listing.campus == campus)

    # Unknown values in the web address are ignored instead of crashing the page.
    condition = request.args.get("condition", "")
    if condition in {c.value for c in ListingCondition}:
        query = query.filter(Listing.condition == ListingCondition(condition))

    listing_type = request.args.get("listing_type", "")
    if listing_type in {t.value for t in ListingType}:
        query = query.filter(Listing.listing_type == ListingType(listing_type))

    sort = request.args.get("sort", "newest")
    if sort == "cheapest":
        query = query.order_by(Listing.price.asc())
    elif sort == "popular":
        query = query.order_by(Listing.views_count.desc())
    else:
        query = query.order_by(Listing.posted_at.desc())

    page = request.args.get("page", 1, type=int)
    pagination = query.paginate(page=page, per_page=12, error_out=False)
    categories = Category.query.order_by(Category.name).all()

    wishlisted_ids = set()
    if current_user.is_authenticated:
        wishlisted_ids = {w.listing_id for w in Wishlist.query.filter_by(user_id=current_user.id).all()}

    return render_template(
        "marketplace/browse.html",
        form=form,
        pagination=pagination,
        listings=pagination.items,
        categories=categories,
        wishlisted_ids=wishlisted_ids,
    )


@marketplace_bp.route("/donations")
def donations():
    listings = (
        visible_listings(current_user)
        .filter(Listing.listing_type == ListingType.DONATE, Listing.status == ListingStatus.ACTIVE)
        .order_by(Listing.posted_at.desc())
        .all()
    )
    return render_template("marketplace/donations.html", listings=listings)


@marketplace_bp.route("/swap-board")
def swap_board():
    listings = (
        visible_listings(current_user)
        .filter(Listing.listing_type == ListingType.SWAP, Listing.status == ListingStatus.ACTIVE)
        .order_by(Listing.posted_at.desc())
        .all()
    )
    return render_template("marketplace/swap_board.html", listings=listings)


# ---------------------------------------------------------------------------
# Listing detail
# ---------------------------------------------------------------------------

@marketplace_bp.route("/listing/<int:listing_id>")
def listing_detail(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    # Removed, waiting for approval, or on the other side: the page does not exist for this viewer.
    if not can_view_listing(current_user, listing):
        abort(404)
    listing.release_reservation_if_expired()
    if not (current_user.is_authenticated and current_user.id == listing.seller_id):
        listing.views_count = (listing.views_count or 0) + 1
    db.session.commit()

    related = (
        visible_listings(current_user).filter(
            Listing.category_id == listing.category_id,
            Listing.id != listing.id,
            Listing.status == ListingStatus.ACTIVE,
        )
        .limit(4)
        .all()
    )
    is_wishlisted = False
    if current_user.is_authenticated:
        is_wishlisted = Wishlist.query.filter_by(
            user_id=current_user.id, listing_id=listing.id
        ).first() is not None

    report_form = ReportForm()
    return render_template(
        "marketplace/listing_detail.html",
        listing=listing,
        related=related,
        is_wishlisted=is_wishlisted,
        report_form=report_form,
    )


@marketplace_bp.route("/listing/<int:listing_id>/report", methods=["POST"])
@login_required
def report_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    if not can_view_listing(current_user, listing):
        abort(404)
    form = ReportForm()
    if listing.seller_id == current_user.id:
        flash("You cannot report your own listing.", "info")
    elif Report.query.filter_by(reporter_id=current_user.id, listing_id=listing.id,
                                status=ReportStatus.OPEN).first():
        flash("You have already reported this listing. Our team will look at it.", "info")
    elif form.validate_on_submit():
        report = Report(
            reporter_id=current_user.id,
            listing_id=listing.id,
            reported_user_id=listing.seller_id,
            reason=form.reason.data,
            details=form.details.data,
        )
        db.session.add(report)
        db.session.commit()
        flash("Thank you - this listing has been reported to our moderation team.", "success")
    else:
        flash("We couldn't submit your report. Please try again.", "danger")
    return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))


# ---------------------------------------------------------------------------
# Sell / Create listing
# ---------------------------------------------------------------------------

@marketplace_bp.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    form = ListingForm()
    form.category_id.choices = [(c.id, c.name) for c in Category.query.order_by(Category.name).all()]

    if form.validate_on_submit():
        if current_user.is_minor and not current_user.allow_paid_trades and form.listing_type.data == "sell":
            flash("Selling for money needs your parent or guardian's permission. You can list items to swap or donate.",
                  "info")
            return render_template("marketplace/sell.html", form=form)
        listing = Listing(
            seller_id=current_user.id,
            category_id=form.category_id.data,
            title=form.title.data.strip(),
            description=form.description.data.strip(),
            listing_type=ListingType(form.listing_type.data),
            condition=ListingCondition(form.condition.data),
            price=0 if form.listing_type.data != "sell" else form.price.data,
            swap_for=form.swap_for.data if form.listing_type.data == "swap" else None,
            campus=form.campus.data,
            status=ListingStatus.ACTIVE,
        )
        db.session.add(listing)
        db.session.flush()

        filename = save_uploaded_image(form.photos.data, subfolder="listings")
        if filename:
            db.session.add(ListingImage(listing_id=listing.id, filename=filename, position=0))

        db.session.commit()
        flash("Your listing is live! Students on your campus can now see it.", "success")
        return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))

    return render_template("marketplace/sell.html", form=form)


@marketplace_bp.route("/sell/preview", methods=["POST"])
@login_required
def sell_preview():
    """Returns a server-rendered preview partial so the 'Preview before
    publishing' step reflects exactly what will be shown live."""
    form = ListingForm()
    form.category_id.choices = [(c.id, c.name) for c in Category.query.order_by(Category.name).all()]
    category = None
    if form.category_id.data:
        category = Category.query.get(form.category_id.data)
    return render_template("marketplace/_listing_preview.html", form=form, category=category)


@marketplace_bp.route("/api/price-guide")
@login_required
def api_price_guide():
    """Real Campus Swap prices for similar items. See price_guide.py."""
    try:
        category_id = int(request.args.get("category_id", ""))
    except ValueError:
        return jsonify({"available": False, "message": "Choose a category first."}), 400
    return jsonify(price_guide(category_id, request.args.get("condition")))


@marketplace_bp.route("/listing/<int:listing_id>/edit", methods=["GET", "POST"])
@login_required
def edit_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    if listing.seller_id != current_user.id and not current_user.is_admin:
        flash("You can only edit your own listings.", "danger")
        return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))
    # A reserved, sold or removed item cannot change under a buyer's feet.
    if listing.status not in (ListingStatus.ACTIVE, ListingStatus.PENDING_APPROVAL):
        flash("This listing can no longer be edited because it is reserved, finished or removed.", "info")
        return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))

    form = ListingForm(obj=listing)
    form.category_id.choices = [(c.id, c.name) for c in Category.query.order_by(Category.name).all()]
    if request.method == "GET":
        form.listing_type.data = listing.listing_type.value
        form.condition.data = listing.condition.value

    if form.validate_on_submit():
        seller = listing.seller
        if seller.is_minor and not seller.allow_paid_trades and form.listing_type.data == "sell":
            flash("Selling for money needs a parent or guardian's permission. The listing can be a swap or a donation.",
                  "info")
            return render_template("marketplace/sell.html", form=form, editing=True, listing=listing)
        listing.title = form.title.data.strip()
        listing.description = form.description.data.strip()
        listing.category_id = form.category_id.data
        listing.listing_type = ListingType(form.listing_type.data)
        listing.condition = ListingCondition(form.condition.data)
        listing.price = 0 if form.listing_type.data != "sell" else form.price.data
        listing.swap_for = form.swap_for.data if form.listing_type.data == "swap" else None
        listing.campus = form.campus.data

        filename = save_uploaded_image(form.photos.data, subfolder="listings")
        if filename:
            db.session.add(ListingImage(listing_id=listing.id, filename=filename, position=0))

        db.session.commit()
        flash("Listing updated.", "success")
        return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))

    return render_template("marketplace/sell.html", form=form, editing=True, listing=listing)


@marketplace_bp.route("/listing/<int:listing_id>/delete", methods=["POST"])
@login_required
def delete_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    if listing.seller_id != current_user.id and not current_user.is_admin:
        flash("You can only remove your own listings.", "danger")
        return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))
    if listing.status not in (ListingStatus.ACTIVE, ListingStatus.PENDING_APPROVAL):
        flash("A listing cannot be removed while it is reserved or after it has been sold, swapped or donated.", "info")
        return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))
    listing.status = ListingStatus.REMOVED
    db.session.commit()
    flash("Listing removed.", "info")
    return redirect(url_for("main.dashboard"))


@marketplace_bp.route("/my-listings")
@login_required
def my_listings():
    listings = (
        Listing.query.filter_by(seller_id=current_user.id)
        .order_by(Listing.posted_at.desc())
        .all()
    )
    listings = sort_listings_for_user(listings, current_user.id)
    return render_template("marketplace/my_listings.html", listings=listings)
