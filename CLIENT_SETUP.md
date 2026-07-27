# HaulCheck — Local Setup Guide

**Installing and running HaulCheck on a Windows laptop, step by step.**

This guide is written so you can follow it yourself, or read it out while
guiding the client over AnyDesk. Every command is copy-and-paste. Nothing here
touches the internet-facing production setup — this gets the app running **on
the laptop itself**, which is all that is needed to demo it, enter real data,
and use it day to day.

> **Assumptions:** a **Windows 10 or 11** laptop with administrator rights and a
> normal internet connection. Budget **30–45 minutes** the first time, most of
> which is downloads. If the client is on a **Mac**, stop here and ask for the
> Mac version of this guide — the commands are different.

---

## What you are installing, and why

HaulCheck has three parts that run on the laptop together:

| Part | What it is | You will install |
|---|---|---|
| **Database** | Stores all the fleet, driver and compliance data | MongoDB 7 (runs quietly in the background) |
| **API / backend** | The engine — logins, compliance rules, PDFs | Python 3.12 + the app's code |
| **Web app / frontend** | The screens you click on in the browser | Node.js + the app's code |

You also need two tools to get the code and run it: **Git** (downloads the code)
and the installers below. Do the steps **in order** — each one builds on the last.

---

## Step 1 — Install the four tools

Download and install these four, one at a time. The **install options in bold
matter** — getting them wrong is the most common cause of problems later.

### 1a. Git (downloads the code)

- Download: <https://git-scm.com/download/win> (the download starts on its own).
- Run the installer. **Click Next through every screen** — the defaults are fine.

### 1b. Python 3.12 (runs the backend)

- Download: <https://www.python.org/downloads/release/python-31210/> — scroll to
  the bottom and choose **“Windows installer (64-bit)”**.
- ⚠️ **Do not** install Python 3.13 or 3.14 — some of the app's parts do not work
  on those yet. It must be **3.12**.
- On the very first installer screen, **tick the box “Add python.exe to PATH”** at
  the bottom, *then* click **Install Now**. This one tick saves a lot of trouble.

### 1c. Node.js (runs the web app)

- Download: <https://nodejs.org/en/download> — choose the **LTS** version, Windows
  Installer (.msi).
- Run it and click Next through the defaults. If it offers a checkbox about
  “automatically install the necessary tools,” you can **leave it unticked** — it
  is not needed.

### 1d. MongoDB 7 (the database)

- Download: <https://www.mongodb.com/try/download/community> — set **Version** to
  **7.0**, **Platform** Windows, **Package** msi, then **Download**.
- Run the installer:
  - Choose **“Complete”** setup.
  - On the service screen, leave **“Install MongoDB as a Service”** ticked (this is
    the default). This means the database **starts automatically** every time the
    laptop is turned on — the client never has to think about it.
  - Leave **“Install MongoDB Compass”** ticked — it is a free visual tool for
    looking at the data, handy but optional.

### Check they all installed

Open a **new** PowerShell window (click Start, type `PowerShell`, press Enter) and
run these one at a time. Each should print a version number:

```powershell
git --version
py -3.12 --version
node --version
```

If any says *“not recognised”*, that tool did not install correctly — re-run its
installer (for Python, the missing **“Add to PATH”** tick is almost always the
cause).

---

## Step 2 — Download the app's code

In the same PowerShell window, choose where the code should live and clone it.
This puts it in the user's home folder under `haulcheck`:

```powershell
cd ~
git clone https://github.com/shahmir2004/haulcheck.git
```

> **A browser window will pop up asking you to sign in to GitHub.** The code is in
> a **private** repository, so sign in with **your own developer GitHub account**
> (the one that owns the repo). This happens once; Git remembers it afterwards.

When it finishes, move into the app folder. The app lives two levels down inside
the project:

```powershell
cd ~\haulcheck\"emergent app"\Haulcheck-main
```

You are now in the folder that contains `backend`, `frontend` and
`start-haulcheck.bat`. Every command below is run from here unless it says
otherwise.

---

## Step 3 — Set up the backend

This creates a private Python environment for the app and installs its parts.

```powershell
cd backend
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-local.txt
```

The install takes a couple of minutes. Then create the app's settings file from
the template:

```powershell
Copy-Item .env.example .env
```

**One value must be filled in: a secret key** used to keep logins secure. Generate
one and open the file to paste it in:

```powershell
.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(48))"
notepad .env
```

In Notepad, find the line that starts `JWT_SECRET=` and replace the placeholder
with the long random string that was just printed. For example:

```
JWT_SECRET=Xy8...the-long-random-string-you-copied...
```

Save and close Notepad. **Leave every other line as it is** — the defaults are
correct for running on the laptop. (The keys for AI, email and Google sign-in are
left blank on purpose; the app runs fine without them. See *Optional extras* at
the end if you want to switch those on.)

---

## Step 4 — Set up the web app

Go back up to the app folder and into `frontend`:

```powershell
cd ..\frontend
corepack enable
corepack prepare yarn@1.22.22 --activate
yarn install
```

`yarn install` downloads a lot of small files and can take **3–5 minutes** — this
is normal. Then create its settings file (the defaults are correct as-is, no
editing needed):

```powershell
Copy-Item .env.example .env
```

---

## Step 5 — Start it for the first time

Everything is installed. Now start the two parts. The database is already running
in the background as a service, so there is nothing to start for it.

**Easiest way — the launcher:** in File Explorer, open
`…\haulcheck\emergent app\Haulcheck-main`, and **double-click
`start-haulcheck.bat`**. Two black windows open (the API and the web app), and
after a few seconds your browser opens the app automatically.

**Or by hand** — two PowerShell windows, from the app folder:

```powershell
# Window 1 — the API
cd backend
.venv\Scripts\python -m uvicorn server:app --port 8000
```

```powershell
# Window 2 — the web app
cd frontend
yarn start
```

The first time, the web app takes **30–60 seconds** to compile, then opens
<http://localhost:3000> in the browser. If it does not open on its own, type that
address in the browser yourself.

> **Leave both black windows open** while using the app. They are the engine —
> closing one stops that part. To shut HaulCheck down at the end of the day, just
> close both windows.

### Create the first account

1. On the login screen, choose **Register / Create account**.
2. Enter the client's company details and a password. **The password must be at
   least 12 characters** (this is a deliberate security rule).
3. That first account becomes the owner of the organisation. Everyone else the
   client adds later (managers, drivers) is invited from inside the app.

That's it — the app is running. Add a vehicle, log a defect, generate a PDF audit
pack to confirm everything works.

---

## Step 6 — Using it day to day

After the one-time setup above, starting HaulCheck each day is simple:

- The **database** is already running (it starts with Windows — nothing to do).
- **Double-click `start-haulcheck.bat`**, wait for the browser to open, and use it.
- When finished, **close the two black windows**.

You may want to **right-click `start-haulcheck.bat` → Send to → Desktop (create
shortcut)** so the client has a one-click icon on the desktop.

---

## Step 7 — Optional extras (only if the client wants them)

The app is fully usable without these. Each one switches on an *extra* feature and
needs an account **in the client's name**. To turn one on, put its key into
`backend\.env` (the file you edited in Step 3) and restart the API window.

| Feature | What it adds | Where to get the key |
|---|---|---|
| **AI assistant** | Auto-summarises defects, drafts letters, reads insurance & tacho docs | An Anthropic API key — set `AI_PROVIDER=anthropic` and `ANTHROPIC_API_KEY=` |
| **Email** | Sends reminders, alerts and audit packs by email | A Resend account — set `RESEND_API_KEY=` and `SENDER_EMAIL=` |
| **Google sign-in** | “Sign in with Google” button | A Google Cloud OAuth client — set `GOOGLE_CLIENT_ID=` and `GOOGLE_CLIENT_SECRET=` |
| **File storage** | Photo/document uploads on defects and walkarounds | An S3-compatible bucket — set `STORAGE_PROVIDER=s3` and the `S3_*` values |

Full details for each, including the exact account steps, are in the separate
**HANDOVER** document. Until a key is added, that one feature simply shows as
“not configured” and the rest of the app works normally.

---

## Troubleshooting

**The browser shows “can't reach this page” or the app won't load.**
The web app window is still compiling (wait for it to say *Compiled successfully*),
or the API window isn't running. Both black windows must be open.

**Everything loads but login/registration fails or spins.**
The API window isn't running or crashed. Look at the API window for a red error.
The most common cause is a missing `JWT_SECRET` — re-check Step 3.

**`py -3.12` says “not recognised”.**
Python 3.12 isn't installed or wasn't added to PATH. Re-run its installer and make
sure **“Add python.exe to PATH”** is ticked (Step 1b).

**`ServerSelectionTimeoutError` in the API window.**
The database isn't running. Open Start → type `services.msc` → find **MongoDB
Server** in the list → right-click → **Start**. (It should be set to start
automatically; if not, set its Startup type to Automatic.)

**Port already in use / “address already in use”.**
An old copy is still running. Close all the black windows and double-click the
launcher again. If it persists, restart the laptop.

**`yarn` says “not recognised”.**
Run `corepack enable` again (Step 4), or close and reopen PowerShell so it picks
up Node.

---

## Where the data lives, and backups

- All the client's data is stored by MongoDB on the laptop (by default under
  `C:\Program Files\MongoDB\Server\7.0\data`).
- Because this runs on one laptop, **there is no automatic off-machine backup.**
  If long-term safety matters, the simplest option is to host the database in
  **MongoDB Atlas** (free tier) and point `MONGO_URL` in `backend\.env` at it —
  Atlas then handles backups. This is covered in the HANDOVER document.
- To move HaulCheck to a different laptop later, install the four tools there,
  clone the code again, and copy the database across (or use Atlas, in which case
  there is nothing to copy).

---

*Once the app is open in the browser and the first account is created, setup is
complete. Keep this guide with the project for the next time it needs installing.*
