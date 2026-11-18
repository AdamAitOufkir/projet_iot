# 06 · Antisèche : questions probables du jury

## Architecture
**Q : Décrivez votre architecture.**
Trois couches. Capteur : un script Python rejoue le dataset AI4I comme 3 machines. Réseau : MQTT pour
le flux, REST pour l'historique et l'appel du modèle, WebSocket pour le direct. Cloud : Node-RED
orchestre, une API FastAPI sert le RandomForest, InfluxDB stocke, Grafana affiche, ThingsBoard gère
l'alarme.

**Q : Pourquoi autant d'outils ?** Chacun fait une chose bien et c'est ce que demande le sujet :
Mosquitto transporte, Node-RED route, InfluxDB stocke des séries temporelles, Grafana visualise,
ThingsBoard gère devices, attributs et alarmes.

**Q : Pourquoi ThingsBoard est sur le port 1884 ?** ThingsBoard a son propre broker MQTT sur 1883
dans son conteneur ; Mosquitto utilise déjà 1883 sur la machine hôte. On mappe donc 1884 → 1883.
Entre conteneurs (Node-RED → ThingsBoard), on utilise directement `thingsboard:1883`.

## Protocoles
**Q : Pourquoi MQTT pour les capteurs et pas HTTP ?** Overhead mesuré : 26 octets par message contre
317 pour HTTP (12× moins). La connexion reste ouverte, c'est du publish/subscribe (le capteur ne connaît
pas les consommateurs), et le QoS garantit la livraison. HTTP impose une requête/réponse et des
en-têtes texte à chaque envoi.

**Q : Différence entre QoS 0, 1 et 2 ?** 0 : au plus une fois, sans accusé. 1 : au moins une fois,
accusé PUBACK et renvoi si absent (doublons possibles). 2 : exactement une fois, 4 échanges. On a pris
QoS 1 : aucune perte, et un doublon horodaté est sans conséquence.

**Q : Pourquoi REST pour l'historique ?** C'est une question ponctuelle (« donne-moi les 24 dernières
heures ») qui attend une réponse : le modèle requête/réponse convient. C'est aussi l'API native de
ThingsBoard (`/api/plugins/telemetry/...`), avec authentification JWT.

**Q : Pourquoi WebSocket et pas du polling REST ?** Avec WebSocket, le serveur pousse dès qu'une
prédiction existe : pas de requêtes inutiles et une latence minimale. En polling, on paierait ~500
octets d'en-têtes à chaque requête même sans nouveauté, avec en plus un délai d'au plus une période.

**Q : WebSocket a un overhead plus faible que MQTT dans votre benchmark : pourquoi ne pas l'utiliser
partout ?** WebSocket n'est qu'un tuyau bidirectionnel : pas de broker, pas de topics, pas de QoS,
pas de persistance des messages. MQTT apporte tout ça, et c'est le standard IoT (capteurs, passerelles,
ThingsBoard le supportent nativement).

**Q : Comment avez-vous mesuré la latence ?** `time.perf_counter()` entre l'envoi et l'accusé :
PUBACK pour MQTT, réponse 200 pour REST, trame de réponse pour WebSocket. 100 messages par protocole,
le même payload, un message d'échauffement exclu, et les endpoints de benchmark ne lancent pas le modèle
pour ne mesurer que le transport.

**Q : Vos latences sont sub-milliseconde, est-ce réaliste ?** C'est du local (même machine). Sur un
vrai réseau, on ajoute le délai de propagation. Les **écarts relatifs** et surtout les **octets**
restent valables.

## Plateformes
**Q : À quoi sert le sous-flux Node-RED ?** C'est un composant réutilisable paramétré par `machine_id` :
filtre de la machine, nettoyage/validation des champs, appel du modèle, ajout de la prédiction. Il est
instancié 3 fois ; pour une nouvelle machine on ajoute une instance, et une correction profite à toutes.

**Q : Comment fonctionne l'alarme ?** La rule chain enregistre la télémétrie, lit l'attribut partagé
`threshold` du device (placé dans les métadonnées), puis un script TBEL compare
`panne_probable > threshold`. Si vrai : alarme CRITICAL (créée ou mise à jour) ; si faux : alarme effacée.

**Q : Qu'est-ce qu'un attribut partagé ?** Un paramètre stocké côté serveur sur un device, visible
par le device et modifiable depuis l'UI/API. Il permet de changer le seuil **sans redéploiement** :
la rule chain le relit à chaque message. Testé : seuil 0,3 sur M2, une prédiction de 0,39 lève une alarme.

**Q : Différence attribut client / serveur / partagé ?** Client : envoyé par le device (ex. version
firmware). Serveur : connu du serveur seulement. Partagé : défini côté serveur et poussé vers le device
(configuration).

**Q : Pourquoi InfluxDB et pas une base SQL ?** Base de séries temporelles : écriture rapide de
points horodatés, compression, fonctions temporelles natives (fenêtres, dernière valeur, rétention).

**Q : Qu'est-ce que le line protocol ?** Le format texte d'écriture d'InfluxDB :
`mesure,tags champs horodatage`. Les tags sont indexés (on filtre dessus : `machine_id`), les champs
sont les valeurs.

**Q : Pourquoi Node-RED est une « passerelle » ThingsBoard ?** Avec l'API gateway
(`v1/gateway/telemetry`), une seule connexion MQTT transporte les données de toutes les machines ;
ThingsBoard les rattache au bon device grâce au nom (`M1`, `M2`, `M3`).

## Machine Learning
**Q : Pourquoi retirer TWF, HDF, PWF, OSF, RNF ?** Ce sont les **modes** de panne, connus seulement
après la panne. Les garder = fuite de données : score parfait en test, inutilisable en production.

**Q : Comment gérez-vous le déséquilibre (3,4 % de pannes) ?** Split stratifié, `class_weight="balanced"`,
et des métriques adaptées (rappel, F1, ROC-AUC) au lieu de l'accuracy.

**Q : Pourquoi le rappel plutôt que la précision ?** Rater une panne coûte un arrêt de production ;
une fausse alerte coûte une inspection. On préfère quelques fausses alertes à des pannes ratées.

**Q : Que vaut votre modèle ?** ROC-AUC 0,97. Au seuil 0,5 : rappel 0,79, précision 0,59. Au seuil 0,7 :
précision 0,83, rappel 0,66. Le seuil est un compromis réglable.

**Q : Pourquoi pas un LSTM ?** AI4I n'a pas de séquences temporelles par machine (chaque ligne est un
état indépendant). Le RandomForest est le bon outil pour du tabulaire : rapide, robuste, explicable.

**Q : Pourquoi un StandardScaler avec une forêt ?** Inutile pour les arbres, mais demandé et sans
effet négatif. Il rendrait le pipeline compatible avec un modèle sensible à l'échelle.

**Q : Comment évitez-vous que le simulateur rejoue des données d'entraînement ?** Le simulateur ne
rejoue que `data/test.csv`, les 20 % mis de côté, jamais vus par le modèle.

**Q : Comment ré-entraîneriez-vous ?** `rest_history.py` récupère l'historique ThingsBoard en REST,
on l'ajoute aux données et on relance `python -m ml.train` (par ex. chaque semaine).

## Limites et améliorations
- Sécurité : Mosquitto anonyme, tokens en clair. En production : TLS (8883 / HTTPS), mots de passe, secrets.
- L'API tourne hors Docker (plus simple à montrer) ; on pourrait la conteneuriser.
- Le ré-entraînement est manuel ; on pourrait l'automatiser et versionner les modèles (MLflow).
- Benchmark en local ; à refaire sur un réseau réel (Wi-Fi, 4G) et avec plus de messages.
