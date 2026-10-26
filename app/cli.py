"""
Custom Flask CLI commands.

Usage (from the project root, with the virtualenv active):
    flask --app run.py init-db        # create all tables
    flask --app run.py init-data      # add the categories and badges (no users, no listings)
    flask --app run.py create-admin --email you@example.com       # asks for the password, nothing typed is echoed
    flask --app run.py reset-password --email admin@campusswap.app   # prompts, nothing typed is echoed
    flask --app run.py clear-demo-data                                # removes the old demo students from earlier versions
"""

import click

from app.extensions import db


def register_cli_commands(app):

    @app.cli.command("init-db")
    def init_db():
        """Create all database tables."""
        db.create_all()
        from app.seed import load_reference_data
        load_reference_data()
        click.echo("Database tables created, with the categories and badges the app needs.")

    @app.cli.command("upgrade-db")
    def upgrade_db():
        """Bring an EXISTING database up to date: creates the new tables and adds
        the new columns to the users table. Safe to run more than once, and it
        never deletes or changes existing data."""
        from sqlalchemy import inspect, text

        db.create_all()   # creates only tables that do not exist yet
        new_columns = [
            ("username", "VARCHAR(30)"), ("phone_number", "VARCHAR(30)"),
            ("pending_email", "VARCHAR(160)"), ("pending_email_token", "VARCHAR(100)"),
            ("pending_email_expires", "TIMESTAMP"), ("two_factor_enabled", "BOOLEAN DEFAULT FALSE"),
            ("two_factor_secret", "VARCHAR(64)"), ("recovery_codes", "TEXT"),
            ("invite_code", "VARCHAR(16)"), ("referred_by_id", "INTEGER"), ("deleted_at", "TIMESTAMP"),
        ]
        new_columns = [("users", n, d) for n, d in new_columns] + [
            ("users", "email_token_hash", "VARCHAR(64)"),
            ("users", "email_token_expires", "TIMESTAMP"),
            ("users", "email_token_sent_at", "TIMESTAMP"),
            ("users", "session_version", "INTEGER NOT NULL DEFAULT 0"),
            ("users", "date_of_birth", "DATE"),
            ("users", "parent_paused", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("users", "allow_paid_trades", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("messages", "offer_status", "VARCHAR(12)"),
            ("messages", "offer_responded_at", "TIMESTAMP"),
            ("transactions", "price_source", "VARCHAR(12) NOT NULL DEFAULT 'listing'"),
            ("transactions", "listed_price", "NUMERIC(10, 2)"),
            ("transactions", "offer_message_id", "INTEGER"),
            ("transactions", "offer_accepted_at", "TIMESTAMP"),
        ]
        inspector = inspect(db.engine)
        existing = {t: {c["name"] for c in inspector.get_columns(t)} for t in ("users", "messages", "transactions")}
        added = []
        for table, name, ddl in new_columns:
            if name not in existing[table]:
                db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                added.append(f"{table}.{name}")
        # SQLite cannot add a UNIQUE column, so uniqueness is enforced with an index.
        db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)"))
        db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_invite_code ON users (invite_code)"))
        if "users.date_of_birth" in added:
            # First upgrade to the version with email confirmation and age sides.
            # People who already have an account keep working: their email counts as
            # confirmed, and they are asked for a date of birth the next time they
            # sign in. Old reset and email-change tokens were stored readable, so
            # they are cleared (they expire within the hour anyway).
            db.session.execute(text("UPDATE users SET email_confirmed = TRUE"))
            db.session.execute(text("UPDATE users SET password_reset_token = NULL, password_reset_expires = NULL, "
                                    "pending_email = NULL, pending_email_token = NULL, pending_email_expires = NULL"))
        db.session.commit()
        from app.seed import load_reference_data
        load_reference_data()
        click.echo(f"Database is up to date. Columns added: {', '.join(added) or 'none'}.")

    @app.cli.command("init-data")
    def init_data():
        """Add the listing categories and badges. Creates no users and no listings."""
        from app.seed import load_reference_data
        load_reference_data()
        click.echo("Categories and badges are in place. No users or listings were created.")

    @app.cli.command("create-admin")
    @click.option("--email", required=True)
    @click.option("--name", default="Campus Swap Admin")
    @click.password_option(prompt="Password for the new admin (ignored when promoting an existing account)",
                           confirmation_prompt=True)
    def create_admin(email, name, password):
        """Create (or promote) an administrator account. The password is typed at a hidden
        prompt, so it never appears on screen or in shell history. Administrators must turn on
        two-step verification the first time they sign in."""
        from datetime import date
        from app.models import User, Profile, UserRole
        from app.security import password_problem

        user = User.query.filter_by(school_email=email.lower()).first()
        if user:
            user.role = UserRole.ADMIN
            user.is_verified = True
            user.email_confirmed = True
            db.session.commit()
            click.echo(f"Existing user {email} promoted to admin.")
            return

        problem = password_problem(password, email, name)
        if problem:
            raise click.ClickException(problem)

        user = User(
            full_name=name,
            student_number=f"ADMIN-{email.split('@')[0]}",
            school_email=email.lower(),
            role=UserRole.ADMIN,
            is_verified=True,
            email_confirmed=True,
            date_of_birth=date(1990, 1, 1),     # administrators are adults; not shown anywhere
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        db.session.add(Profile(user_id=user.id, campus="Main Campus"))
        db.session.commit()
        click.echo(f"Admin account created: {email}")


    @app.cli.command("reset-password")
    @click.option("--email", required=True)
    @click.password_option(prompt="New password", confirmation_prompt=True)
    def reset_password(email, password):
        """Set a new password for any account. The password is typed at a
        hidden prompt, so it never appears on screen or in shell history."""
        from app.models import User

        from app.security import password_problem

        user = User.query.filter_by(school_email=email.lower().strip()).first()
        if not user:
            raise click.ClickException(f"No account found for {email}.")
        problem = password_problem(password, user.school_email, user.full_name)
        if problem:
            raise click.ClickException(problem)
        user.set_password(password)
        user.password_reset_token = None
        user.password_reset_expires = None
        user.session_version = (user.session_version or 0) + 1      # signs the account out everywhere
        db.session.commit()
        click.echo(f"Password updated for {email}.")

    @app.cli.command("clear-demo-data")
    @click.confirmation_option(
        prompt="This permanently deletes the seeded demo students and everything "
               "connected to them (listings, messages, transactions). Continue?"
    )
    def clear_demo_data():
        """Remove ONLY the sample students that earlier versions created, plus anything
        that references them. Real accounts, admins, categories and badges
        are left alone."""
        from app.models import (
            User, Profile, Listing, ListingImage, Wishlist, Conversation, Message,
            SwapRequest, DonationRequest, Transaction, Dispute, Review,
            Notification, Report, UserBadge,
        )
        from app.models import UserSettings, Feedback

        # The four fictional students that earlier versions created with the old
        # seed command. Listed here only so they can be found and removed.
        demo_emails = ["sarah.mokoena@campusswap.app", "thabo.nkosi@campusswap.app",
                       "aisha.patel@campusswap.app", "lindiwe.dube@campusswap.app"]
        users = User.query.filter(User.school_email.in_(demo_emails)).all()
        if not users:
            click.echo("No demo students found. Nothing to delete.")
            return

        uids = [u.id for u in users]
        lids = [l.id for l in Listing.query.filter(Listing.seller_id.in_(uids)).all()]

        tx_ids = [t.id for t in Transaction.query.filter(
            (Transaction.buyer_id.in_(uids)) | (Transaction.seller_id.in_(uids))
            | (Transaction.listing_id.in_(lids))
        ).all()]
        conv_ids = [c.id for c in Conversation.query.filter(
            (Conversation.participant_one_id.in_(uids)) | (Conversation.participant_two_id.in_(uids))
            | (Conversation.listing_id.in_(lids))
        ).all()]

        def purge(model, condition):
            return model.query.filter(condition).delete(synchronize_session=False)

        # Children first, so no foreign key is left pointing at a deleted row.
        purge(Dispute, (Dispute.transaction_id.in_(tx_ids)) | (Dispute.raised_by_id.in_(uids)))
        purge(Review, (Review.transaction_id.in_(tx_ids)) | (Review.reviewer_id.in_(uids))
              | (Review.reviewee_id.in_(uids)))
        purge(Transaction, Transaction.id.in_(tx_ids))
        purge(SwapRequest, (SwapRequest.requester_id.in_(uids))
              | (SwapRequest.target_listing_id.in_(lids)) | (SwapRequest.offered_listing_id.in_(lids)))
        purge(DonationRequest, (DonationRequest.requester_id.in_(uids))
              | (DonationRequest.listing_id.in_(lids)))
        purge(Wishlist, (Wishlist.user_id.in_(uids)) | (Wishlist.listing_id.in_(lids)))
        purge(Message, (Message.conversation_id.in_(conv_ids)) | (Message.sender_id.in_(uids)))
        purge(Conversation, Conversation.id.in_(conv_ids))
        purge(Report, (Report.reporter_id.in_(uids)) | (Report.reported_user_id.in_(uids))
              | (Report.listing_id.in_(lids)))
        purge(Notification, Notification.user_id.in_(uids))
        purge(UserBadge, UserBadge.user_id.in_(uids))
        purge(UserSettings, UserSettings.user_id.in_(uids))
        purge(Feedback, Feedback.user_id.in_(uids))
        # Release any real listing a demo student had reserved.
        Listing.query.filter(Listing.reserved_by_id.in_(uids)).update(
            {"reserved_by_id": None, "reserved_until": None}, synchronize_session=False
        )
        purge(ListingImage, ListingImage.listing_id.in_(lids))
        purge(Listing, Listing.id.in_(lids))
        purge(Profile, Profile.user_id.in_(uids))
        purge(User, User.id.in_(uids))
        db.session.commit()
        click.echo(f"Removed {len(uids)} demo students and {len(lids)} demo listings.")
