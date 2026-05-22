# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`draftRecreate` is a single-file Python CLI tool (`draft_replay.py`) that replays a prior year's fantasy/sports draft into a MySQL/MariaDB database in real time, preserving the original time gaps between picks.

The full specification is in `specs/spec.md`. Implement against that spec exactly — the out-of-scope section matters (no dry-run, no resume, no timing compression).

## Running the script

```bash
python draft_replay.py --csv draft_2024.csv --season 2025
```

Requires a `.env` file in the working directory:

```
DB_HOST=localhost
DB_PORT=3306
DB_NAME=your_database
DB_USER=your_user
DB_PASSWORD=your_password
DB_TABLE=draft_picks
```

## Dependencies

```bash
pip install python-dotenv mysql-connector-python
# or: pip install python-dotenv PyMySQL
```

## Key design constraints

- Database operation is always an **UPDATE**, never an INSERT. One UPDATE per pick targeting `round`, `pick`, and `season`.
- `season` comes from `--season` CLI arg, not from `draft_time` in the CSV.
- No sleep before the first pick; sleep *before* each subsequent pick using the delta between consecutive `draft_time` values.
- After each UPDATE, check `rowcount`: warn on 0 rows affected, warn on 2+ rows affected, proceed silently on exactly 1.
- CSV rows must be sorted by `draft_time` ascending before replay begins.
