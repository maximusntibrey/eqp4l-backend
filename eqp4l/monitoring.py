"""Sentry set-up (T.13, O1.7). Off unless a DSN is given; the DSN never goes in git."""

import sentry_sdk


def init_sentry(dsn: str, environment: str, release: str) -> bool:
    """Start Sentry when `dsn` is set. Returns whether it was started."""
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release or None,
        send_default_pii=False,  # never send personal data (SKILLS rule 17)
    )
    return True
