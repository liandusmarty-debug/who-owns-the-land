# Setting up donations

Sponsorships are switched on in the repository settings, but the **Sponsor** button on GitHub only
appears once `.github/FUNDING.yml` exists. Don't create that file until there's a real account to point
it at: a placeholder shows a broken or misleading button.

## 1. Choose where donations go

| Option | Good for | Notes |
|---|---|---|
| **GitHub Sponsors** | Developers and tech supporters already on GitHub | Needs a Sponsors profile (personal or organisation) and approval from GitHub. Check that payouts are available to a South African bank account before applying. |
| **Open Collective** | Transparent public budgets; a natural fit for civic/open-data projects | Join a *fiscal host* so donations are held by a registered organisation. Every expense is published. |
| **South African payment page** | Local donors paying in rand by card, EFT or instant EFT | e.g. PayFast, BackaBuddy, GivenGain, or a donate page on the NPO's own website. |

Once the organisation is registered as an NPO (and ideally a Public Benefit Organisation with
**Section 18A** approval from SARS), local donors can claim tax deductions. That's worth saying on the donate page.

## 2. Create `.github/FUNDING.yml`

List only the platforms you actually set up. Up to four custom links are allowed.

```yaml
# .github/FUNDING.yml
github: [liandusmarty-debug]           # GitHub Sponsors account(s)
open_collective: who-owns-the-land     # Open Collective slug
custom:
  - https://example.org/donate         # e.g. PayFast / BackaBuddy / GivenGain page
```

Commit it through a pull request. After it merges, the **♥ Sponsor** button appears at the top of the repository.

## 3. Update the README

In `README.md` → **Support this project**, replace "Donations will open soon" with the donate
link(s) and one sentence on what donations pay for (for example licensed deeds data for priority areas,
community workshops and translations).

## 4. Be transparent

Publish a short yearly note in the Wiki on what was raised and how it was spent. Open Collective
does this automatically.
