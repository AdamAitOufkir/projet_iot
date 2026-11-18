# 05 · Déroulement de la démo

## Avant la soutenance (10 min)
```bash
cd ~/Desktop/projet_iot && source .venv/bin/activate
docker compose up -d                       # attendre ~2 min pour ThingsBoard
uvicorn src.api:app --host 0.0.0.0 --port 8000      # terminal 2
python scripts/setup_plateformes.py        # idempotent : peut être relancé sans risque
```
Ouvrir les onglets : http://localhost:8000 (live), http://localhost:3000 (Grafana),
http://localhost:8080 (ThingsBoard → Alarmes), http://localhost:1880 (Node-RED).

## Pendant la démo (~1 min)
1. Terminal 3 : `python src/simulator.py --demo --interval 0.5`
   → les messages défilent (`M1 rpm=… → ok / PANNE`).
2. **Page live** : les jauges bougent en direct (WebSocket).
3. **Grafana** : courbes et jauges, la ligne rouge du seuil, le tableau des alertes.
4. **ThingsBoard → Alarmes** : alarmes CRITICAL « Panne probable ».
5. **Seuil dynamique** : ThingsBoard → Entités → Devices → M1 → Attributs → *Attributs partagés* →
   `threshold` : passer de 0.7 à 0.95 → les alarmes de M1 deviennent rares, sans rien redéployer.
6. (Si on vous le demande) `python src/benchmark.py` → tableau des 3 protocoles en ~2 s.

## Configuration manuelle (si on demande « comment l'avez-vous configuré ? »)
Le script `setup_plateformes.py` automatise exactement ces étapes :

**Node-RED** : Menu ☰ → Importer → coller `configs/nodered_flow.json` → Déployer.
Le token ThingsBoard est dans le nœud de config « ThingsBoard (passerelle) » (champ *Username*).

**ThingsBoard** (tenant@thingsboard.org / tenant) :
1. Entités → Devices → **+** : créer `M1`, `M2`, `M3`.
2. Sur chaque device : Attributs → *Attributs partagés* → **+** `threshold` = `0.7` (double).
3. Créer le device `Node-RED Gateway` en cochant **« Is gateway »**, puis Gérer les identifiants →
   Access token = `NODERED_GATEWAY_TOKEN`.
4. Chaînes de règles → **+** → Importer → `configs/tb_rule_chain.json` → enregistrer →
   « Définir comme chaîne racine ».

**Grafana** : rien à faire (provisionné). Pour importer à la main : Dashboards → New → Import →
`configs/grafana_dashboard.json`.

## Captures (dossier `docs/img/`)
| Fichier | Contenu |
|---|---|
| `grafana_dashboard.png` | dashboard Grafana pendant un rejeu |
| `live_websocket.png` | page live alimentée en WebSocket |
| `nodered_flux.png` | flux principal Node-RED |
| `nodered_sousflux.png` | sous-flux `Prétraitement_Machine` |
| `tb_rule_chain.png` | rule chain ThingsBoard |
| `tb_alarmes.png` | alarme CRITICAL dans ThingsBoard |

## En cas de problème
| Symptôme | Cause probable / solution |
|---|---|
| Node-RED : « API ML indisponible » | `uvicorn` n'est pas lancé, ou lancé sans `--host 0.0.0.0` |
| ThingsBoard ne répond pas | il démarre encore (`docker logs -f p11-thingsboard`) |
| Pas de données dans Grafana | vérifier la période (en haut à droite) et que le simulateur tourne |
| Nœud « ThingsBoard (passerelle) » déconnecté | le device passerelle n'existe pas : relancer `setup_plateformes.py` |
| Aucune alarme | lancer le simulateur avec `--demo` ; vérifier que la rule chain est bien « racine » |
