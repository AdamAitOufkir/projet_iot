"""Configuration automatique de Node-RED et ThingsBoard (optionnel).

Ce script fait EXACTEMENT les étapes manuelles décrites dans docs/05_deroulement_demo.md,
pour gagner du temps avant une démo :
  Node-RED    : importe configs/nodered_flow.json (API admin POST /flows)
  ThingsBoard : - crée les devices M1, M2, M3
                - ajoute l'attribut partagé threshold = 0.7 sur chacun
                - crée le device passerelle "Node-RED Gateway" (token NODERED_GATEWAY_TOKEN)
                - importe configs/tb_rule_chain.json et la définit comme rule chain racine

Usage :  python scripts/setup_plateformes.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TB = "http://localhost:8080"
NODERED = "http://localhost:1880"
MACHINES = ["M1", "M2", "M3"]
GATEWAY_NAME, GATEWAY_TOKEN = "Node-RED Gateway", "NODERED_GATEWAY_TOKEN"


def attendre(url: str, nom: str, essais: int = 60) -> None:
    for _ in range(essais):
        try:
            if requests.get(url, timeout=3).status_code == 200:
                print(f"[ok] {nom} disponible")
                return
        except requests.RequestException:
            pass
        time.sleep(5)
    sys.exit(f"[x] {nom} ne répond pas ({url})")


def setup_nodered() -> None:
    flow = json.loads((ROOT / "configs" / "nodered_flow.json").read_text(encoding="utf-8"))
    r = requests.post(f"{NODERED}/flows", json=flow,
                      headers={"Node-RED-Deployment-Type": "full"}, timeout=10)
    r.raise_for_status()
    print("[ok] Flux Node-RED importé et déployé")


def setup_thingsboard() -> None:
    jwt = requests.post(f"{TB}/api/auth/login", timeout=10,
                        json={"username": "tenant@thingsboard.org", "password": "tenant"}).json()["token"]
    h = {"X-Authorization": f"Bearer {jwt}"}

    def device(nom: str, gateway: bool = False, token: str | None = None) -> str:
        r = requests.get(f"{TB}/api/tenant/devices", params={"deviceName": nom}, headers=h, timeout=10)
        if r.status_code == 200:
            return r.json()["id"]["id"]
        body = {"name": nom, "type": "default", "additionalInfo": {"gateway": gateway}}
        params = {"accessToken": token} if token else {}
        r = requests.post(f"{TB}/api/device", json=body, params=params, headers=h, timeout=10)
        r.raise_for_status()
        print(f"[ok] Device créé : {nom}")
        return r.json()["id"]["id"]

    # 1. Devices machines + attribut partagé "threshold"
    for m in MACHINES:
        dev_id = device(m)
        r = requests.post(f"{TB}/api/plugins/telemetry/DEVICE/{dev_id}/attributes/SHARED_SCOPE",
                          json={"threshold": 0.7}, headers=h, timeout=10)
        r.raise_for_status()
    print("[ok] Attribut partagé threshold = 0.7 sur", ", ".join(MACHINES))

    # 2. Device passerelle utilisé par Node-RED
    device(GATEWAY_NAME, gateway=True, token=GATEWAY_TOKEN)

    # 3. Rule chain : import puis définition comme racine
    export = json.loads((ROOT / "configs" / "tb_rule_chain.json").read_text(encoding="utf-8"))
    nom = export["ruleChain"]["name"]
    existantes = requests.get(f"{TB}/api/ruleChains", params={"pageSize": 100, "page": 0,
                              "textSearch": nom}, headers=h, timeout=10).json()["data"]
    if existantes:
        rc_id = existantes[0]["id"]["id"]
    else:
        rc = requests.post(f"{TB}/api/ruleChain", json=export["ruleChain"], headers=h, timeout=10)
        rc.raise_for_status()
        rc_id = rc.json()["id"]["id"]
    # (ré)écrit toujours les nœuds : relancer le script applique la dernière version du JSON
    meta = dict(export["metadata"], ruleChainId={"entityType": "RULE_CHAIN", "id": rc_id})
    r = requests.post(f"{TB}/api/ruleChain/metadata", json=meta, headers=h, timeout=10)
    r.raise_for_status()
    print(f"[ok] Rule chain importée : {nom}")
    requests.post(f"{TB}/api/ruleChain/{rc_id}/root", headers=h, timeout=10).raise_for_status()
    print("[ok] Rule chain définie comme racine (root)")


if __name__ == "__main__":
    attendre(f"{NODERED}/", "Node-RED")
    setup_nodered()
    attendre(f"{TB}/login", "ThingsBoard (peut prendre ~2 min au 1er démarrage)", essais=120)
    setup_thingsboard()
    print("\nTerminé. Lancer maintenant : python src/simulator.py --demo")
