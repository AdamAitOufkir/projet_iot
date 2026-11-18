# Benchmark protocoles : MQTT vs REST vs WebSocket

Date : 2026-11-15 02:36 · même payload JSON pour les trois · latence = envoi -> accusé de réception

| Protocole | Messages | Latence moy. (ms) | Latence p95 (ms) | Payload (o) | Overhead (o) | Total / msg (o) | Overhead (%) | Fiabilité (%) |
|---|---|---|---|---|---|---|---|---|
| MQTT (QoS 1) | 100 | 0.6 | 0.79 | 191 | 26 | 217 | 12.0 | 100.0 |
| REST / HTTP 1.1 | 100 | 1.24 | 1.77 | 191 | 317 | 508 | 62.4 | 100.0 |
| WebSocket | 100 | 0.39 | 0.69 | 191 | 21 | 212 | 9.9 | 100.0 |
