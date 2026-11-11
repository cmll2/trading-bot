"""SQLite persistence via stdlib sqlite3 (FR-39, architecture §2, AD-7, AD-17). M3.

One database file per (mode, strategy) under var/state/. WAL, synchronous=FULL. The
dashboard opens it read-only (file:...?mode=ro).
"""
