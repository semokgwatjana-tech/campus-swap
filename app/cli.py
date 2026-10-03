"""
Custom Flask CLI commands.

Usage (from the project root, with the virtualenv active):
    flask --app run.py init-db        # create all tables
    flask --app run.py seed-db        # populate demo/sample data
    flask --app run.py create-admin --email admin@campusswap.app --password ChangeMe123
"""

import click

from app.extensions import db


def register_cli_commands(app):

    @app.cli.command("init-db")
    def init_db():
        """Create all database tables."""
        db.create_all()
        click.echo("Database tables created.")

    @app.cli.command("seed-db")
    def seed_db():
        """Populate the database with demo categories, users, and listings."""
        from app.seed import run_seed
        run_seed()
        click.echo("Demo data seeded successfully.")

    @app.cli.command("create-admin")
    @click.option("--email", required=True)
    @click.option("--password", required=True)
    @click.option("--name", default="Campus Swap Admin")
    def create_admin(email, password, name):
        """Create (or promote) an administrator account."""
        from app.models import User, Profile, UserRole

        user = User.query.filter_by(school_email=email.lower()).first()
        if user:
            user.role = UserRole.ADMIN
            user.is_verified = True
            db.session.commit()
            click.echo(f"Existing user {email} promoted to admin.")
            return

        user = User(
            full_name=name,
            student_number=f"ADMIN-{email.split('@')[0]}",
            school_email=email.lower(),
            role=UserRole.ADMIN,
            is_verified=True,
            email_confirmed=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        db.session.add(Profile(user_id=user.id, campus="Main Campus"))
        db.session.commit()
        click.echo(f"Admin account created: {email}")
