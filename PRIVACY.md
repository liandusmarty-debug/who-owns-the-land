# Privacy (POPIA)

This project publishes **area-level information only**. We never collect, join or publish data
about identifiable people or households.

The rules are enforced in code:

- The clean stage turns registered-owner names into an owner *type* (City, Province, National,
  Private or Other) and then drops them. They never reach `data/processed/` or `outputs/`.
- `PrivacyGuard` refuses to write any output that still contains a personal-data column.
- Small areas with fewer than `min_households` households (default 30) have their figures
  hidden and are left out of the ranking.
- CI checks every published file again before anything is deployed.
- Raw data is never committed to this repository.

## Reporting a concern

If you think anything we publish could identify a person or household, **don't open a public
issue**. Report it privately instead:

1. Go to the repository's **Security** tab and choose **Report a vulnerability**. Only maintainers can see these reports.
2. Say which area or file is affected and why. Don't repeat the personal details themselves.

We aim to respond within 72 hours and will take the affected output down while we look into it.
