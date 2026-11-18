# Projet 11 : Maintenance prédictive d'équipements industriels (IoT + IA)

Simuler les capteurs de 3 machines industrielles (dataset **AI4I 2020**), transporter les mesures
en **MQTT**, prédire une panne avec un **RandomForest**, stocker dans **InfluxDB**, visualiser dans
**Grafana**, pousser la prédiction en direct par **WebSocket**, et déclencher une **alarme CRITICAL
dans ThingsBoard** dont le seuil est un **attribut partagé** modifiable sans redéploiement.

> Documentation détaillée, couche par couche : dossier [docs/](docs/)
> Présentation (5 min) : [presentation/soutenance_projet11.pptx](presentation/soutenance_projet11.pptx)

---

## 1. Architecture en 3 niveaux

```
 ┌─────── CAPTEUR ───────┐   ┌──── RÉSEAU ────┐   ┌──────────────── CLOUD / APPLICATION ────────────────┐

  ai4i2020.csv (test)            Mosquitto              Node-RED  (sous-flux Prétraitement_Machine × 3)
        │                        :1883                     │            │                 │
        ▼        MQTT QoS 1        │       MQTT             │ HTTP POST  │ HTTP write      │ MQTT (API passerelle)
  simulator.py ─────────────────▶ usine/+/telemetry ──────▶│ /predict   ▼                 ▼
  (machines M1, M2, M3)                                    ▼          InfluxDB ──▶ Grafana  ThingsBoard CE
                                                       api.py          :8086       :3000    :8080 / :1884
                                                   (FastAPI + RF)                           Rule Chain → alarme
                                                     :8000                                  CRITICAL si
                                                       │ WebSocket /ws                      panne_probable > threshold
                                                       ▼                                         ▲
                                                   live.html (jauge en direct)                   │ REST GET /api/plugins/telemetry/…
                                                                                          rest_history.py → data/history.csv
```

**Un rôle par protocole** : MQTT pour le **flux** de mesures, REST pour le **batch** (historique de
ré-entraînement, appel du modèle), WebSocket pour le **push temps réel** vers le navigateur.

## 2. Pourquoi MQTT, REST et WebSocket ?

| | **MQTT** | **REST / HTTP** | **WebSocket** |
|---|---|---|---|
| Modèle | publish / subscribe via un broker | requête / réponse | connexion persistante bidirectionnelle |
| Qui initie ? | le capteur publie, les abonnés reçoivent | toujours le client | les deux (le serveur peut **pousser**) |
| Fiabilité | QoS 0 / **1** / 2 (accusé PUBACK) | code HTTP (200, 4xx, 5xx) | TCP, pas d'accusé applicatif natif |
| Overhead mesuré* | **26 o** / message (12 %) | **317 o** / message (62 %) | **21 o** / message (10 %) |
| Latence moyenne* | 0,60 ms | 1,24 ms | 0,39 ms |
| Usage dans le projet | flux continu capteurs → plateforme | historique ThingsBoard, appel `/predict` | `panne_probable` → page live |

\* `python src/benchmark.py`, 100 messages par protocole, même payload JSON de 191 octets, en local.
Résultats complets : [reports/benchmark.md](reports/benchmark.md).

- **MQTT pour le flux** : en-tête minuscule (2 octets de base), découplage capteur/consommateurs
  (le simulateur ignore qui lit), QoS 1 garantit « au moins une fois » même si le réseau coupe.
- **REST pour le batch** : on a besoin d'une **réponse** à une **question** ponctuelle
  (« donne-moi l'historique des 24 h », « quelle est la probabilité ? »). HTTP est universel, sans état,
  facile à sécuriser et à mettre en cache. Son overhead (en-têtes texte) ne gêne pas pour des appels rares.
- **WebSocket pour l'affichage live** : un navigateur ne parle pas MQTT nativement ; faire du polling REST
  toutes les secondes gaspillerait ~500 o par requête même sans nouveauté. Avec WebSocket, la connexion
  reste ouverte et **le serveur pousse** chaque prédiction dès qu'elle existe.

## 3. Lancer le projet (Ubuntu / WSL)

Prérequis : Docker + Docker Compose, Python 3.11+, ~4 Go de RAM libre (ThingsBoard), ~5 Go de disque.

```bash
# 0. Dépendances Python
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Entraîner le modèle (télécharge AI4I 2020 ; sans Internet -> données synthétiques)
python -m ml.train                      # -> ml/artifacts/ + data/test.csv

# 2. Démarrer les 5 services (ThingsBoard met ~2 min au premier démarrage)
docker compose up -d

# 3. Démarrer l'API d'inférence (REST + WebSocket) dans un 2e terminal
uvicorn src.api:app --host 0.0.0.0 --port 8000

# 4. Configurer Node-RED + ThingsBoard (devices, attribut threshold, rule chain)
python scripts/setup_plateformes.py     # ou à la main : docs/05_deroulement_demo.md

# 5. Lancer les capteurs simulés
python src/simulator.py --demo          # --demo = ~20 % de pannes pour voir des alarmes vite

# 6. Benchmark des 3 protocoles (100 messages chacun)
python src/benchmark.py --n 100         # -> reports/benchmark.md + .csv

# 7. Historique REST pour le ré-entraînement
python src/rest_history.py --hours 1    # -> data/history.csv
```

| Service | URL | Identifiants |
|---|---|---|
| Page live (WebSocket) | http://localhost:8000 | – |
| Grafana | http://localhost:3000 (dashboard « Projet 11 ») | admin / admin |
| ThingsBoard | http://localhost:8080 | tenant@thingsboard.org / tenant |
| Node-RED | http://localhost:1880 | – |
| InfluxDB | http://localhost:8086 | admin / admin12345 (token `projet11-token`) |
| Mosquitto | mqtt://localhost:1883 | anonyme |

Arrêt : `docker compose down` (garde les données) ou `docker compose down -v` (remise à zéro).

## 4. Contenu du dépôt

```
docker-compose.yml          5 services : mosquitto, nodered, thingsboard, influxdb, grafana
mosquitto/mosquitto.conf    broker MQTT
grafana/provisioning/       datasource InfluxDB + chargement automatique du dashboard
configs/
  nodered_flow.json         flux + sous-flux Prétraitement_Machine (paramètre machine_id)
  tb_rule_chain.json        export de la rule chain d'alarme ThingsBoard
  grafana_dashboard.json    dashboard Grafana
ml/
  features.py               transformation commune entraînement / inférence
  train.py                  entraînement + évaluation (script)
  train.ipynb               même chose pas à pas, avec explications (notebook exécuté)
  artifacts/                model.joblib, scaler.joblib, metrics.json, confusion_matrix.png
src/
  simulator.py              CAPTEUR : rejeu du CSV en MQTT QoS 1
  api.py + live.html        modèle ML en REST + push WebSocket + page live
  rest_history.py           REST : historique ThingsBoard pour ré-entraîner
  benchmark.py              comparatif MQTT / REST / WebSocket
scripts/setup_plateformes.py  configuration automatique Node-RED + ThingsBoard
reports/benchmark.md        tableau comparatif des protocoles
docs/                       explications détaillées par couche + antisèche Q&R
```

## 5. Résultats

**Modèle** (jeu de test : 2 000 lignes, 3,4 % de pannes)

| Seuil | Précision | Rappel | F1 | ROC-AUC |
|---|---|---|---|---|
| 0,5 | 0,59 | **0,79** | 0,68 | **0,971** |
| 0,7 (seuil d'alarme) | **0,83** | 0,66 | 0,74 | 0,971 |

Le seuil est un compromis : plus haut, moins de fausses alertes mais plus de pannes ratées.
C'est pourquoi il est stocké dans un **attribut partagé ThingsBoard**, réglable à chaud.
