"""REST : récupération de l'historique ThingsBoard pour ré-entraîner le modèle (pull batch).

    POST /api/auth/login                                         -> jeton JWT
    GET  /api/tenant/devices?deviceName=M1                       -> id du device
    GET  /api/plugins/telemetry/DEVICE/{id}/values/timeseries    -> historique

Usage :
    python src/rest_history.py                  # dernières 24 h, machines M1,M2,M3
    python src/rest_history.py --hours 2 --machines M1
Sortie : data/history.csv (une ligne par (machine, horodatage))
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd
import requests

KEYS = ["air_temp_k", "process_temp_k", "rpm", "torque_nm", "tool_wear_min",
        "panne_probable", "panne_reelle"]
SORTIE = Path(__file__).resolve().parent.parent / "data" / "history.csv"


def login(base: str, user: str, password: str) -> str:
    r = requests.post(f"{base}/api/auth/login", json={"username": user, "password": password}, timeout=10)
    r.raise_for_status()
    return r.json()["token"]


def historique(base: str, jwt: str, machine: str, hours: float) -> pd.DataFrame:
    h = {"X-Authorization": f"Bearer {jwt}"}
    r = requests.get(f"{base}/api/tenant/devices", params={"deviceName": machine}, headers=h, timeout=10)
    r.raise_for_status()
    device_id = r.json()["id"]["id"]

    fin = int(time.time() * 1000)
    params = {
        "keys": ",".join(KEYS),
        "startTs": fin - int(hours * 3600 * 1000),
        "endTs": fin,
        "limit": 50_000,
        "agg": "NONE",
    }
    r = requests.get(f"{base}/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries",
                     params=params, headers=h, timeout=30)
    r.raise_for_status()
    # Réponse : {"rpm": [{"ts": 1700000000000, "value": "1500"}, ...], "torque_nm": [...]}
    series = []
    for key, points in r.json().items():
        s = pd.DataFrame(points).set_index("ts")["value"].astype(float).rename(key)
        series.append(s)
    if not series:
        return pd.DataFrame()
    df = pd.concat(series, axis=1).reset_index().sort_values("ts")
    df.insert(0, "machine_id", machine)
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description="Historique ThingsBoard via REST")
    ap.add_argument("--url", default="http://localhost:8080")
    ap.add_argument("--user", default="tenant@thingsboard.org")
    ap.add_argument("--password", default="tenant")
    ap.add_argument("--machines", default="M1,M2,M3")
    ap.add_argument("--hours", type=float, default=24)
    args = ap.parse_args()

    jwt = login(args.url, args.user, args.password)
    frames = []
    for m in args.machines.split(","):
        df = historique(args.url, jwt, m, args.hours)
        print(f"{m} : {len(df)} points récupérés")
        frames.append(df)
    total = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    SORTIE.parent.mkdir(exist_ok=True)
    total.to_csv(SORTIE, index=False)
    print(f"-> {SORTIE} ({len(total)} lignes) : prêt pour un ré-entraînement")


if __name__ == "__main__":
    main()
