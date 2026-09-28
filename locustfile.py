import random

from locust import HttpUser, task, between

from common import (
    API_BASE_URL,
    EXPORT_FORMATS,
    SPREADSHEET_MEDIA_TYPES,
    ADMIN_SUPER_ADMIN_EMAIL,
    ADMIN_SUPER_ADMIN_PASSWORD,
    BULK_CSV_ROWS,
    build_bulk_csv,
    build_personalised_csv,
    client_signed_request,
    load_billed_client,
    load_spreadsheet_payloads,
    load_user_pool,
    random_msisdn,
    random_sms_message,
    signed_headers,
    unsigned_multipart_headers,
)

BULK_CSV_BYTES = build_bulk_csv(BULK_CSV_ROWS)

PERSONALISED_CSV_BYTES = build_personalised_csv(50)
NUMBERS_ONLY_CSV_BYTES = ("phone_number\n" + "\n".join(random_msisdn() for _ in range(BULK_CSV_ROWS)) + "\n").encode()

SPREADSHEETS = load_spreadsheet_payloads()
USER_POOL = load_user_pool()
BILLED_CLIENT = load_billed_client()


class SingleSmsUser(HttpUser):
    host = API_BASE_URL
    weight = 10
    wait_time = between(0.2, 1.5)

    @task(20)
    def send_single_sms(self):
        body = {
            "to": random_msisdn(),
            "message": random_sms_message(),
            "senderId": "LOADTEST",
        }
        self.client.post(
            "/api/v1/sms",
            json=body,
            headers=signed_headers(body),
            name="/api/v1/sms",
        )

    @task(1)
    def health_check(self):
        self.client.get("/health/live", name="/health/live")


class BilledSmsUser(HttpUser):
    host = API_BASE_URL
    weight = 6
    wait_time = between(0.2, 1.5)

    def on_start(self):
        if BILLED_CLIENT is None:
            print("BilledSmsUser: no data/billed_client.json - run `python provision_billing.py`; skipping")
            self.stop()

    @task
    def send_billed_sms(self):
        body = {"to": random_msisdn(), "message": random_sms_message(), "senderId": BILLED_CLIENT["sender"]}
        text, headers = client_signed_request(body, BILLED_CLIENT)
        self.client.post("/api/v1/sms", data=text, headers=headers, name="/api/v1/sms (billed)")


class BulkSmsUser(HttpUser):
    host = API_BASE_URL
    weight = 1
    wait_time = between(3, 8)

    @task(3)
    def upload_bulk_csv(self):
        files = {"file": ("load_test.csv", BULK_CSV_BYTES, "text/csv")}
        self.client.post(
            "/api/v1/sms/bulk",
            files=files,
            headers=unsigned_multipart_headers(),
            name="/api/v1/sms/bulk",
        )

    @task(1)
    def upload_personalised(self):
        files = {"file": ("personalised.csv", PERSONALISED_CSV_BYTES, "text/csv")}
        self.client.post("/api/v1/sms/bulk", files=files, headers=unsigned_multipart_headers(),
                         data={"message": "Hi {{name}}, your balance is KES {{amount}}."},
                         name="/api/v1/sms/bulk (template)")

    @task(2)
    def upload_spreadsheet(self):
        if not SPREADSHEETS:
            return
        fmt = random.choice(list(SPREADSHEETS))
        files = {"file": (f"personalised.{fmt}", SPREADSHEETS[fmt], SPREADSHEET_MEDIA_TYPES[fmt])}
        self.client.post("/api/v1/sms/bulk", files=files, headers=unsigned_multipart_headers(),
                         data={"message": "Hi {{name}}, your balance is KES {{amount}}."},
                         name=f"/api/v1/sms/bulk (.{fmt})")

    @task(1)
    def upload_numbers_only(self):
        files = {"file": ("numbers.csv", NUMBERS_ONLY_CSV_BYTES, "text/csv")}
        self.client.post("/api/v1/sms/bulk", files=files, headers=unsigned_multipart_headers(),
                         data={"message": "Load test broadcast"}, name="/api/v1/sms/bulk (numbers only)")


class CampaignUser(HttpUser):
    host = API_BASE_URL
    weight = 1
    wait_time = between(5, 15)

    def on_start(self):
        self.token = None
        if BILLED_CLIENT is None:
            print("CampaignUser: no data/billed_client.json - run `python provision_billing.py`; skipping")
            self.stop()
            return
        resp = self.client.post("/api/v1/admin/auth/login", name="/api/v1/admin/auth/login",
                                json={"email": BILLED_CLIENT["admin_email"], "password": BILLED_CLIENT["admin_password"]})
        if resp.status_code == 200:
            self.token = resp.json()["token"]

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    @task
    def list_then_campaign(self):
        if not self.token:
            return
        resp = self.client.post("/api/v1/admin/lists", headers=self._headers(), name="/api/v1/admin/lists (upload)",
                                files={"file": ("audience.csv", PERSONALISED_CSV_BYTES, "text/csv")},
                                data={"name": f"Load test list {random.randint(1, 10**9)}"})
        if resp.status_code != 200:
            return
        list_id = resp.json()["list"]["id"]
        body = {"message": "Hi {{name}}, please pay KES {{amount}} by Friday.", "list_ids": [list_id]}
        self.client.post("/api/v1/admin/campaigns/estimate", json=body, headers=self._headers(),
                         name="/api/v1/admin/campaigns/estimate")
        self.client.post("/api/v1/admin/campaigns", headers=self._headers(), name="/api/v1/admin/campaigns",
                         json={**body, "name": "Load test campaign", "sender_id": BILLED_CLIENT["sender"]})


class AdminConsoleUser(HttpUser):
    host = API_BASE_URL
    weight = 3
    wait_time = between(1, 4)

    def on_start(self):
        if USER_POOL:
            account = random.choice(USER_POOL)
            email, password = account["email"], account["password"]
        else:
            email, password = ADMIN_SUPER_ADMIN_EMAIL, ADMIN_SUPER_ADMIN_PASSWORD

        self.token = None
        self.is_super_admin = False

        with self.client.post(
            "/api/v1/admin/auth/login",
            json={"email": email, "password": password},
            name="/api/v1/admin/auth/login",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"login failed ({resp.status_code}): {resp.text}")
                return
            data = resp.json()
            self.token = data["token"]
            self.is_super_admin = data["user"]["role_name"] == "Super Administrator"

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @task(10)
    def view_me(self):
        if not self.token:
            return
        self.client.get("/api/v1/admin/me", headers=self._auth_headers(), name="/api/v1/admin/me")

    @task(5)
    def view_senders(self):
        if not self.token:
            return
        self.client.get("/api/v1/admin/senders", headers=self._auth_headers(), name="/api/v1/admin/senders")

    @task(5)
    def view_users(self):
        if not self.token:
            return
        self.client.get("/api/v1/admin/users", headers=self._auth_headers(), name="/api/v1/admin/users")

    @task(3)
    def view_bulk_campaigns(self):
        if not self.token:
            return
        self.client.get(
            "/api/v1/admin/bulk-campaigns", headers=self._auth_headers(), name="/api/v1/admin/bulk-campaigns"
        )

    @task(3)
    def view_reports(self):
        if not self.token:
            return
        self.client.get("/api/v1/admin/reports/overview?days=30", headers=self._auth_headers(),
                        name="/api/v1/admin/reports/overview")
        self.client.get("/api/v1/admin/reports/daily?days=30", headers=self._auth_headers(),
                        name="/api/v1/admin/reports/daily")

    @task(3)
    def view_campaigns_and_lists(self):
        if not self.token:
            return
        self.client.get("/api/v1/admin/campaigns?limit=25", headers=self._auth_headers(), name="/api/v1/admin/campaigns")
        self.client.get("/api/v1/admin/lists?limit=25", headers=self._auth_headers(), name="/api/v1/admin/lists")

    @task(1)
    def export_report(self):
        if not self.token:
            return
        fmt = random.choice(EXPORT_FORMATS)
        self.client.get(f"/api/v1/admin/reports/daily.{fmt}?days=30", headers=self._auth_headers(),
                        name=f"/api/v1/admin/reports/daily.{fmt}")

    @task(2)
    def view_billing(self):
        if not self.token or self.is_super_admin:
            return
        self.client.get("/api/v1/admin/billing/summary", headers=self._auth_headers(),
                        name="/api/v1/admin/billing/summary")

    @task(2)
    def view_clients(self):
        if not self.token or not self.is_super_admin:
            return
        self.client.get("/api/v1/admin/clients", headers=self._auth_headers(), name="/api/v1/admin/clients")
