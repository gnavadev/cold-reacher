# Cold Reacher

A desktop app for job-search cold outreach. Paste raw text from a LinkedIn profile, and Cold Reacher finds the person's work email, verifies it, and writes a short, personalized pitch with the Gemini API — all stored locally.

Built with Python + PySide6. Networking (email validation) and AI (pitch generation) run on background threads, so the UI never freezes.

---

## Setup

Requires **Python 3.10+**.

```bash
pip install -r requirements.txt
python main.py        # on Windows you can also use: py main.py
```

On first launch, open **Settings** and fill in at least a Gemini key (for pitches) and one email-verification key.

---

## API keys (all have free tiers, no credit card)

Open **Settings → API Keys…** and paste whichever you have:

| Service | Free tier | What it's for | Get a key |
|---|---|---|---|
| **Google Gemini** | free | Writing the pitch (required for pitches) | aistudio.google.com/apikey |
| **Hunter.io** | ~50 finds/mo | Finding & verifying emails (best option) | hunter.io/users/sign_up |
| **ZeroBounce** | ~100/mo | Email verification (fallback) | app.zerobounce.net |
| **Abstract** | 100/mo | Email verification (fallback) | app.abstractapi.com — use the **Email Reputation** product |

Validation tries these in order: **Reacher → Hunter → ZeroBounce → Abstract → direct SMTP**. The first one you've configured is used; only one runs per lookup. With no keys, it falls back to a direct SMTP probe (works for self-hosted mail servers but is blocked by Google/Microsoft from home networks).

> **Why keys?** Google and Microsoft block email verification from residential IPs. Services like Hunter run the check from datacenter IPs that aren't blocked, so they work on `@microsoft.com`, `@google.com`, etc.

### Other Settings

- **Settings → User Info…** — your name and website, used to sign off each pitch (`Best, / Name / Website`).
- **Settings → Instructions…** — full editor for how the AI writes pitches (tone, length, language). Pre-filled with the default so you can tweak or fully replace it; **Reset to Default** restores it.

---

## Using it

1. **Add a lead** — enter First name, Last name, and Domain (e.g. `microsoft.com`), then **Add Lead**.
2. **Paste context** — copy the target's LinkedIn profile/posts into the *LinkedIn Context* box. Messy text is fine; the AI filters out the noise.
3. **Validate Email** — finds the real address and shows its status (Valid / Catch-all / Invalid).
4. **Generate Pitch** — writes a sub-80-word email with a subject line and your signature. Use **Copy Pitch to Clipboard** to send it from your mail client.
5. **Export / Log** — appends the lead to `leads.csv` for your records.

The **Live Logs** tab shows each step in real time (MX lookup, SMTP result, API calls).

Leads, emails, contexts, and pitches are **saved automatically** and restored the next time you open the app.

---

## Local files

| File | Contents | Committed? |
|---|---|---|
| `.keys.json` | API keys, your name/website, custom instructions | No — gitignored |
| `leads.json` | Auto-saved working state (all leads + pitches) | No — gitignored |
| `leads.csv` | Manual export log (from Export / Log) | No — gitignored |

All data stays on your machine. Nothing is uploaded except the API calls you trigger.

---

## Project layout

```
engines/       backend logic (no UI)
  validator.py     email permutations + verification providers
  ai_generator.py  Gemini pitch generation
  logger.py        CSV export
ui/            PySide6 widgets + background threads
main.py        entry point
tests/         unit tests  (python -m pytest tests/)
```
