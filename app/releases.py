"""Release notes shown in Settings > App updates. Add a new entry at the top
(and raise APP_VERSION in config.py) each time a new version goes live."""

RELEASES = [
    {
        "version": "2.0.0",
        "date": "2026-10-26",
        "notes": [
            "Under-18 accounts: date of birth at sign-up, parent or guardian confirmation, and a parent portal.",
            "Learners and adults are kept on separate sides: they cannot see, message or trade with each other.",
            "Email confirmation at sign-up, a 5-attempt limit on passwords and codes, and stronger password rules.",
            "Signing in on a new password signs out other devices. Sign-in activity is shown in Settings.",
            "Administrators must use two-step verification.",
            "Donation requests and swap offers can now be answered from a new Requests page.",
            "Only one student can reserve an item at a time, and only the buyer confirms a hand-over.",
        ],
    },
    {
        "version": "1.4.0",
        "date": "2026-10-24",
        "notes": [
            "No sample students or sample listings: everything on the site is created by real people.",
            "The sell page has a price guide based only on real Campus Swap sales and listings.",
            "Removed the placeholder AI listing generator and smart search.",
        ],
    },
    {
        "version": "1.3.0",
        "date": "2026-10-24",
        "notes": [
            "Offers in chat can now be accepted or declined by the other person.",
            "Receipts show where the price came from: the listing, or an accepted chat offer.",
            "When a chat offer is used, the receipt also shows the listed price and the difference.",
        ],
    },
    {
        "version": "1.2.0",
        "date": "2026-10-20",
        "notes": ["New sliding Sign in and Create account page."],
    },
    {
        "version": "1.1.0",
        "date": "2026-10-17",
        "notes": [
            "New Settings area: account, privacy, appearance, accessibility, lists, chats, storage, help and more.",
            "Two-step verification with an authenticator app, and recovery codes.",
            "Username, phone number and email address can now be changed from Settings.",
            "Dark, Blue and Velvet appearance modes, and an increased-contrast option.",
            "Invite a friend link, chat backup download, and delete account.",
        ],
    },
]
