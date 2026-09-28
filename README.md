# bulksms-api – Locust Load Tests

Load test for [`bulksms-api`](../../Personal_Co_code/bulksms-api), the sms project's actual load-bearing HTTP surface — both the public SMS ingestion API and the admin API [`sms-admin-ui`](../../Personal_Co_code/sms-admin-ui) talks to.

## What this does and doesn't cover

- **[`bulksms`](../../Personal_Co_code/bulksms) (the Quarkus consumer) has no HTTP API of its own** to load test directly — it only drains the `sms.outbound` RabbitMQ queue and calls the Safaricom operator. `SingleSmsUser`/`BulkSmsUser` below feed that same queue (the exact pipeline described in bulksms-api's own README), so a sustained run does exercise the consumer's throughput indirectly — but this tool only measures bulksms-api's own request/response times, not the consumer's processing latency or the operator call. Point something at `bulksms`'s own metrics/logs separately if you need that half measured.
- **`sms-admin-ui` itself (the Vite frontend) isn't targeted.** `AdminConsoleUser` simulates the *API calls* that app makes (see its `src/views/*.vue` — every screen re-fetches its list on mount), not page loads against the Vite dev server or a built bundle.

User classes in [`locustfile.py`](locustfile.py), weighted to approximate a realistic mix:

| User class | Weight | Simulates |
|---|---|---|
| `SingleSmsUser` | 10 | single sends on the shared key (unbilled) - `POST /api/v1/sms` |
| `BilledSmsUser` | 6 | single sends as a known, billed client (`X-Api-Client`) - the group-committed charging path. Needs `provision_billing.py` |
| `BulkSmsUser` | 1 | bulk uploads in all three file shapes (`phone_number,message`; template over `phone_number,name,amount`; `phone_number` + one message), plus the personalised list as a random spreadsheet format (`.xlsx`, `.xlsm`, `.xlsb`, `.xls`, `.ods`, `.numbers`), one stats row per format |
| `CampaignUser` | 1 | the admin UI's write path as the billed client's admin: upload a personalised broadcast list, estimate, send |
| `AdminConsoleUser` | 3 | an `sms-admin-ui` session, read-only: `/me`, senders, users, campaigns, lists, reports, billing summary, clients (Super Admin), and the Reports **Export** menu in a random one of the seven formats (`/reports/daily.{fmt}`, one stats row per format) |

[`throughput.py`](throughput.py) is a separate, **fixed-rate** test for "can it sustain N messages/second": each user sends one message per second, and a step shape climbs 100 → 300 → 500 → 700 msg/s (`THROUGHPUT_STEPS`, `STEP_SECONDS`), half billed and half unbilled (`THROUGHPUT_BILLED_SHARE`).

---|---|---|
| `SingleSmsUser` | 10 | External callers sending single SMS (`POST /api/v1/sms`) - the dominant pattern, per bulksms-api's own README framing as "the public entry point". |
| `BulkSmsUser` | 1 | Rare but heavy bulk file uploads (`POST /api/v1/sms/bulk`) - README targets 1M+ rows in under 10 minutes for this path. |
| `AdminConsoleUser` | 3 | An `sms-admin-ui` session: logs in once, then browses read-only (`/me`, `/senders`, `/users`, `/bulk-campaigns`, and `/clients` if Super Admin) the way that app actually does. |

---

## Prerequisites

| Tool | Notes |
|------|-------|
| Python | 3.10+ |
| `bulksms-api` | running, with MySQL reachable (see its own README). RabbitMQ too, if you want `SingleSmsUser`/`BulkSmsUser` to actually succeed rather than fail on every request - see Known limitations. |

---

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # adjust if your bulksms-api differs
```

`.env` defaults to the bootstrap Super Administrator (`admin@bulksms-platform.com` / `ChangeMe123!`). Seed it on a test database with `BOOTSTRAP_ADMIN_PASSWORD='ChangeMe123!' python seed_admin.py`; without that variable `seed_admin.py` generates a one-time password, and production refuses this one.

### Optional: provision a pool of distinct admin accounts

By default every simulated `AdminConsoleUser` logs in as the same bootstrap Super Administrator, which is fine for a quick/small run but means dozens of concurrent users share one account. For anything larger, spread logins across real, distinct accounts first:

```bash
python provision_pool.py --count 50
```

Creates 50 clients, each with one Client Administrator, and writes their credentials to `data/user_pool.json` (gitignored — real working passwords). `locustfile.py` picks one at random per simulated user automatically if this file exists; falls back to the bootstrap account if it doesn't. Re-run with a higher `--count` to add more, or `--replace` to start over.

---

### Provision a billed client (for BilledSmsUser, CampaignUser, throughput.py)

```bash
python provision_billing.py --credit 1000000
```

Creates a client, its Client Administrator, a sender, tops the wallet up (as the Super Administrator) and fetches the client's API credentials into `data/billed_client.json` (gitignored). Without it those user classes skip themselves.

## Running

```bash
locust                              # web UI at http://localhost:8089 - pick user count/spawn rate there
locust --headless -u 50 -r 5 -t 5m  # 50 users, 5/s spawn rate, runs for 5 minutes, prints a summary
```

[`locust.conf`](locust.conf) sets defaults (`host`, `users`, `spawn-rate`) so a bare `locust` run needs no flags; override any of them on the command line, or point at a different target entirely:

```bash
locust --host https://staging.example.com
```

### Run one user class only

```bash
locust --headless -u 20 -r 5 -t 2m SingleSmsUser
locust --headless -u 5 -r 1 -t 2m AdminConsoleUser
```

### Throughput (sustained msg/s)

```bash
locust -f throughput.py --headless --processes 4 --csv results/throughput
THROUGHPUT_STEPS=1200,1600,2000 STEP_SECONDS=40 locust -f throughput.py --headless --processes 6 --csv results/ceiling
```

Read the per-step rate and latency from `results/*_stats_history.csv`. Measured on a 10-core laptop, with the generator, API (4 workers) and MySQL on the same machine and no broker:

| Target | Achieved | p95 | Failures |
|---|---|---|---|
| 100-900/s (steps) | same as target | 54-59 ms | 0 |
| 1,200 / 1,600 / 2,000/s | same as target | 230 / 280 / 290 ms | 0 |

Billed sends reconciled exactly with the ledger (56,539 sends = KES 56,539 of debits).

### Save an HTML report

```bash
locust --headless -u 50 -r 5 -t 5m --html report.html
```

---

## Known limitations

- **`SingleSmsUser`/`BulkSmsUser` need RabbitMQ reachable to actually succeed.** Without it, `POST /api/v1/sms` returns `500` and `POST /api/v1/sms/bulk` still returns `202` (the file-format check is synchronous, but insertion/publishing happens in a background task per request — see `services.py`) — either way you'd be measuring bulksms-api's failure-path latency, not its real one. Same constraint the Selenium/Cucumber suites in this folder document.
- **Signing is off by default.** `AUTH_TEST_MODE=true` (both this project's and bulksms-api's own default) bypasses the `X-Api-Key`/`X-Signature` scheme entirely, so out of the box `SingleSmsUser` sends unsigned requests and the real signing code path (`common.signed_headers`, a port of `app/security.py`) never runs under load. Set `AUTH_TEST_MODE=false` here **and** on the API to load test the real signed paths, including their per-request cost:
  - `SingleSmsUser` uses the legacy shared-key MD5/SHA1 scheme.
  - `BilledSmsUser` and `throughput.py`'s billed share use per-client HMAC-SHA256 (`common.client_signed_request`), and post the exact JSON text they signed.
- **`AdminConsoleUser` is deliberately read-only.** Every simulated user creating clients/senders/users on every task would flood the database with load-test junk over a sustained run. If you specifically want to load test those write paths, add tasks for them in `locustfile.py` (the request-building patterns already used by `provision_pool.py` show the shape) and plan to clean up or use a disposable database afterward.
- **A serious/sustained run will still populate `outbound_messages`/`sms_uploads` significantly** just from `SingleSmsUser`/`BulkSmsUser` doing their job — that's the point, but don't point this at a shared dev database other people rely on without expecting that.

## Spreadsheet payloads

`payloads/personalised.{xlsx,xlsm,xlsb,xls,ods,numbers}` hold a 50-row personalised list (`phone_number,name,amount`). They are committed, and `BulkSmsUser` sends them as-is. To regenerate them, use bulksms-api's own writers (the only `.xlsb` writer):

```bash
../../Personal_Co_code/bulksms-api/.venv/bin/python build_payloads.py
```

If the folder is missing, the spreadsheet task is skipped, not failed.
