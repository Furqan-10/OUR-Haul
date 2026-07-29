# HaulCheck — deployment guide

**Putting HaulCheck online, on infrastructure you control, for £0/month.**

This is the internet-facing deployment. For running the app on a single laptop,
see [CLIENT_SETUP.md](CLIENT_SETUP.md) instead.

> **Written from the code and configuration in this repository, not from a
> completed deployment** — the accounts have to be created in your name. The
> steps match what the repo expects; the dashboards may have moved a button
> since. Where a screen differs, the value you need is still the one named here.

---

## What you are building

```
Browser
   │
   ├──► Vercel  ·  the web app  ·  haulcheck.vercel.app
   │       └─ REACT_APP_BACKEND_URL ──┐
   │                                  ▼
   └──────────────────────► Render  ·  the API  ·  haulcheck-api.onrender.com
                                  ├──► MongoDB Atlas   the database
                                  ├──► Cloudflare R2   uploaded photos and PDFs
                                  └──► Resend          reminder and alert email

   cron-job.org ──► POST /api/tasks/run-reminders  ·  daily 07:00 UTC
```

Five services. Each has a free tier that this app fits inside.

| Service | Free tier | What happens when you outgrow it |
|---|---|---|
| **Render** — the API | 750 hours/month, sleeps after 15 min idle | $7/month, no sleeping |
| **MongoDB Atlas** — the database | 512 MB (M0) | ~$9/month for 2 GB |
| **Cloudflare R2** — files | 10 GB, no charge to serve | $0.015/GB/month after |
| **Resend** — email | 3,000/month, 100/day | $20/month for 50,000 |
| **Vercel** — the web app | Free (non-commercial only, see below) | $20/month Pro |

**Budget 45–60 minutes.** Most of it is waiting for accounts to verify.

---

## Before you start

Create these five accounts. Use the client's own email — these hold their data,
and you want them to own it.

1. **MongoDB Atlas** — <https://www.mongodb.com/cloud/atlas/register>
2. **Cloudflare** — <https://dash.cloudflare.com/sign-up>
3. **Resend** — <https://resend.com/signup>
4. **Render** — <https://dashboard.render.com/register> (sign in with GitHub)
5. **Vercel** — <https://vercel.com/signup> (sign in with GitHub)

Plus **cron-job.org** (<https://console.cron-job.org/signup>) at the end.

You also need the code on GitHub. It already is:
`https://github.com/Furqan-10/OUR-Haul`.

Keep a scratch file open. You will collect six values as you go, and step 4
needs all of them at once.

---

## Step 1 — The database

There is no schema to create. The app builds its own collections and indexes
the first time it starts.

1. In Atlas, **Create a deployment** → choose **M0** (the free one).
2. Provider **AWS**, region **Frankfurt (eu-central-1)** — closest to the UK and
   Ireland, and it keeps the data in the EU.
3. Name it `haulcheck`. Create.
4. Atlas prompts for a database user. Create one, let it generate the password,
   and **copy the password now** — it is not shown again.
5. **Network Access** → **Add IP Address** → **Allow access from anywhere**
   (`0.0.0.0/0`).

   > This looks alarming and is the correct choice here. Render's free tier has
   > no fixed outbound IP address, so there is nothing to add to an allow-list.
   > The database password is what protects it. If you later move to a paid
   > Render plan with a static IP, narrow this to that address.

6. **Database** → **Connect** → **Drivers** → copy the connection string. It
   looks like:

   ```
   mongodb+srv://haulcheck:<db_password>@haulcheck.ab12cde.mongodb.net/?retryWrites=true&w=majority
   ```

7. Replace `<db_password>` with the real password. If the password contains
   `@`, `/`, `:` or `#`, percent-encode it (`@` → `%40`) or the URL will not parse.

**Write down:** `MONGO_URL`

---

## Step 2 — File storage

This holds defect photos, signed walkaround sheets and insurance certificates.

1. Cloudflare dashboard → **R2** → **Create bucket**.
2. Name it `haulcheck`. Location **EU**. Create.
3. **Manage R2 API Tokens** → **Create API token**.
4. Permissions: **Object Read & Write**. Scope it to the `haulcheck` bucket
   only — a token that can reach every bucket in the account is a token you
   cannot safely put in a deploy dashboard.
5. Create, then copy **Access Key ID** and **Secret Access Key**. The secret is
   shown once.
6. Note your **Account ID** — it is in the R2 sidebar. Your endpoint is:

   ```
   https://<account-id>.r2.cloudflarestorage.com
   ```

**Write down:** `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_ENDPOINT`

---

## Step 3 — Email

Used for defect alerts, reminder digests, invitations, password resets and
audit packs.

1. Resend → **API Keys** → **Create API Key**. Permission **Sending access**.
   Copy it.
2. **Sender address.** Without a verified domain, Resend only delivers to the
   address that owns the account. That is fine for testing. For real use, add
   the client's domain under **Domains** and set the DNS records it lists.

**Write down:** `RESEND_API_KEY`, `SENDER_EMAIL`

---

## Step 4 — The API

1. Render dashboard → **New** → **Blueprint**.
2. Connect the `Furqan-10/OUR-Haul` repository. Render reads
   [`render.yaml`](render.yaml) and proposes a service called `haulcheck-api`.
3. It will ask for the values marked `sync: false`. Fill in:

   | Variable | Value |
   |---|---|
   | `MONGO_URL` | from step 1 |
   | `S3_BUCKET` | `haulcheck` |
   | `S3_ENDPOINT` | from step 2 |
   | `S3_ACCESS_KEY` | from step 2 |
   | `S3_SECRET_KEY` | from step 2 |
   | `RESEND_API_KEY` | from step 3 |
   | `SENDER_EMAIL` | from step 3 |
   | `CORS_ORIGINS` | `https://haulcheck.vercel.app` — a placeholder for now, corrected in step 6 |

   Everything else is already set in `render.yaml`. `JWT_SECRET` and
   `CRON_SECRET` are generated for you; do not invent your own.

4. **Apply**. The first build takes 5–10 minutes.

**The build is the moment things go wrong.** Watch the log. It should end with
the app starting and reporting:

```
Indexes ready: 64 created/verified
Storage provider: s3 (reachable)
AI provider: null
Email provider: resend
```

`Storage provider: s3 (reachable)` is the line that proves R2 works.

**Write down:** the service URL, e.g. `https://haulcheck-api.onrender.com`

Check it:

```bash
curl https://haulcheck-api.onrender.com/api/health
```

The first request wakes a sleeping instance and can take **50 seconds**. That
is the free tier, not a fault.

---

## Step 5 — The web app

1. Vercel → **Add New** → **Project** → import `Furqan-10/OUR-Haul`.
2. **Root Directory**: `frontend` — this matters; the repository root is not
   the app.
3. Vercel reads [`frontend/vercel.json`](frontend/vercel.json) for the rest.
4. **Environment Variables** → add:

   | Name | Value |
   |---|---|
   | `REACT_APP_BACKEND_URL` | `https://haulcheck-api.onrender.com` |

   **No trailing slash, and no `/api`** — the app appends that itself. A
   trailing `/api` produces requests to `/api/api/...` and every call 404s.

5. **Deploy.**

**Write down:** the Vercel URL, e.g. `https://haulcheck.vercel.app`

> This value is compiled into the JavaScript at build time, not read when the
> page loads. Changing it later means redeploying the frontend, not just
> editing the variable.

---

## Step 6 — Connect the two

The API refuses requests from origins it does not know. Right now it does not
know your Vercel URL.

1. Render → `haulcheck-api` → **Environment**.
2. Set `CORS_ORIGINS` to the exact Vercel URL from step 5 — scheme included, no
   trailing slash:

   ```
   https://haulcheck.vercel.app
   ```

3. Save. Render redeploys automatically.

> **Why the app refuses to start without this.** In production the API rejects
> an unset or `*` value outright. A wildcard cannot be combined with credentials
> — browsers reject it, and the framework then quietly echoes back whichever
> origin asked, which is every origin, with cookies attached. Failing at startup
> is the safe version of that mistake.

> **Vercel preview deployments will not work**, and that is deliberate. Each
> preview gets its own URL, and this list also validates OAuth redirects.
> Allowing `*.vercel.app` would let any Vercel user's project call your API with
> credentials. Test on the production URL.

---

## Step 7 — Daily reminders

The reminder jobs run inside the API at 07:00 UTC. On the free tier the instance
is asleep at 07:00, so they never run — silently, because nothing is awake to
log it. An external scheduler calls the API instead, which also wakes it.

1. Render → **Environment** → copy the generated value of `CRON_SECRET`.
2. cron-job.org → **Create cronjob**.
3. Configure:

   | Field | Value |
   |---|---|
   | Title | HaulCheck daily reminders |
   | URL | `https://haulcheck-api.onrender.com/api/tasks/run-reminders` |
   | Schedule | Every day at **07:00**, timezone **UTC** |
   | Request method | **POST** |
   | Header | `Authorization: Bearer <CRON_SECRET>` |

4. Save, then use **Test run**. Expect `200` and a body like
   `{"ran": {"daily": {"orgs": 1, "sent": 0, "failed": 0}}}`.

One entry covers both jobs: it runs the daily job every day and adds the weekly
one on Mondays, matching the built-in schedule.

> Calling it twice is safe. Both jobs take a lock in the database, so a second
> call returns `{"daily": null}` and sends nothing. `null` means "another run
> held the lock", which is different from "ran and had nothing to send".

---

## Step 8 — Smoke test

Work through this after every deploy. Each step exercises a different part of
the stack, so where it stops tells you what is broken.

- [ ] `https://<render-url>/api/health` returns JSON.
      Check `"storage": "s3"` — `"null"` means the R2 variables did not take.
- [ ] The Vercel URL loads the login page.
- [ ] Register an account. *(API, database write, password policy — minimum 12
      characters.)*
- [ ] Sign in. *(Token issue and verify.)*
- [ ] Add a vehicle with an MOT date in the past; it shows as expired.
      *(Compliance calculation.)*
- [ ] Raise a defect and attach a photo. *(R2 upload — the step most likely to
      fail.)*
- [ ] Reopen the defect; the photo displays. *(R2 download.)*
- [ ] Generate a PDF audit pack and open it. *(PDF rendering in the container.)*
- [ ] Add a repair and a recall. *(The iteration 30–32 features.)*
- [ ] Create a driver, open `/driver`, sign in with the access code.
      *(The separate driver authentication path.)*
- [ ] Trigger reminders:
      ```bash
      curl -X POST -H "Authorization: Bearer $CRON_SECRET" \
        https://<render-url>/api/tasks/run-reminders
      ```
      Expect `{"ran": {...}}` and an email. *(Resend, and the cron path.)*
- [ ] Run the same command again. Expect `"daily": null` — the lock preventing
      duplicate email.

### Running the test suite against the deployment

```bash
cd backend
pip install -r requirements-dev.txt
export REACT_APP_BACKEND_URL=https://haulcheck-api.onrender.com
curl -s "$REACT_APP_BACKEND_URL/api/health"   # wake it first
pytest -n 0
```

The wake-up call is required, not optional — a cold start outruns the default
HTTP timeout and the whole suite fails at once.

---

## What the free tier actually costs you

Worth knowing before a demo, so nothing is a surprise in front of the client.

- **50-second first load.** Render stops the instance after 15 minutes idle. The
  Vercel frontend stays up, so the login page appears instantly and then waits
  on the API. Before any live demo, open the app a minute early — or move to the
  $7/month plan, where this stops happening.
- **Vercel's free plan is non-commercial** under their terms. Fine for testing.
  A product the client charges for needs Pro (~$20/month), or move the frontend
  to Cloudflare Pages or Netlify.
- **Atlas M0 is 512 MB.** Uploaded files go to R2, not the database, so this
  holds a lot of fleet records — but it does not grow, and there are no
  automated backups on M0.
- **Resend allows 100 emails/day** on the free plan. A large fleet's daily
  reminder digest can approach that.

---

## When the domain arrives

Doing this fixes Google sign-in, which is switched off until then.

1. **Vercel** → project → **Settings** → **Domains** → add `app.example.com`.
   Follow the DNS records it gives you.
2. **Render** → service → **Settings** → **Custom Domain** → add
   `api.example.com`. Follow its DNS records.
3. **Render environment** → set `CORS_ORIGINS` to `https://app.example.com`.
4. **Vercel environment** → set `REACT_APP_BACKEND_URL` to
   `https://api.example.com`, then **redeploy the frontend** — the old value is
   baked into the current build.
5. **Turn on Google sign-in:**
   - Google Cloud Console → **APIs & Services** → **Credentials** → **Create
     OAuth client ID** → **Web application**.
   - Authorised redirect URI, exactly: `https://app.example.com/auth/google/callback`
   - Add `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` on Render.
   - The button appears on the login page by itself. It stays hidden while those
     two are unset.
6. Optional: set the canonical URL in `frontend/public/index.html`, fill in
   `sitemap.xml`, and uncomment the `Sitemap:` line in `robots.txt`.

> **Why Google sign-in waits for the domain.** It relies on a session cookie
> marked `SameSite=None`, which Safari and other privacy-focused browsers block
> between two unrelated domains — `vercel.app` and `onrender.com` are unrelated.
> Under one domain the cookie is same-site and every browser accepts it.
> Email/password sign-in never had this problem and works throughout.

---

## When you want AI switched on

Five features are built and currently disabled: defect summaries, letter
drafting, insurance-certificate import, the fleet risk briefing, and tacho
printout analysis. Each one degrades on its own — the app tells the user the
feature is not enabled and carries on.

To enable:

1. Add `anthropic` to [`backend/requirements.txt`](backend/requirements.txt).
2. On Render, set `AI_PROVIDER=anthropic` and `ANTHROPIC_API_KEY=...`.
3. Redeploy.

Expect single-digit dollars a month at this usage — these are per-click
features, not background processing.

> Two of the five read documents: insurance-certificate import and tacho
> printout analysis extract structured compliance fields from a photo or PDF.
> That is where model quality shows first, so test those two before trusting
> them with real records.

---

## Going paid

When the client has customers:

| Change | Cost | Why |
|---|---|---|
| Render Starter | $7/mo | No sleeping. The 07:00 job runs on its own; keep the cron as a backstop |
| Atlas M10 | ~$9/mo | Automated backups, more room |
| Vercel Pro | $20/mo | Required for commercial use |
| Resend | $20/mo | 50,000 emails |

**Back up the database before you have customers, not after.** Atlas M0 has no
automated backups:

```bash
mongodump --uri="$MONGO_URL" --out=backup-$(date +%F)
```

---

## When something is wrong

| Symptom | Cause |
|---|---|
| Build fails during `pip install` | Check `requirements.txt` was not reverted to the Emergent version — that one fetches a package from a URL that only resolves inside their image |
| App will not start, no useful error | `MONGO_URL`, `DB_NAME` or `JWT_SECRET` missing. All three are read as the app loads, so it cannot start without them |
| `CORS_ORIGINS must list explicit origins` | Expected. Set it to the Vercel URL (step 6) |
| Database connection fails, wrong-password look | The `mongodb+srv://` form needs a DNS lookup. Confirm `dnspython` is in `requirements.txt`, and that a `@` or `/` in the password is percent-encoded |
| Every browser request blocked by CORS | `CORS_ORIGINS` does not match the Vercel URL exactly — scheme, no trailing slash |
| Uploads fail | `/api/health` shows `"storage"`. `"null"` means the `S3_*` variables did not take. `SignatureDoesNotMatch` in the log means a wrong key or a region other than `auto` |
| Login works, everything else 401 | `REACT_APP_BACKEND_URL` has a trailing `/api`. Remove it and redeploy the frontend |
| One user's actions rate-limit everyone | `TRUST_PROXY_HEADERS` is not `1`. Render terminates TLS at a proxy, so every request looks like one IP |
| Reminders never arrive | The cron job is not configured, or its `Authorization` header is wrong. Use **Test run** on cron-job.org |
| First load takes ~50 seconds | The free tier stopped the instance. Expected |
