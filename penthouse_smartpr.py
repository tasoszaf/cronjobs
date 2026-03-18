#!/usr/bin/env python
# -*- coding: utf-8 -*-

import requests
from datetime import datetime, timedelta
import time
import os

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
    "PENTHOUSE": {"apartments": [830350,1713455,830344,830347,1663210,830323], "perc_discount": 0.10},
   
    
}

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
    raise Exception(f"❌ Αποτυχία {method} στο {url} μετά από {RETRY_LIMIT} προσπάθειες")

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
            return group["perc_discount"]
    return 0.0

# ---------------- RATE CALCULATION ----------------
def calculate_discounted_rates(rates_data, apartment_id):
    operations = []
    perc_discount = get_group_discount(apartment_id)
    total_days = 7  

    for delta in range(0, total_days + 1):
        target_date = today + timedelta(days=delta)

        # Διαθεσιμότητα με min_stay
        day_info = rates_data.get("data", {}).get(str(apartment_id), {}).get(target_date.isoformat(), {})
        available = day_info.get("available", False)
        min_stay = day_info.get("min_length_of_stay", 1)

        if not available:
            continue

        current_price = day_info.get("price")
        if current_price is None:
            continue

        # Υπολογισμός έκπτωσης
        if delta == 0:
            discount_percent = perc_discount + 0.1
        else:
            discount_percent = perc_discount * (total_days - delta + 1) / total_days

        
        new_price = current_price * (1 - discount_percent)
        new_price = round(max(new_price, 52))  # όριο 52€

        operations.append({
            "dates": [target_date.isoformat()],
            "daily_price": new_price,
            "min_length_of_stay": min_stay
        })

        # Καθαρή εκτύπωση
        print(f"{apartment_id} | {target_date.isoformat()} | {current_price}€ → {new_price}€")

    return operations

# ---------------- SEND OR PREVIEW ----------------
def process_rates(apartment_id, operations):
    if TEST_MODE:
        print(f"\n[TEST MODE] Προεπισκόπηση τιμών για κατάλυμα {apartment_id}\n")
    else:
        url = "https://login.smoobu.com/api/rates"
        payload = {"apartments": [apartment_id], "operations": operations}
        safe_request("POST", url, json=payload)

# ---------------- MAIN ----------------
def main():
    start = today.isoformat()
    end = (today + timedelta(days=7)).isoformat()
    valid_apartment_ids = [apt_id for group in GROUPS.values() for apt_id in group["apartments"]]

    try:
        all_apartments = get_apartments()
        apartment_ids = [apt_id for apt_id in all_apartments if apt_id in valid_apartment_ids]
    except Exception as e:
        print(f"Σφάλμα φόρτωσης καταλυμάτων: {e}")
        return

    for apt_id in apartment_ids:
        rates_data = get_existing_rates(apt_id, start, end)
        operations = calculate_discounted_rates(rates_data, apt_id)
        if operations:
            process_rates(apt_id, operations)
        time.sleep(SLEEP_BETWEEN_REQUESTS)

# Εκτέλεση
main()
