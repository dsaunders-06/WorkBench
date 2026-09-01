# Plan — M160 deploy and the Gateway→TWS swap, at the close of 1 September 2026

**Two changes in one stand-down.** Written before either is made, including the
thing that decides which one to blame if the next launch misbehaves.

---

## Why they are bundled, given today's whole lesson was one build at a time

Deploying M160 and swapping the broker endpoint both need the app stopped, and
the close is the only moment today that costs nothing. Doing them on separate
evenings would mean two stand-downs for one outcome.

⚠️ **The cost of bundling is attribution**, and it is paid for here rather than
waved away: **the failure modes are disjoint and the discriminator is written
below, in advance.** If the next launch misbehaves in a way the table does not
predict, unbundle by rolling back TWS first (seconds) and re-reading.

---

## PREREQUISITE — yours, not mine

**TWS is not installed.** Only IB Gateway 10.50 is (`C:\Jts\ibgateway`), and it
is API-only — no trading UI of any kind, which is the whole reason for this.

**Install Trader Workstation** from interactivebrokers.com, using the same paper
credentials the Gateway uses. I will not download or install executables.

⚠️ **IBKR allows one session per username, so this is a SWAP, not an addition.**
TWS and the Gateway cannot both hold the paper login. Whatever is logged in is
what the app can reach.

---

## THE SEQUENCE

Nothing here runs before **16:00** and the daily report at ~16:02.

### 1. Confirm the session finished cleanly

    & "C:\Claude Programming\scripts\session_check.ps1"     # NO ARGUMENTS, EVER

Want: a stand-down line, the daily report, and no ERROR/CRITICAL after 10:21.
⚠️ **A clean shutdown is what makes the fill watermark trustworthy on the next
launch** — the app says so itself at startup. Do not kill the process.

### 2. Close the app normally

`deploy.ps1` refuses while it runs, and says why in those words.

### 3. Deploy M160 — dry run, then ask, then apply

    .\scripts\deploy.ps1                # dry run: derives everything, writes nothing
    .\scripts\deploy.ps1 -Apply         # ONLY after the dry run is read and approved

⚠️ **Ask before `-Apply`.** It rewrites `DEPLOYED` only after verifying the
installed copy, and creates rollback directory number 22.

### 4. Swap the broker

1. Close IB Gateway.
2. Start TWS, log into the **paper** account.
3. **Global Configuration → API → Settings**:
   * ✅ Enable ActiveX and Socket Clients
   * Socket port **7497**
   * ❌ **Read-Only API OFF** — on, the app connects and every order fails
   * Trusted IP `127.0.0.1`
4. Consider TWS's auto-restart/auto-logoff settings: it logs out daily by
   default, and an unattended session that has quietly logged itself out looks
   exactly like a broker outage.

### 5. Point the app at TWS

    .\.venv\Scripts\python.exe scripts\set_ibkr_port.py 7497            # dry run
    .\.venv\Scripts\python.exe scripts\set_ibkr_port.py 7497 --apply

⚠️ **PowerShell, never Bash** — it writes to `%LOCALAPPDATA%`. It backs the file
up, refuses a live port under `paper`, refuses an unknown port, refuses while the
app is running, and **reads the value back rather than trusting the write**.

### 6. Launch, and read BOTH changes back

| Expect | Which change it confirms |
|---|---|
| `Build: M160 (<sha>, ...)` | the deploy |
| broker connects, ten positions adopted, 20 legs | the swap |
| `RESTING ORDER SCAN: 20 working leg(s) ... nothing unjustified` | both |
| no `KILL-SWITCH RESTORED` line | state carried over |

⚠️ **The account must still be `DU…`.** `check_paper_account` refuses a
non-`DU` account after connecting — the port being right does not prove the
session is the paper one.

---

## ⚠️ THE DISCRIMINATOR — written before anything is changed

| Symptom | Blame | Why |
|---|---|---|
| Cannot connect; connection refused/timeout | **TWS** | M160 changes nothing about connecting |
| Connects, but every order rejected | **TWS** | Read-Only API left on |
| Account is not `DU…` | **TWS** | logged into the wrong session |
| Positions adopt wrong, or legs missing | **TWS** | different session, different book |
| Connects fine, adopts fine, then reconciliation misbehaves | **M160** | that is the only thing M160 touches |
| Kill switch trips on a partial fill | **M160** | this is the defect it fixes — it regressed |
| Build line is not M160 | **deploy** | installed copy is not what was built |

**Anything not in this table means the bundle was a mistake: roll TWS back
first** (`set_ibkr_port.py 4002 --apply`, restart Gateway — seconds) **and
re-read on M160 alone.**

---

## ROLLBACK

| Change | How | Cost |
|---|---|---|
| TWS swap | `set_ibkr_port.py 4002 --apply`, close TWS, start Gateway | seconds |
| M160 | rollback directory 22, created by `deploy.ps1 -Apply` | a reinstall |

Both are independent. The TWS rollback does not touch the build, and the M160
rollback does not touch the port.

---

## WHAT THIS DOES NOT GIVE YOU

TWS provides manual **buy and sell** and the ability to move a resting stop —
the gap that prompted this. It does **not** teach the application about anything
done by hand:

⚠️ **A manual trade in TWS is invisible to the app's records.** The app
reconciles against the broker, so it will SEE a changed position — but
`open_position_entries.json` has no entry basis for it, so the minimum hold and
the time stop cannot be computed and no stop can be re-armed. That is exactly
the state `flatten_positions.py`'s docstring describes from 24 August:
*"the application cannot manage them"*.

**So: manual selling of an app-managed position is safe** (the app records the
exit against a known entry). **Manual BUYING creates a position the app cannot
manage.** If you buy by hand, expect to manage that position by hand.

The existing sell-side tools remain the safer route for app-managed positions:

    scripts\flatten_positions.py            # everything to zero, dry-run default
    scripts\unwind_in_tranches.py SYMBOL    # one symbol, cancels stuck orders first
