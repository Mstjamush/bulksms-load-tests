import os
import random

from locust import FastHttpUser, LoadTestShape, constant_throughput, task

from common import API_BASE_URL, client_signed_request, load_billed_client, random_msisdn, random_sms_message, signed_headers

BILLED_CLIENT = load_billed_client()
BILLED_SHARE = float(os.getenv("THROUGHPUT_BILLED_SHARE", "0.5")) if BILLED_CLIENT else 0.0
STEPS = [int(x) for x in os.getenv("THROUGHPUT_STEPS", "100,300,500,700").split(",")]
STEP_SECONDS = int(os.getenv("STEP_SECONDS", "60"))


class ThroughputUser(FastHttpUser):
    host = API_BASE_URL
    wait_time = constant_throughput(1)

    @task
    def send(self):
        if random.random() < BILLED_SHARE:
            body = {"to": random_msisdn(), "message": random_sms_message(), "senderId": BILLED_CLIENT["sender"]}
            text, headers = client_signed_request(body, BILLED_CLIENT)
            self.client.post("/api/v1/sms", data=text, headers=headers, name="/api/v1/sms (billed)")
        else:
            body = {"to": random_msisdn(), "message": random_sms_message(), "senderId": "LOADTEST"}
            self.client.post("/api/v1/sms", json=body, headers=signed_headers(body), name="/api/v1/sms")


class StepShape(LoadTestShape):
    def tick(self):
        step = int(self.get_run_time() // STEP_SECONDS)
        if step >= len(STEPS):
            return None
        return STEPS[step], max(50, STEPS[step] // 5)
