"""Synthetic payment data. Entirely random — no real customers, institutions or amounts."""

import random
from datetime import date, timedelta
from decimal import Decimal

CHANNELS = ["WALLET", "CARD", "INTERBANK", "BILL_PAYMENT", "MERCHANT", "AGENT_FUNDING"]
INSTITUTIONS = [f"INST{n:03d}" for n in range(1, 9)]


def rrn() -> str:
    return f"{random.randrange(10**11, 10**12)}"


def amount(channel: str) -> Decimal:
    high = {"INTERBANK": 20000, "AGENT_FUNDING": 50000}.get(channel, 3000)
    return Decimal(random.randint(1000, high * 100)) / 100


def transaction(value_date: date) -> dict:
    channel = random.choice(CHANNELS)
    return {
        "rrn": rrn(),
        "amount": amount(channel),
        "currency": "MAD",
        "value_date": value_date,
        "channel": channel,
        "institution_code": random.choice(INSTITUTIONS),
    }


def settlement_rows(txns: list[dict], anomalies: bool = True) -> list[dict]:
    """Settlement rows for the given transactions, with a realistic sprinkle of breaks:
    ~2% never settled, ~2% wrong amount, ~1% wrong value date, ~1% unknown RRN."""
    rows = []
    for t in txns:
        r = random.random()
        if anomalies and r < 0.02:
            continue  # will become MISSING_IN_SETTLEMENT after the grace period
        row = {k: t[k] for k in ("rrn", "amount", "currency", "value_date", "institution_code")}
        if anomalies and r < 0.04:
            row["amount"] = t["amount"] + Decimal(random.choice([-1, 1]) * random.randint(1, 5000)) / 100
            row["amount"] = max(row["amount"], Decimal("0.01"))
        elif anomalies and r < 0.05:
            row["value_date"] = t["value_date"] + timedelta(days=1)
        rows.append(row)
    if anomalies:
        for _ in range(max(0, round(len(txns) * 0.01 + random.uniform(-0.5, 0.5)))):
            ghost = transaction(txns[0]["value_date"] if txns else date.today())
            rows.append({k: ghost[k] for k in ("rrn", "amount", "currency", "value_date", "institution_code")})
    random.shuffle(rows)
    return rows
