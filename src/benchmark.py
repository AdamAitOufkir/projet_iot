"""Benchmark MQTT vs REST vs WebSocket sur le MÊME message de télémétrie.

Pour chaque protocole on envoie N messages (100 par défaut) et on mesure le temps
jusqu'à l'accusé de réception :
    MQTT      : PUBLISH QoS 1 vers Mosquitto       -> PUBACK du broker
    REST      : POST /bench (api.py)               -> réponse HTTP 200
    WebSocket : trame sur /ws/bench (api.py)       -> trame de réponse
On mesure le TRANSPORT seul (les endpoints /bench ne lancent pas le modèle),
pour comparer les protocoles et non le temps de calcul du RandomForest.

Octets : taille du payload JSON + overhead du protocole applicatif (en-têtes MQTT,
en-têtes HTTP, en-têtes de trame WebSocket, accusés). Les en-têtes TCP/IP (~40 o
par paquet) sont communs aux trois et non comptés.

Usage :  python src/benchmark.py [--n 100]
Sortie : reports/benchmark.md et reports/benchmark.csv
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import statistics
import time
from pathlib import Path

import paho.mqtt.client as mqtt
import requests
import websockets

REPORTS = Path(__file__).resolve().parent.parent / "reports"
TIMEOUT = 5.0

# Un message de télémétrie réaliste (identique pour les 3 protocoles)
MESSAGE = {"machine_id": "BENCH", "type": "M", "air_temp_k": 298.1, "process_temp_k": 308.6,
           "rpm": 1551.0, "torque_nm": 42.8, "tool_wear_min": 108.0, "panne_reelle": 0}


def payload(seq: int) -> str:
    return json.dumps({**MESSAGE, "seq": seq, "ts": int(time.time() * 1000)})


# ------------------------------------------------------------------ MQTT
def taille_remaining_length(n: int) -> int:
    """Nombre d'octets du champ 'remaining length' (varint MQTT)."""
    return 1 if n < 128 else 2 if n < 16_384 else 3 if n < 2_097_152 else 4


def bench_mqtt(n: int, host: str) -> dict:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="bench")
    client.connect(host, 1883)
    client.loop_start()
    topic = "bench/telemetry"   # hors de usine/+ : Node-RED ne le traite pas
    client.publish(topic, payload(-1), qos=1).wait_for_publish(timeout=TIMEOUT)   # échauffement
    lat, octets, ok = [], [], 0
    for i in range(n):
        p = payload(i)
        t0 = time.perf_counter()
        info = client.publish(topic, p, qos=1)
        try:
            info.wait_for_publish(timeout=TIMEOUT)
        except (RuntimeError, ValueError):
            pass
        if info.is_published():
            ok += 1
            lat.append((time.perf_counter() - t0) * 1000)
        # PUBLISH = 1 (type/flags) + remaining length + 2 (long. topic) + topic + 2 (packet id) + payload
        reste = 2 + len(topic) + 2 + len(p)
        overhead = 1 + taille_remaining_length(reste) + 2 + len(topic) + 2 + 4   # + PUBACK (4 o)
        octets.append((len(p), overhead))
    client.loop_stop()
    client.disconnect()
    return resume("MQTT (QoS 1)", n, ok, lat, octets)


# ------------------------------------------------------------------ REST
def bench_rest(n: int, api: str) -> dict:
    s = requests.Session()              # keep-alive : la connexion TCP est réutilisée
    s.post(f"{api}/bench", data=payload(-1), timeout=TIMEOUT)   # échauffement (ouverture TCP)
    lat, octets, ok = [], [], 0
    for i in range(n):
        p = payload(i)
        t0 = time.perf_counter()
        try:
            r = s.post(f"{api}/bench", data=p, headers={"Content-Type": "application/json"},
                       timeout=TIMEOUT)
            if r.status_code == 200:
                ok += 1
                lat.append((time.perf_counter() - t0) * 1000)
            # requête : ligne + en-têtes réellement envoyés ; réponse : ligne + en-têtes + corps
            req = len("POST /bench HTTP/1.1\r\n") + sum(
                len(k) + len(v) + 4 for k, v in r.request.headers.items()) + 2
            rep = len(f"HTTP/1.1 {r.status_code} OK\r\n") + sum(
                len(k) + len(v) + 4 for k, v in r.headers.items()) + 2 + len(r.content)
            octets.append((len(p), req + rep))
        except requests.RequestException as exc:
            print(f"   REST message {i} perdu : {type(exc).__name__}")
            octets.append((len(p), 0))
    return resume("REST / HTTP 1.1", n, ok, lat, octets)


# ------------------------------------------------------------------ WebSocket
def entete_ws(n: int, masque: bool) -> int:
    base = 2 if n < 126 else 4 if n < 65_536 else 10
    return base + (4 if masque else 0)   # le client masque ses trames (4 o de clé)


async def _bench_ws(n: int, url: str) -> dict:
    lat, octets, ok = [], [], 0
    async with websockets.connect(url) as ws:   # une seule connexion, réutilisée
        await ws.send(payload(-1))               # échauffement
        await ws.recv()
        for i in range(n):
            p = payload(i)
            t0 = time.perf_counter()
            await ws.send(p)
            try:
                rep = await asyncio.wait_for(ws.recv(), TIMEOUT)
                if json.loads(rep).get("ack") == i:
                    ok += 1
                    lat.append((time.perf_counter() - t0) * 1000)
                overhead = entete_ws(len(p), True) + entete_ws(len(rep), False) + len(rep)
            except asyncio.TimeoutError:
                overhead = entete_ws(len(p), True)
            octets.append((len(p), overhead))
    return resume("WebSocket", n, ok, lat, octets)


def bench_ws(n: int, api: str) -> dict:
    return asyncio.run(_bench_ws(n, api.replace("http", "ws", 1) + "/ws/bench"))


# ------------------------------------------------------------------ Résultats
def resume(nom: str, n: int, ok: int, lat: list[float], octets: list[tuple[int, int]]) -> dict:
    lat_triees = sorted(lat)
    p95 = lat_triees[int(0.95 * (len(lat_triees) - 1))] if lat_triees else float("nan")
    payload_moy = statistics.mean(o[0] for o in octets)
    overhead_moy = statistics.mean(o[1] for o in octets)
    return {
        "protocole": nom,
        "messages": n,
        "latence_moy_ms": round(statistics.mean(lat), 2) if lat else float("nan"),
        "latence_p95_ms": round(p95, 2),
        "payload_octets": round(payload_moy),
        "overhead_octets": round(overhead_moy),
        "total_octets": round(payload_moy + overhead_moy),
        "overhead_pct": round(100 * overhead_moy / (payload_moy + overhead_moy), 1),
        "fiabilite_pct": round(100 * ok / n, 1),
    }


def ecrire(resultats: list[dict]) -> None:
    REPORTS.mkdir(exist_ok=True)
    with open(REPORTS / "benchmark.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=resultats[0].keys())
        w.writeheader()
        w.writerows(resultats)
    entetes = ["Protocole", "Messages", "Latence moy. (ms)", "Latence p95 (ms)", "Payload (o)",
               "Overhead (o)", "Total / msg (o)", "Overhead (%)", "Fiabilité (%)"]
    lignes = ["| " + " | ".join(entetes) + " |", "|" + "---|" * len(entetes)]
    for r in resultats:
        lignes.append("| " + " | ".join(str(v) for v in r.values()) + " |")
    md = ("# Benchmark protocoles : MQTT vs REST vs WebSocket\n\n"
          f"Date : {time.strftime('%Y-%m-%d %H:%M')} · même payload JSON pour les trois · "
          "latence = envoi -> accusé de réception\n\n" + "\n".join(lignes) + "\n")
    (REPORTS / "benchmark.md").write_text(md)
    print(md)


def main() -> None:
    ap = argparse.ArgumentParser(description="Benchmark MQTT / REST / WebSocket")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--mqtt-host", default="127.0.0.1")
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    args = ap.parse_args()

    resultats = []
    for nom, f, cible in [("MQTT", bench_mqtt, args.mqtt_host),
                          ("REST", bench_rest, args.api),
                          ("WebSocket", bench_ws, args.api)]:
        print(f"-> {nom} : {args.n} messages…")
        try:
            resultats.append(f(args.n, cible))
        except Exception as exc:   # service éteint : on le signale sans tout arrêter
            print(f"   échec {nom} : {exc}")
            resultats.append({"protocole": nom, "messages": args.n, "latence_moy_ms": "n/a",
                              "latence_p95_ms": "n/a", "payload_octets": "n/a",
                              "overhead_octets": "n/a", "total_octets": "n/a",
                              "overhead_pct": "n/a", "fiabilite_pct": 0.0})
    ecrire(resultats)


if __name__ == "__main__":
    main()
