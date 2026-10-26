"""
Age rules: which side of Campus Swap a person is on. Pure functions, no database.

learner = under 18, adult = 18 or older. The two sides never see, message or
trade with each other. Age comes from the date of birth, so someone moves to the
adult side automatically on their 18th birthday.
"""

from datetime import date

MIN_AGE = 13       # youngest person allowed on the platform
ADULT_AGE = 18


def add_years(day, years):
    """Same calendar day `years` later (29 Feb becomes 28 Feb when needed)."""
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def age_on(dob, today):
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def side_of(dob, today):
    """'learner', 'adult', or None when the date of birth is not known."""
    if dob is None:
        return None
    return "learner" if age_on(dob, today) < ADULT_AGE else "adult"


def eighteen_cutoff(today):
    """People born on or before this date are adults today; later means under 18."""
    return add_years(today, -ADULT_AGE)


def dob_problem(dob, today):
    """Why a date of birth cannot be accepted, or None."""
    if dob is None:
        return "Enter your date of birth."
    if dob > today or age_on(dob, today) > 110:
        return "Enter a real date of birth."
    if age_on(dob, today) < MIN_AGE:
        return f"You must be at least {MIN_AGE} years old to use Campus Swap."
    return None
