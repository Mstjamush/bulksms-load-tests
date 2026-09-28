import hashlib
import hmac
import io
import json
import os
import random
import time
from pathlib import Path

from dotenv import load_dotenv
from faker import Faker

load_dotenv()
fake = Faker()

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
AUTH_API_KEY = os.getenv("AUTH_API_KEY", "dev-secret")
AUTH_TEST_MODE = os.getenv("AUTH_TEST_MODE", "true").strip().lower() == "true"
ADMIN_SUPER_ADMIN_EMAIL = os.getenv("ADMIN_SUPER_ADMIN_EMAIL", "admin@bulksms-platform.com")
ADMIN_SUPER_ADMIN_PASSWORD = os.getenv("ADMIN_SUPER_ADMIN_PASSWORD", "ChangeMe123!")
BULK_CSV_ROWS = int(os.getenv("BULK_CSV_ROWS", "500"))

USER_POOL_PATH = Path(__file__).parent / "data" / "user_pool.json"
BILLED_CLIENT_PATH = Path(__file__).parent / "data" / "billed_client.json"


def _md5(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def _sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def api_key_for(timestamp: str) -> str:
    return _md5(_sha1(AUTH_API_KEY + timestamp))


def _as_text(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def signature_for(flat_body: dict, api_key: str) -> str:
    parts = [f"&{key}={_as_text(flat_body[key])}" for key in sorted(flat_body.keys())]
    canonical = "".join(parts)[1:]  # drop the leading '&'
    return _md5(canonical + api_key)


def signed_headers(body: dict) -> dict:
    if AUTH_TEST_MODE:
        return {}
    timestamp = str(int(time.time()))
    api_key = api_key_for(timestamp)
    return {
        "X-Timestamp": timestamp,
        "X-Api-Key": api_key,
        "X-Signature": signature_for(body, api_key),
    }


def unsigned_multipart_headers() -> dict:
    if AUTH_TEST_MODE:
        return {}
    timestamp = str(int(time.time()))
    return {"X-Timestamp": timestamp, "X-Api-Key": api_key_for(timestamp)}


def random_msisdn() -> str:
    return "2547" + "".join(random.choices("0123456789", k=8))


def random_sms_message() -> str:
    return fake.sentence(nb_words=10)


def build_bulk_csv(rows: int) -> bytes:
    buf = io.StringIO()
    buf.write("phone_number,message\n")
    for _ in range(rows):
        buf.write(f"{random_msisdn()},{random_sms_message()}\n")
    return buf.getvalue().encode("utf-8")


def load_user_pool() -> list:
    if USER_POOL_PATH.exists():
        return json.loads(USER_POOL_PATH.read_text())
    return []


def load_billed_client() -> dict | None:
    if BILLED_CLIENT_PATH.exists():
        return json.loads(BILLED_CLIENT_PATH.read_text())
    return None


def client_signed_request(body: dict, client: dict, path: str = "/api/v1/sms") -> tuple[str, dict]:
    """(JSON text, headers) for a send as a known, billed client. The signature
    is HMAC-SHA256 keyed by the client's api_token over the timestamp, method,
    path and the exact body - so post the returned text as-is (data=, not json=).
    In AUTH_TEST_MODE the API trusts X-Api-Client without a signature."""
    text = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    headers = {"Content-Type": "application/json", "X-Api-Client": str(client["api_client_id"])}
    if AUTH_TEST_MODE:
        return text, headers
    timestamp = str(int(time.time()))
    message = f"{timestamp}\nPOST\n{path}\n{text}"
    signature = hmac.new(client["api_token"].encode(), message.encode(), hashlib.sha256).hexdigest()
    headers.update({"X-Timestamp": timestamp, "X-Signature": signature})
    return text, headers


def build_personalised_csv(rows: int) -> bytes:
    buf = io.StringIO()
    buf.write("phone_number,name,amount\n")
    for _ in range(rows):
        buf.write(f"{random_msisdn()},{fake.first_name()},{random.randint(100, 9000)}\n")
    return buf.getvalue().encode("utf-8")


PAYLOADS_PATH = Path(__file__).parent / "payloads"
SPREADSHEET_MEDIA_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    "xlsb": "application/vnd.ms-excel.sheet.binary.macroEnabled.12",
    "xls": "application/vnd.ms-excel",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "numbers": "application/vnd.apple.numbers",
}
EXPORT_FORMATS = ("csv", *SPREADSHEET_MEDIA_TYPES)

def load_spreadsheet_payloads() -> dict[str, bytes]:
    return {fmt: (PAYLOADS_PATH / f"personalised.{fmt}").read_bytes()
            for fmt in SPREADSHEET_MEDIA_TYPES if (PAYLOADS_PATH / f"personalised.{fmt}").exists()}
