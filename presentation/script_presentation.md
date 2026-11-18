# Script de présentation : Maintenance prédictive (Projet 11)

> Durée visée : **5 minutes** pour 13 slides, donc environ **20 à 25 secondes par slide**.
> Les durées sont indicatives. Les mots en *italique* sont des mots techniques anglais : on peut les dire tels quels.

---

## Slide 1 : Titre (~15 s)

Bonjour à tous.
Je m'appelle **[Prénom NOM]**, je suis en Master Data & IA à l'INPT.
Aujourd'hui, je vous présente mon projet : **la maintenance prédictive d'équipements industriels**.
L'idée, c'est de construire une chaîne complète : des capteurs simulés jusqu'à une alarme, avec un modèle d'IA au milieu.
En bas, vous voyez les technologies que j'ai utilisées. On va les voir une par une pendant la présentation.

---

## Slide 2 : Contexte (~25 s)

D'abord, c'est quoi la maintenance prédictive ?
Il y a trois façons de faire la maintenance.
- La **corrective** : on attend la panne, puis on répare. Donc la machine s'arrête sans prévenir.
- La **préventive** : on change les pièces à date fixe, même si elles sont encore bonnes.
- La **prédictive** : on regarde les mesures de la machine, et on intervient **seulement quand une panne arrive**.

C'est l'objectif de ce projet. Les avantages : moins d'arrêts imprévus, des interventions planifiées, et moins de coûts.

---

## Slide 3 : Le dataset (~25 s)

Pour les données, j'utilise un dataset public : **AI4I 2020**.
Ce sont des relevés d'une machine-outil : **10 000 lignes** et **14 colonnes**.

Le modèle utilise six colonnes : le type de produit, la température de l'air, la température du procédé, la vitesse de rotation, le couple et l'usure de l'outil.
La cible, c'est la colonne *Machine failure* : 0 si la machine marche bien, 1 si elle est en panne.

Point important : il y a seulement **339 pannes, donc 3,4 %**. Les pannes sont rares, et ça rend le problème plus difficile.

---

## Slide 4 : Le modèle (~25 s)

Sur ces données, j'ai entraîné un modèle de *machine learning*.
Les étapes sont simples :
1. Je garde les six variables.
2. Je sépare les données : **80 % pour l'entraînement, 20 % pour le test**. Le *split* est stratifié, donc on garde 3,4 % de pannes des deux côtés.
3. Je normalise avec un *StandardScaler*.
4. J'entraîne un **RandomForest** avec 200 arbres.

Comme les pannes sont rares, j'utilise *class_weight = balanced* : le modèle fait plus attention aux pannes.
Les 20 % de test ne sont pas perdus : c'est eux que le simulateur va envoyer. On va voir ça juste après.

---

## Slide 5 : Architecture (~25 s)

Voici l'architecture globale, en trois couches : **capteur, réseau, cloud**.
La couleur des flèches indique le protocole : vert pour MQTT, bleu pour HTTP, violet pour WebSocket.

En résumé : un script Python simule les capteurs et envoie les mesures en MQTT au *broker* Mosquitto.
Node-RED reçoit les messages, demande une prédiction au modèle, puis envoie le résultat à InfluxDB, Grafana et ThingsBoard.
Si la probabilité de panne est trop haute, ThingsBoard lève une **alarme**.

On va détailler chaque couche dans les slides suivantes.

---

## Slide 6 : Couche capteur (~20 s)

Commençons par la couche capteur.
Je n'ai pas de vrai capteur. Le script `simulator.py` lit les **2 000 lignes de test**, que le modèle n'a jamais vues.
Il envoie une ligne par seconde, et il les répartit à tour de rôle entre trois machines : M1, M2 et M3.

Chaque mesure devient un message **JSON**, comme celui-ci, avec un horodatage.
Il est publié en **MQTT avec QoS 1** : le *broker* répond avec un accusé, le PUBACK. Donc on ne perd aucune mesure.

---

## Slide 7 : Couche réseau, les protocoles (~25 s)

Dans la couche réseau, j'utilise trois protocoles, et chacun a un rôle précis.
- **MQTT** pour le flux continu de mesures. C'est léger, et le capteur ne sait pas qui écoute.
- **REST** pour les questions ponctuelles : demander une prédiction, écrire dans la base, récupérer l'historique.
- **WebSocket** pour envoyer les prédictions en temps réel au navigateur, sans que la page demande à chaque fois.

On va comparer ces trois protocoles avec des chiffres dans la partie résultats.

---

## Slide 8 : Couche réseau, l'infrastructure (~20 s)

Concrètement, tout tourne **sur une seule machine**.
Cinq services sont dans des conteneurs **Docker** : Mosquitto, Node-RED, InfluxDB, Grafana et ThingsBoard.
Ils communiquent entre eux par leur nom, dans le même réseau Docker.
L'API du modèle et le simulateur tournent directement sur la machine hôte.
Il n'y a pas de Wi-Fi ou de LoRaWAN ici : c'est un prototype local.

---

## Slide 9 : Couche cloud, le traitement (~25 s)

Maintenant, la couche cloud. D'abord le traitement, avec **Node-RED**.
Node-RED reçoit tous les messages MQTT. Ensuite, un **sous-flux** fait quatre étapes :
1. Il garde seulement les messages de **sa** machine.
2. Il vérifie et nettoie les données.
3. Il appelle le modèle avec un `POST /predict`.
4. Il ajoute la probabilité de panne au message.

L'API, faite avec **FastAPI**, répond en environ **11 millisecondes**.
Et le sous-flux est réutilisable : pour ajouter une quatrième machine, il suffit d'ajouter une instance.

---

## Slide 10 : Couche cloud, stocker, alerter, afficher (~25 s)

Après la prédiction, il y a trois rôles.
- **Stocker** : les données vont dans **InfluxDB**, une base pour les séries temporelles, et **Grafana** les affiche.
- **Alerter** : **ThingsBoard** lit un seuil, appelé *threshold*. Si la probabilité de panne dépasse ce seuil, il crée une **alarme critique**. Sinon, il l'efface.
  Le seuil se change **à chaud**, sans redéployer.
- **Afficher** : l'utilisateur peut regarder Grafana, la page live, ou ThingsBoard.

---

## Slide 11 : Résultats, benchmark (~25 s)

Passons aux résultats. D'abord le réseau.
J'ai envoyé **100 messages** avec chaque protocole, avec le même JSON.
Les latences sont très faibles, autour d'une milliseconde, parce que tout est en local.
La vraie différence, c'est la taille : HTTP ajoute **317 octets** par message, contre **26 pour MQTT** et **21 pour WebSocket**.
Donc HTTP est environ **12 fois plus lourd** que MQTT. C'est pour ça que j'utilise MQTT pour le flux continu, et REST seulement pour les appels ponctuels.

---

## Slide 12 : Résultats, modèle (~25 s)

Ensuite, le modèle, testé sur 2 000 lignes avec 68 pannes.
- Le **ROC-AUC est de 0,97** : le modèle sépare très bien les pannes et les cas normaux.
- Au seuil 0,5, il détecte **79 % des pannes**.
- Au seuil 0,7, **83 % des alertes sont de vraies pannes**.

Le seuil, c'est un compromis : plus il est haut, moins on a de fausses alertes, mais plus on rate de pannes.
C'est pour ça qu'il est réglable. J'ai testé : avec un seuil de 0,3, une prédiction de 0,39 déclenche bien l'alarme.

---

## Slide 13 : Démonstration (~15 s, puis démo)

Maintenant, je vais vous montrer le système en direct.
1. Je lance le simulateur.
2. Sur la page live, les jauges bougent en temps réel.
3. Dans Grafana, on voit les courbes et le seuil.
4. Dans ThingsBoard, les alarmes critiques apparaissent.
5. Et enfin, je change le seuil de M1 de 0,7 à 0,95, et les alarmes deviennent rares, sans rien redéployer.

*(Après la démo)* Merci pour votre attention. Je suis prêt pour vos questions.

---

## Phrases utiles si on vous pose une question

| Situation | Phrase |
|---|---|
| Vous ne savez pas tout de suite | « Bonne question. Je pense que… » |
| Le sujet est sur une autre slide | « On l'a vu sur la slide des protocoles : … » |
| La démo ne marche pas | « Je vous montre les captures, elles viennent du même système. » |
| Pourquoi pas un LSTM ? | « Les données AI4I n'ont pas de séquence dans le temps, donc un RandomForest est plus adapté. » |
| Pourquoi pas de Wi-Fi / LoRaWAN ? | « C'est un prototype local. En production, on ajouterait TLS et l'authentification. » |
