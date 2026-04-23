#!/usr/bin/env python
# -*- coding: utf-8 -*-

import requests
from datetime import datetime, timedelta
import time
import os
from collections import defaultdict

# ---------------- SETTINGS ----------------
RETRY_LIMIT = 3
SLEEP_BETWEEN_REQUESTS = 1
TEST_MODE = False

CUSTOMER_ID = int(os.getenv("PENTHOUSE_SMOOBU_CUSTOMER_ID"))
API_KEY = os.getenv("PENTHOUSE_SMOOBU_API_KEY")

headers = {
    "Api-Key": API_KEY,
    "Content-Type": "application/json"
}

GROUPS = {
    "PENTHOUSE": {"apartments": [830350, 1713455, 830344, 830347, 1663210, 830323], "max_drop": 0.25},
}

URGENCY_WINDOW = 4
FLOOR_PRICE = 52

today = datetime.today().date()


# ---------------- HELPERS ----------------
def safe_request(method, url, **kwargs):
    for attempt in range(RETRY_LIMIT):
        try:
            response = requests.request(method, url, timeout=10, headers=headers, **kwargs)
            if response.status_code == 200:
                return response
        except requests.RequestException:
            pass
        time.sleep(SLEEP_BETWEEN_REQUESTS)
    raise Exception(f"Αποτυχια {method} στο {url}")


def get_apartments():
    url = "https://login.smoobu.com/api/apartments"
    response = safe_request("GET", url)
    return [apt["id"] for apt in response.json().get("apartments", [])]


def get_existing_rates(apartment_id, start_date, end_date):
    url = "https://login.smoobu.com/api/rates"
    params = {"start_date": start_date, "end_date": end_date, "apartments[]": apartment_id}
    response = safe_request("GET", url, params=params)
    return response.json()


def get_group_discount(apartment_id):
    for group in GROUPS.values():
        if apartment_id in group["apartments"]:
            return group["max_drop"]
    return 0.0


def is_available(day_info: dict) -> bool:
    return bool(day_info.get("available", 1))


# ---------------- RATE CALCULATION ----------------
def calculate_discounted_rates(rates_data, apartment_id):
    operations = []
    date_grouped_prices = {}

    max_drop = get_group_discount(apartment_id)
    apt_data = rates_data.get("data", {}).get(str(apartment_id), {})

    for delta in range(URGENCY_WINDOW, -1, -1):
        target_date = today + timedelta(days=delta)
        day_info = apt_data.get(target_date.isoformat(), {})

        if not is_available(day_info):
            continue

        day_price = day_info.get("price")
        if day_price is None:
            continue

        discount = (max_drop / (URGENCY_WINDOW + 1)) * (URGENCY_WINDOW - delta + 1)
        new_price = round(max(day_price * (1 - discount), FLOOR_PRICE))

        operations.append({
            "dates": [target_date.isoformat()],
            "daily_price": new_price,
            "min_length_of_stay": day_info.get("min_length_of_stay", 1)
        })

        date_grouped_prices.setdefault(target_date.isoformat(), []).append(
            (apartment_id, new_price)
        )

    return operations, date_grouped_prices


# ---------------- SEND OR PREVIEW ----------------
def process_rates(apartment_id, operations):
    if not TEST_MODE:
        url = "https://login.smoobu.com/api/rates"
        payload = {"apartments": [apartment_id], "operations": operations}
        safe_request("POST", url, json=payload)


# ---------------- MAIN ----------------
def main():
    if TEST_MODE:
        print("\n[TEST MODE] DEN apostelontai sto Smoobu\n")
    else:
        print("\n[LIVE] Apostelontai sto Smoobu\n")

    start = today.isoformat()
    end = (today + timedelta(days=URGENCY_WINDOW)).isoformat()
    valid_apartment_ids = [apt_id for group in GROUPS.values() for apt_id in group["apartments"]]

    try:
        all_apartments = get_apartments()
        apartment_ids = [apt_id for apt_id in all_apartments if apt_id in valid_apartment_ids]
    except Exception as e:
        print(f"Sfalma fortosis: {e}")
        return

    if not apartment_ids:
        print("Den vrethikan egkyra katalymata.")
        return

    all_dates_prices = defaultdict(list)

    for apt_id in apartment_ids:
        try:
            rates_data = get_existing_rates(apt_id, start, end)
            operations, date_grouped_prices = calculate_discounted_rates(rates_data, apt_id)
            for dt, entries in date_grouped_prices.items():
                all_dates_prices[dt].extend(entries)
            process_rates(apt_id, operations)
        except Exception as e:
            print(f"Sfalma gia {apt_id}: {e}")
        time.sleep(SLEEP_BETWEEN_REQUESTS)

    print("\n================== PROEPISKOPISI ==================")
    for dt in sorted(all_dates_prices):
        print(dt)
        for apt_id, new_price in all_dates_prices[dt]:
            print(f"  {apt_id} | {new_price}EUR")
        print()


main()
