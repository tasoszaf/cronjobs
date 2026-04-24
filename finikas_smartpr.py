#!/usr/bin/env python
# -*- coding: utf-8 -*-

import requests
import pandas as pd
from datetime import datetime, timedelta
import os
import time

# =====================================================
# CONFIG
# =====================================================
API_URL_AVAIL = "https://login.smoobu.com/booking/checkApartmentAvailability"
API_URL_RATES = "https://login.smoobu.com/api/rates"

CUSTOMER_ID = int(os.getenv("SMOOBU_CUSTOMER_ID"))
API_KEY = os.getenv("SMOOBU_API_KEY")

# Σειρά καταλυμάτων (η σειρά καθορίζει τις τιμές)
APARTMENTS = [
    2715198, 2715203, 2715218, 2715223, 2715238,
    2715273, 2715193, 2715208, 2715213, 2715228, 2715233
]

# Ελάχιστη τιμή για ΣΗΜΕΡΑ ανά μήνα
MIN_PRICE_SAME_DAY_BY_MONTH = {
    1: 50, 2: 50, 3: 55, 4: 60,
    5: 70, 6: 80, 7: 80, 8: 80,
    9: 80, 10: 70, 11: 50, 12: 50
}

TEST_MODE = True  # True = δεν στέλνει στο Smoobu

PREMIUM_SURCHARGE = {
    2715228: 30,
    2715233: 50,
}
PREMIUM_MONTHS = {5, 6, 7, 8, 9}
# =====================================================
# LOAD EXCEL
# =====================================================
df = pd.read_excel("data_finikas.xlsx")
df["date"] = pd.to_datetime(df["date"]).dt.date  # ασφαλής σύγκριση ημερομηνιών

headers = {
    "Api-Key": API_KEY,
    "Content-Type": "application/json"
}

# =====================================================
# AVAILABILITY (με retry + timeout)
# =====================================================
def get_total_occupancy(date_str, apartment_ids, retries=3, timeout_sec=10):
    """
    Παίρνει συνολική πληρότητα & διαθέσιμα καταλύματα
    """
    for attempt in range(1, retries + 1):
        try:
            payload = {
                "arrivalDate": date_str,
                "departureDate": (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d"),
                "apartments": apartment_ids,
                "customerId": CUSTOMER_ID
            }
            r = requests.post(API_URL_AVAIL, json=payload, headers=headers, timeout=timeout_sec)
            r.raise_for_status()
            data = r.json()
            available = data.get("availableApartments", [])
            occupied = len(apartment_ids) - len(available)
            total_occ = occupied / len(apartment_ids) if apartment_ids else 0
            return total_occ, available
        except requests.exceptions.RequestException as e:
            print(f"⚠ Availability attempt {attempt} failed for {date_str}: {e}")
            time.sleep(2)
    print(f"❌ Availability failed for {date_str}")
    return None, []

# =====================================================
# PRICE CALCULATION
# =====================================================
def calculate_price(current_occ, target_date, now):
    """
    Υπολογίζει:
    - Base price
    - Composite score x
    - Min/Max τιμές
    """
    difference = (target_date - now.date()).days

    # Εκτός ορίων (πριν ή πολύ μακριά)
    if difference < 0 or difference > 365:
        return None, None, None, None

    row = df.loc[df["date"] == target_date]
    if row.empty:
        return None, None, None, None

    target_price = float(row["target_price"].iloc[0])
    max_price = float(row["max_price"].iloc[0])
    min_price = MIN_PRICE_SAME_DAY_BY_MONTH[target_date.month] if difference == 0 else float(row["min_price"].iloc[0])

    # =================================================
    # 🔴 ΣΗΜΕΡΑ → ΩΡΙΑΙΑ ΛΟΓΙΚΗ
    # =================================================
    if difference == 0:
        hours_left = max(1, 23 - now.hour)

        if current_occ == 0:
            # Καθόλου κρατήσεις → μόνο pacing
            x = (hours_left - 263) / hours_left
        else:
            # Βρίσκουμε το row που έχει sum_occupancy_days_ahead πιο κοντά στο current_occ
            temp = df.copy()
            temp["diff_occ"] = abs(temp["sum_occupancy_days_ahead"] - current_occ)
            closest = temp.loc[temp["diff_occ"].idxmin()]
            closest_hour = int(closest["hours_diff"])

            pace_ratio = (hours_left - closest_hour) / hours_left

            if hours_left in df["hours_diff"].values:
                plan_occ = float(df.loc[df["hours_diff"] == hours_left]["sum_occupancy_days_ahead"].values[0])
            else:
                plan_occ = current_occ

            denom = min(current_occ, plan_occ) if plan_occ > 0 else 1
            occupancy_ratio = max(current_occ, plan_occ) / denom
            x = pace_ratio * occupancy_ratio

        # Υπολογισμός τελικής τιμής
        if x >= 0:
            price = x * (max_price - target_price) + target_price
        else:
            price = x * (target_price - min_price) + target_price

        price = max(min_price, min(price, max_price))
        return round(price, 2), round(x, 4), min_price, max_price

    # =================================================
    # 🟢 ΜΕΛΛΟΝΤΙΚΕΣ ΗΜΕΡΕΣ → ΗΜΕΡΕΣ
    # =================================================
    # Long-term >240 μέρες
    if difference > 240:
        return round(target_price + 20, 2), None, None, None

    if current_occ == 0:
        x = (difference - 240) / difference
    else:
        temp = df.copy()
        temp["diff_occ"] = abs(temp["sum_occupancy_days_ahead"] - current_occ)
        closest = temp.loc[temp["diff_occ"].idxmin()]
        plan_day = int(closest.get("days_diff", difference))

        pace_ratio = (difference - plan_day) / difference

        if difference in df["days_diff"].values:
            plan_occ = float(df.loc[df["days_diff"] == difference]["sum_occupancy_days_ahead"].values[0])
        else:
            plan_occ = current_occ

        denom = min(current_occ, plan_occ) if plan_occ > 0 else 1
        occupancy_ratio = max(current_occ, plan_occ) / denom
        x = pace_ratio * occupancy_ratio

    if x >= 0:
        price = x * (max_price - target_price) + target_price
    else:
        price = x * (target_price - min_price) + target_price

    price = max(min_price, min(price, max_price))
    return round(price, 2), round(x, 4), min_price, max_price

# =====================================================
# SEND PRICE (με retry)
# =====================================================
def send_price(apartment_id, date_str, price, retries=3, timeout_sec=10):
    payload = {
        "apartments": [apartment_id],
        "operations": [{"dates": [date_str], "daily_price": price, "min_length_of_stay": 1}]
    }

    for attempt in range(1, retries + 1):
        try:
            if TEST_MODE:
                print(f"[TEST] {date_str} | Apt {apartment_id} → {price}")
                return

            r = requests.post(API_URL_RATES, json=payload, headers=headers, timeout=timeout_sec)
            r.raise_for_status()
            print(f"✓ Sent {price}€ for {date_str} → Smoobu")
            return
        except requests.exceptions.RequestException as e:
            print(f"⚠ Send attempt {attempt} failed for Apt {apartment_id}: {e}")
            time.sleep(2)

    print(f"❌ Failed to send price for Apt {apartment_id} on {date_str} after {retries} attempts")

# =====================================================
# MAIN LOOP
# =====================================================
now = datetime.now()
current = now.date()
end = current + timedelta(days=190)

while current <= end:
    date_str = current.strftime("%Y-%m-%d")

    occ, available = get_total_occupancy(date_str, APARTMENTS)
    if occ is None or not available:
        print(f"❌ {date_str} | No available apartments or failed to get occupancy")
        current += timedelta(days=1)
        continue

    price, x, min_p, max_p = calculate_price(occ, current, now)
    if price is None:
        print(f"⚠ {date_str} | Pricing calculation failed")
        current += timedelta(days=1)
        continue

    # Διατήρηση σειράς APARTMENTS για διαθέσιμα
    available_sorted = [apt for apt in APARTMENTS if apt in available]

    if max_p is None:
        for apt in available_sorted:
            final_price = price
            if apt in PREMIUM_SURCHARGE and current.month in PREMIUM_MONTHS:
                final_price = round(price + PREMIUM_SURCHARGE[apt], 1)
            send_price(apt, date_str, final_price)
    else:
        step = (max_p - price) / len(available_sorted) if len(available_sorted) > 0 else 0
        for i, apt in enumerate(available_sorted, start=1):
            price_i = price + (i-1)*step
            price_i = min(price_i, max_p)
            price_i = round(price_i, 1)
            if apt in PREMIUM_SURCHARGE and current.month in PREMIUM_MONTHS:
                price_i = round(price_i + PREMIUM_SURCHARGE[apt], 1)
            send_price(apt, date_str, price_i)

    print(f"✅ {date_str} | Occ={occ:.4f} | x={x} | Base Price={price}")
    current += timedelta(days=1)

print("\nFinished processing all valid dates.")
