"""Broker port and adapters (FR-23 to FR-29, architecture §1).

Modules:
    base        Broker protocol, value types and the adapter risk gate (M2)
    errors      error taxonomy every adapter maps to (M0)
    fill_model  pure fill simulation shared by backtest and paper (M2, AD-6)
    paper       PaperBroker: backtest (M2) and dry-run (M3)
    kraken      KrakenBroker; constructor requires a LiveGate (M6, AD-15)
"""
