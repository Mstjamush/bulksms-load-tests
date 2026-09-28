import argparse
import json
import uuid

import requests

from common import (
    ADMIN_SUPER_ADMIN_EMAIL,
    ADMIN_SUPER_ADMIN_PASSWORD,
    API_BASE_URL,
    BILLED_CLIENT_PATH,
    random_msisdn,
)

CLIENT_ADMIN_ROLE_ID = 2


def _post(path: str, token: str, body: dict) -> dict:
    resp = requests.post(f"{API_BASE_URL}{path}", json=body, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code >= 400:
        raise SystemExit(f"{path} failed ({resp.status_code}): {resp.text}")
    return resp.json()


def login(email: str, password: str) -> str:
    resp = requests.post(f"{API_BASE_URL}/api/v1/admin/auth/login", json={"email": email, "password": password})
    resp.raise_for_status()
    return resp.json()["token"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--credit", type=float, default=100000, help="KES topped up into the wallet")
    args = parser.parse_args()

    suffix = uuid.uuid4().hex[:8]
    super_token = login(ADMIN_SUPER_ADMIN_EMAIL, ADMIN_SUPER_ADMIN_PASSWORD)
    client = _post("/api/v1/admin/clients", super_token, {
        "client_name": f"Load Test Billed Client {suffix}",
        "client_email": f"loadtest.billed.{suffix}@example.com",
        "address": "Nairobi", "country": "KENYA",
    })
    email, password = f"loadtest.billed.admin.{suffix}@example.com", "LoadTest123!"
    _post("/api/v1/admin/users", super_token, {
        "email_address": email, "full_names": "Load Test Billed Admin", "password": password,
        "msisdn": random_msisdn(), "role_id": CLIENT_ADMIN_ROLE_ID, "client_id": client["client_id"],
    })
    _post(f"/api/v1/admin/billing/clients/{client['client_id']}/topup", super_token,
          {"amount": f"{args.credit:.2f}", "reference": f"LOADTEST-{suffix}", "note": "Load test credit"})

    admin_token = login(email, password)
    sender = f"LTB{suffix[:6].upper()}"
    _post("/api/v1/admin/senders", admin_token, {"short_code": sender, "send_type_id": 1})
    creds = requests.get(f"{API_BASE_URL}/api/v1/admin/api-credentials",
                         headers={"Authorization": f"Bearer {admin_token}"}).json()

    BILLED_CLIENT_PATH.parent.mkdir(exist_ok=True)
    BILLED_CLIENT_PATH.write_text(json.dumps({
        "client_id": client["client_id"], "api_client_id": creds["api_client_id"], "api_token": creds["api_token"],
        "sender": sender, "admin_email": email, "admin_password": password,
    }, indent=2))
    print(f"Billed client {client['client_id']} (API client {creds['api_client_id']}, sender {sender}) "
          f"with KES {args.credit:,.2f} -> {BILLED_CLIENT_PATH}")


if __name__ == "__main__":
    main()
