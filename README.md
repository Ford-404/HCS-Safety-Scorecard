# HCS Safety Health Report automation

Work in progress, built in stages. Currently at **Stage 1: endpoint discovery**. See `docs/field-map.md`.

## Setup
1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in `PROCORE_CLIENT_ID`, `PROCORE_CLIENT_SECRET`, `PROCORE_COMPANY_ID` (9593).
3. Put `002 - Safety Health Report.xlsx` in `templates/`.
4. `python src/discover.py`: saves raw JSON for project 401814 to `samples/`.

The full setup, scheduling, distribution list and how to add a project will be documented as later stages are built.
