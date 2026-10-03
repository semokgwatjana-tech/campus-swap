from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user

from app.marketplace import marketplace_bp
from app.extensions import db
from app.forms import ListingForm, ReportForm, SearchForm
from app.models import (
    Listing, ListingImage, Category, ListingStatus, ListingType,
    ListingCondition, Report, Wishlist
)
from app.utils import save_uploaded_image
from app.marketplace.ai_features import suggest_price, generate_listing_from_image, smart_search


# ---------------------------------------------------------------------------
# Browse / Search
# ---------------------------------------------------------------------------

@marketplace_bp.route("/browse")
def browse():
    form = SearchForm(request.args)
    form.category.choices = [("", "All Categories")] + [
        (c.slug, c.name) for c in Category.query.order_by(Category.name).all()
    ]

    query = Listing.query.filter(Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.RESERVED]))

    q = request.args.get("q", "").strip()
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Listing.title.ilike(like), Listing.description.ilike(like)))

    category_slug = request.args.get("category", "")
    if category_slug:
        category = Category.query.filter_by(slug=category_slug).first()
        if category:
            query = query.filter(Listing.category_id == category.id)

    campus = request.args.get("campus", "")
    if campus:
        query = query.filter(Listing.campus == campus)

    condition = request.args.get("condition", "")
    if condition:
        query = query.filter(Listing.condition == ListingCondition(condition))

    listing_type = request.args.get("listing_type", "")
    if listing_type:
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
        Listing.query.filter_by(listing_type=ListingType.DONATE, status=ListingStatus.ACTIVE)
        .order_by(Listing.posted_at.desc())
        .all()
    )
    return render_template("marketplace/donations.html", listings=listings)


@marketplace_bp.route("/swap-board")
def swap_board():
    listings = (
        Listing.query.filter_by(listing_type=ListingType.SWAP, status=ListingStatus.ACTIVE)
        .order_by(Listing.posted_at.desc())
        .all()
    )
    return render_template("marketplace/swap_board.html", listings=listings)


@marketplace_bp.route("/api/smart-search")
def api_smart_search():
    query_text = request.args.get("q", "")
    if not query_text.strip():
        return jsonify({"error": "empty query"}), 400
    return jsonify(smart_search(query_text))


# ---------------------------------------------------------------------------
# Listing detail
# ---------------------------------------------------------------------------

@marketplace_bp.route("/listing/<int:listing_id>")
def listing_detail(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    listing.release_reservation_if_expired()
    listing.views_count = (listing.views_count or 0) + 1
    db.session.commit()

    related = (
        Listing.query.filter(
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
    form = ReportForm()
    if form.validate_on_submit():
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


@marketplace_bp.route("/api/ai/suggest-price")
@login_required
def api_suggest_price():
    category_slug = request.args.get("category", "textbooks")
    condition = request.args.get("condition", "Good")
    title = request.args.get("title", "")
    return jsonify(suggest_price(category_slug, condition, title))


@marketplace_bp.route("/api/ai/generate-listing", methods=["POST"])
@login_required
def api_generate_listing():
    hint = request.form.get("hint_text", "")
    # In production the uploaded photo (request.files.get('photo')) would be
    # sent to a vision-capable AI model here.
    return jsonify(generate_listing_from_image(hint_text=hint))


@marketplace_bp.route("/listing/<int:listing_id>/edit", methods=["GET", "POST"])
@login_required
def edit_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    if listing.seller_id != current_user.id and not current_user.is_admin:
        flash("You can only edit your own listings.", "danger")
        return redirect(url_for("marketplace.listing_detail", listing_id=listing.id))

    form = ListingForm(obj=listing)
    form.category_id.choices = [(c.id, c.name) for c in Category.query.order_by(Category.name).all()]
    if request.method == "GET":
        form.listing_type.data = listing.listing_type.value
        form.condition.data = listing.condition.value

    if form.validate_on_submit():
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
    return render_template("marketplace/my_listings.html", listings=listings)
