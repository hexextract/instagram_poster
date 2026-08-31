# Instagram Poster

Posts queued content to Instagram from GitHub Actions using the Meta Graph API.

## How it works

- Each post lives in its own folder under `posts/`, containing:
  - one `.jpg` for a single image post, **2–10 `.jpg` files for a carousel**
    (published in filename order), or a `.mp4`/`.mov` for a Reel
  - alternatively a `url.txt` with one public HTTPS media URL per line
  - `caption.txt` with the caption (hashtags included)
- The **Post to Instagram** workflow runs daily (and on manual dispatch), picks the
  oldest folder not yet listed in `posted.json`, publishes it, and commits the
  updated `posted.json` back.
- Folders publish in alphabetical order — date-prefixed names like
  `2026-09-01-my-post` keep the queue ordered.
- The **Refresh Instagram token** workflow runs monthly and rotates the
  long-lived access token before its 60-day expiry.

> **The repo must be public** for Instagram to fetch images via
> `raw.githubusercontent.com`. If you want a private repo, host media elsewhere
> (S3, Cloudinary, etc.) and put the public URL in `url.txt` instead.

## Setup

This project uses the **Instagram API with Instagram Login**
(`graph.instagram.com`). App: **AskZoye - IG**, Instagram app ID
`2027818518096305`, IG account ID `17841439160595352`. The app secret and
tokens are **never** stored in this repo (it is public) — only in GitHub
Actions secrets.

1. **Instagram account**: professional (Business/Creator), added as an
   Instagram Tester on the app (accept the invite at instagram.com →
   Settings → Apps and Websites → Tester Invites).
2. **Access token**: in the app dashboard under Instagram → API setup with
   Instagram login, click **Generate token** next to the account. Tokens
   generated there are long-lived (60 days); the refresh workflow keeps it
   fresh from then on. Scopes: `instagram_business_basic`,
   `instagram_business_content_publish`.
3. **Repository secrets** (Settings → Secrets and variables → Actions):

   | Secret            | Value                                                         |
   | ----------------- | ------------------------------------------------------------- |
   | `IG_USER_ID`      | `17841439160595352`                                           |
   | `IG_ACCESS_TOKEN` | long-lived access token                                       |
   | `GH_PAT`          | GitHub PAT with `secrets: write` on this repo (token refresh) |

   Only if using a Facebook-Login token instead: also set `FB_APP_ID` and
   `FB_APP_SECRET`, and set env `GRAPH_BASE=https://graph.facebook.com/v23.0`
   in `post.yml`.
4. **Verify the token** locally:
   ```sh
   IG_ACCESS_TOKEN=<token> python poster.py whoami
   ```

5. Push, then trigger the **Post to Instagram** workflow manually from the
   Actions tab to test with the first queued post.

## Limits worth knowing

- Max 100 API-published posts per rolling 24 hours.
- Images must be JPEG; aspect ratio between 4:5 and 1.91:1.
- Reels are published with `media_type=REELS`; the script polls until Meta
  finishes processing before publishing.
