"""Fills ledger and CSV export for French tax bookkeeping (FR-46 to FR-48, AD-19). M3/M4.

The ledger is a SQL view over fills; disposals (crypto -> fiat) are marked; tax-year
attribution uses the Europe/Paris local date, storage stays UTC.
"""
