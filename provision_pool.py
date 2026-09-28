import argparse
import json

import requests

from common import (
    ADMIN_SUPER_ADMIN_EMAIL,
    ADMIN_SUPER_ADMIN_PASSWORD,
    API_BASE_URL,
    USER_POOL_PATH,
    load_user_pool,
    random_msisdn,
)

# AdminRoles.CLIENT_ADMIN - see bulksms-api's app/admin/roles.py. A fixed,
CLIENT_ADMIN_ROLE_ID = 2


def login(email: str, password: str) -> str:
    resp = requests.post(f"{API_BASE_URL}/api/v1/admin/auth/login", json={"email": email, "password": password})
    resp.raise_for_status()
    return resp.json()["token"]


def create_client(token: str, suffix: str) -> int:
    resp = requests.post(
        f"{API_BASE_URL}/api/v1/admin/clients",
        json={
            "client_name": f"Load Test Client {suffix}",
            "client_email": f"loadtest.client.{suffix}@example.com",
            "address": "Nairobi",
            "country": "KENYA",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    return resp.json()["client_id"]


def create_client_admin(token: str, client_id: int, suffix: str) -> dict:
    email = f"loadtest.admin.{suffix}@example.com"
    password = "LoadTest123!"
    resp = requests.post(
        f"{API_BASE_URL}/api/v1/admin/users",
        json={
            "email_address": email,
            "full_names": "Load Test Admin",
            "password": password,
            "msisdn": random_msisdn(),
            "role_id": CLIENT_ADMIN_ROLE_ID,
            "client_id": client_id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    return {"email": email, "password": password}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=20, help="Number of Client Administrator accounts to add")
    parser.add_argument("--replace", action="store_true", help="Overwrite the existing pool instead of appending to it")
    args = parser.parse_args()

    print(f"Logging in as {ADMIN_SUPER_ADMIN_EMAIL} ({API_BASE_URL})...")
    token = login(ADMIN_SUPER_ADMIN_EMAIL, ADMIN_SUPER_ADMIN_PASSWORD)

    pool = [] if args.replace else load_user_pool()
    for i in range(args.count):
        suffix = f"{len(pool):04d}{random_msisdn()[-4:]}"
        client_id = create_client(token, suffix)
        account = create_client_admin(token, client_id, suffix)
        pool.append(account)
        print(f"  [{i + 1}/{args.count}] {account['email']} (client_id={client_id})")

    USER_POOL_PATH.parent.mkdir(parents=True, exist_ok=True)
    USER_POOL_PATH.write_text(json.dumps(pool, indent=2))
    print(f"\nWrote {len(pool)} account(s) total to {USER_POOL_PATH}")


if __name__ == "__main__":
    main()
