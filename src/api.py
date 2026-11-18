"""API d'inférence (FastAPI) : REST pour prédire, WebSocket pour pousser le résultat en direct.

Lancement (depuis la racine du projet) :
    uvicorn src.api:app --host 0.0.0.0 --port 8000

Endpoints :
    POST /predict      -> appelé par Node-RED : renvoie panne_probable et la diffuse en WebSocket
    WS   /ws           -> la page live.html s'y abonne pour recevoir chaque prédiction en direct
    GET  /             -> page live.html
    POST /bench, WS /ws/bench -> endpoints d'écho utilisés uniquement par benchmark.py
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ml.features import to_features

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "ml" / "artifacts"
ALERT_THRESHOLD = 0.7  # seuil d'affichage local (le seuil "officiel" est l'attribut ThingsBoard)

log = logging.getLogger("uvicorn.error")
app = FastAPI(title="Projet 11 - Inférence maintenance prédictive")

# Chargement du modèle UNE fois au démarrage (pas à chaque requête)
model = joblib.load(ARTIFACTS / "model.joblib")
model.n_jobs = 1   # 1 seule ligne à prédire : paralléliser sur tous les cœurs coûte ~70 ms au lieu de ~10 ms
scaler = joblib.load(ARTIFACTS / "scaler.joblib")


class Mesure(BaseModel):
    """Une mesure capteur (même format que le message MQTT du simulateur)."""
    machine_id: str = "M1"
    type: Literal["L", "M", "H"] = "M"
    air_temp_k: float = Field(gt=250, lt=350)
    process_temp_k: float = Field(gt=250, lt=350)
    rpm: float = Field(gt=0, lt=5000)
    torque_nm: float = Field(ge=0, lt=200)
    tool_wear_min: float = Field(ge=0, lt=500)
    ts: int | None = None
    panne_reelle: int | None = None   # vérité terrain (rejeu du dataset), non utilisée par le modèle


def predire(m: Mesure) -> float:
    x = to_features(pd.DataFrame([m.model_dump()]))
    return float(model.predict_proba(scaler.transform(x))[0, 1])


# ------------------------------------------------------------ WebSocket : diffusion
clients: set[WebSocket] = set()


async def diffuser(message: dict) -> None:
    """Envoie le message à toutes les pages live.html connectées."""
    texte = json.dumps(message)
    for ws in list(clients):
        try:
            await ws.send_text(texte)
        except Exception:
            clients.discard(ws)   # client parti : on le retire


@app.websocket("/ws")
async def ws_live(ws: WebSocket) -> None:
    await ws.accept()
    clients.add(ws)
    try:
        while True:              # on garde la connexion ouverte (le serveur pousse, le client écoute)
            await ws.receive_text()
    except WebSocketDisconnect:
        clients.discard(ws)


# ------------------------------------------------------------ REST : prédiction
@app.post("/predict")
async def predict(m: Mesure) -> dict:
    try:
        p = predire(m)
    except Exception as exc:
        log.exception("Erreur d'inférence")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    resultat = {
        "machine_id": m.machine_id,
        "ts": m.ts,
        "panne_probable": round(p, 4),
        "alerte": p > ALERT_THRESHOLD,
        "panne_reelle": m.panne_reelle,
    }
    await diffuser(resultat)     # push temps réel vers le navigateur
    return resultat


@app.get("/")
async def page_live() -> FileResponse:
    return FileResponse(Path(__file__).parent / "live.html")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "clients_ws": len(clients)}


# ------------------------------------------------------------ Benchmark (écho, sans modèle)
@app.post("/bench")
async def bench_rest(payload: dict) -> dict:
    return {"ack": payload.get("seq")}


@app.websocket("/ws/bench")
async def bench_ws(ws: WebSocket) -> None:
    await ws.accept()
    try:
        while True:
            data = json.loads(await ws.receive_text())
            await ws.send_text(json.dumps({"ack": data.get("seq")}))
    except WebSocketDisconnect:
        pass
