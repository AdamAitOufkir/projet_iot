"""COUCHE CAPTEUR : rejoue le jeu de test AI4I 2020 comme si 3 machines envoyaient leurs mesures.

Chaque ligne du CSV devient un message JSON publié en MQTT (QoS 1) sur :
    usine/<machine_id>/telemetry

Usage :
    python src/simulator.py                      # 1 message / seconde, en boucle
    python src/simulator.py --interval 0.5 --limit 100
    python src/simulator.py --demo               # ~20 % de lignes "panne" pour voir vite une alarme
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd
import paho.mqtt.client as mqtt

TEST_CSV = Path(__file__).resolve().parent.parent / "data" / "test.csv"
COLONNES = ["type", "air_temp_k", "process_temp_k", "rpm", "torque_nm", "tool_wear_min", "panne_reelle"]


def charger(demo: bool) -> pd.DataFrame:
    df = pd.read_csv(TEST_CSV)[COLONNES]
    if demo:   # on sur-représente les pannes pour la démonstration
        pannes = df[df.panne_reelle == 1]
        normales = df[df.panne_reelle == 0].sample(len(pannes) * 4, random_state=1)
        df = pd.concat([pannes, normales]).sample(frac=1, random_state=1)
    return df.reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Simulateur de capteurs (rejeu AI4I via MQTT)")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--interval", type=float, default=1.0, help="secondes entre deux messages")
    ap.add_argument("--limit", type=int, default=0, help="nombre de messages (0 = infini)")
    ap.add_argument("--machines", default="M1,M2,M3")
    ap.add_argument("--demo", action="store_true", help="plus de pannes pour la démo")
    args = ap.parse_args()

    machines = args.machines.split(",")
    df = charger(args.demo)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="simulateur-ai4i")
    client.connect(args.host, args.port, keepalive=60)
    client.loop_start()   # thread réseau de paho (gère les PUBACK, la reconnexion…)
    print(f"Connecté à mqtt://{args.host}:{args.port} | {len(df)} lignes | machines {machines}")

    envoyes = 0
    try:
        while args.limit == 0 or envoyes < args.limit:
            ligne = df.iloc[envoyes % len(df)]
            machine = machines[envoyes % len(machines)]
            message = {
                "machine_id": machine,
                "ts": int(time.time() * 1000),
                "type": ligne["type"],
                "air_temp_k": float(ligne["air_temp_k"]),
                "process_temp_k": float(ligne["process_temp_k"]),
                "rpm": float(ligne["rpm"]),
                "torque_nm": float(ligne["torque_nm"]),
                "tool_wear_min": float(ligne["tool_wear_min"]),
                "panne_reelle": int(ligne["panne_reelle"]),
            }
            info = client.publish(f"usine/{machine}/telemetry", json.dumps(message), qos=1)
            info.wait_for_publish(timeout=5)   # QoS 1 : on attend l'accusé PUBACK du broker
            envoyes += 1
            etat = "PANNE" if message["panne_reelle"] else "ok"
            print(f"[{envoyes:5d}] {machine} rpm={message['rpm']:.0f} "
                  f"couple={message['torque_nm']:.1f} usure={message['tool_wear_min']:.0f} -> {etat}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()
        print(f"Arrêt : {envoyes} messages envoyés.")


if __name__ == "__main__":
    main()
