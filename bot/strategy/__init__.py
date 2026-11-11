"""Strategy interface, registry and implementations (FR-05 to FR-10, AD-3, AD-30).

Pure: no access to the broker, the clock or the network.

Modules:
    base      Strategy protocol, Mode, TargetPosition (M0)
    registry  frozen LIVE / DRY_RUN strategy sets; plumbing never live (M0)
    v0_trend  slow long-or-flat trend filter (M2)
    plumbing  short-timeframe dry-run-only order generator (M3)
"""
