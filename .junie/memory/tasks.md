### Completed Tasks
- **FIFO Trade Matching:** Implemented quantity-splitting matching to handle aggregated orders and "legging out" scenarios.
- **Tax Planning 2026:** Added Safe Harbor and Rate-Based tax estimation logic to the dashboard.
- **Corporate Actions Engine:** Built a generalized adjustment system for stock splits, reverse splits (TLRY, BITI), strike adjustments (TECL), and spin-offs (LEN).
- **Orphan Re-matching:** Fixed an issue where corporate action symbol changes (e.g., TLRY to TLRY1) created orphaned historical rows. The tool now re-matches these legs after normalization.
- **Double-Adjustment Safety:** Added safeguards to `orders.py` to prevent historical trades from being adjusted multiple times for the same split.
- **Git Hygiene:** Configured `.gitignore` and removed the `experiments/` directory from remote tracking (keeping it local-only).
