import sentry_sdk


def setup_sentry():
    sentry_sdk.init(
        dsn="https://a0a16236f88452610071a2e2a6735f4c@o4509650312167424.ingest.de.sentry.io/4510538964271184",
        # Add data like request headers and IP for users,
        # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info
        send_default_pii=True,
        # Enable sending logs to Sentry
        enable_logs=True,
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for tracing.
        traces_sample_rate=1.0,
        # Set profile_session_sample_rate to 1.0 to profile 100%
        # of profile sessions.
        profile_session_sample_rate=1.0,
        # Set profile_lifecycle to "trace" to automatically
        # run the profiler on when there is an active transaction
        profile_lifecycle="trace",
        # Enable logs to be sent to Sentry
        _experiments={
            "enable_logs": True,
        },
    )