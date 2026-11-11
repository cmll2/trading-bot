# Data manifest

Provenance of every external data file used by the bot. Files themselves live under the
gitignored `data/raw/` folder and are never committed. They are treated as untrusted
data: nothing in them is executed; only CSV members are read through stdlib `zipfile`
and `pandas.read_csv`, without extracting the archive to disk.

Source page (official): https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data

## Downloaded

| Local path | Source URL | Size (bytes) | SHA-256 (computed on download) | Downloaded (UTC) | Checksum published by Kraken? |
|---|---|---|---|---|---|
| `data/raw/kraken_ohlcvt/Kraken_OHLCVT_2026Q3.zip` | https://assets.kraken.com/marketing/institutions/Kraken_OHLCVT_2026Q3.zip | 576348633 | `96daae63c7b3acb522892e1f602f9c564d1a3fb659089d9b0699282f30d41226` | 2026-11-11 | No (Kraken publishes checksums only for the full archive). This value is trust-on-first-use and is the one passed to `bot data import-archive --sha256`. |
| `data/raw/kraken_ohlcvt/OHLCVT_Full_PARTS_SHA256SUMS.txt` | https://assets.kraken.com/marketing/institutions/OHLCVT_Full_PARTS_SHA256SUMS.txt | 480 | `2b9be0b727fe0ca453ac0a425700e2e77679a8c6146d3302ced7d0416b1db0d3` | 2026-11-11 | n/a (it is the published checksum list) |

`Kraken_OHLCVT_2026Q3.zip` facts, read from its `MANIFEST.json` and member listing
(2026-11-11): coverage 2026-07-01 to 2026-09-30, 1436 pairs, 10052 CSV files, no header,
columns `timestamp, open, high, low, close, volume, trades`, timestamps in Unix seconds
(first row 1782864000 = 2026-07-01T00:00Z). XBTEUR members: `XBTEUR_1440.csv` (92 rows),
`XBTEUR_240.csv` (552 rows), `XBTEUR_15.csv` (8832 rows). Note that `AIXBTEUR_*`,
`XBTEURC_*` and `XBTEUROP_*` members also exist: the importer matches the exact member
name, never a suffix.

## Not downloaded (operator action required for "several years")

The full history exists only as `Kraken_OHLCVT_Full.zip`, split into 5 parts of
2097152000 bytes each (about 10 GB in total), with no per-pair file. Above the 5 GB
limit set for this build, so it was not downloaded automatically.

| Part | URL | Published SHA-256 (from the SUMS file above) |
|---|---|---|
| part00 | https://assets.kraken.com/marketing/institutions/Kraken_OHLCVT_Full.zip.part00 | `12ce809a0cc12c421f9bb871434f71eca8b3c258cb194efae258318a683b9491` |
| part01 | https://assets.kraken.com/marketing/institutions/Kraken_OHLCVT_Full.zip.part01 | `7086e1915e79b5157fae05978ca9603da7f918a091652b5fdedda7d7a53d03ee` |
| part02 | https://assets.kraken.com/marketing/institutions/Kraken_OHLCVT_Full.zip.part02 | `880fcf84e177e50ca946f3f5cb6d57c721a4950853ca1bf6bdde526896013cc1` |
| part03 | https://assets.kraken.com/marketing/institutions/Kraken_OHLCVT_Full.zip.part03 | `3fa1fdfbb94c5a3cc861068a11b5c309502a8ac8da0f4c6f091c5a2968451157` |
| part04 | https://assets.kraken.com/marketing/institutions/Kraken_OHLCVT_Full.zip.part04 | `db2c8b80c92a2e09b3f71f464b0b55574bd56c645d2560169dbbe4887b9c00eb` |

Published SHA-256 of the reassembled `Kraken_OHLCVT_Full.zip` (support page, read
2026-11-11): `bc273e9027470b07d790a7fa4df9bb43f0dfc527c20c6ecae48402e123e7b1c7`.
Coverage per the support page: first trade to 2026-06-30.

Operator steps (PowerShell), into a new empty folder `data/raw/kraken_ohlcvt_full/`:

1. Download the 5 parts from the URLs above.
2. Check each part: `Get-FileHash .\Kraken_OHLCVT_Full.zip.part00 -Algorithm SHA256`
   (compare with the table).
3. Reassemble: `cmd /c copy /b Kraken_OHLCVT_Full.zip.part00+Kraken_OHLCVT_Full.zip.part01+Kraken_OHLCVT_Full.zip.part02+Kraken_OHLCVT_Full.zip.part03+Kraken_OHLCVT_Full.zip.part04 Kraken_OHLCVT_Full.zip`
4. Import (the command re-checks the published SHA-256 before reading any row):
   `uv run bot data import-archive --zip data\raw\kraken_ohlcvt_full\Kraken_OHLCVT_Full.zip --sha256 bc273e9027470b07d790a7fa4df9bb43f0dfc527c20c6ecae48402e123e7b1c7`
5. Then `uv run bot data validate` and add the row to the "Downloaded" table above.
