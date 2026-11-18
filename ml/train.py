"""Entraînement du modèle de maintenance prédictive (AI4I 2020 + RandomForest).

Usage (depuis la racine du projet) :
    python -m ml.train               # télécharge AI4I 2020 (UCI), sinon données synthétiques
    python -m ml.train --synthetic   # force le générateur synthétique

Sorties (dossier ml/artifacts/) :
    model.joblib, scaler.joblib, metrics.json, confusion_matrix.png
    + data/test.csv : les 20 % de test, rejoués ensuite par le simulateur MQTT
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import zipfile
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import requests
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from ml.features import FEATURES, RENAME, to_features

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ARTIFACTS = ROOT / "ml" / "artifacts"
CSV_PATH = DATA_DIR / "ai4i2020.csv"
UCI_URL = (
    "https://archive.ics.uci.edu/static/public/601/"
    "ai4i+2020+predictive+maintenance+dataset.zip"
)

log = logging.getLogger("train")


# ---------------------------------------------------------------- 1. Données
def download_ai4i() -> pd.DataFrame:
    """Télécharge le CSV officiel AI4I 2020 depuis l'UCI (une seule fois, puis cache local)."""
    if not CSV_PATH.exists():
        log.info("Téléchargement AI4I 2020 depuis l'UCI…")
        resp = requests.get(UCI_URL, timeout=60)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            CSV_PATH.write_bytes(z.read("ai4i2020.csv"))
    return pd.read_csv(CSV_PATH)


def synthetic_ai4i(n: int = 10_000, seed: int = 42) -> pd.DataFrame:
    """Générateur de secours qui reproduit le schéma ET les règles de panne d'AI4I 2020."""
    rng = np.random.default_rng(seed)
    types = rng.choice(["L", "M", "H"], size=n, p=[0.5, 0.3, 0.2])
    air = 300 + np.cumsum(rng.normal(0, 0.05, n)) + rng.normal(0, 2, n) * 0.3
    process = air + 10 + rng.normal(0, 1, n)
    rpm = np.clip(rng.normal(1540, 150, n), 1160, 2890)
    torque = np.clip(rng.normal(40, 7, n), 3, 77)
    wear_add = np.select([types == "L", types == "M"], [2, 3], 5)
    wear = (np.arange(n) * 7 % 240 + wear_add).astype(int)

    power = torque * rpm * 2 * np.pi / 60                      # puissance en W
    strain_limit = np.select([types == "L", types == "M"], [11_000, 12_000], 13_000)
    twf = (wear >= 200) & (wear <= 240) & (rng.random(n) < 0.05)   # usure outil
    hdf = ((process - air) < 8.6) & (rpm < 1380)                    # dissipation thermique
    pwf = (power < 3500) | (power > 9000)                           # puissance
    osf = (wear * torque) > strain_limit                            # surcharge
    rnf = rng.random(n) < 0.001                                     # aléatoire
    failure = twf | hdf | pwf | osf | rnf

    return pd.DataFrame({
        "UDI": np.arange(1, n + 1),
        "Product ID": [f"{t}{50000 + i}" for i, t in enumerate(types)],
        "Type": types,
        "Air temperature [K]": air.round(1),
        "Process temperature [K]": process.round(1),
        "Rotational speed [rpm]": rpm.round().astype(int),
        "Torque [Nm]": torque.round(1),
        "Tool wear [min]": wear,
        "Machine failure": failure.astype(int),
        "TWF": twf.astype(int), "HDF": hdf.astype(int), "PWF": pwf.astype(int),
        "OSF": osf.astype(int), "RNF": rnf.astype(int),
    })


def load_data(force_synthetic: bool = False) -> tuple[pd.DataFrame, str]:
    if not force_synthetic:
        try:
            return download_ai4i(), "AI4I 2020 (UCI)"
        except Exception as exc:  # pas d'Internet, URL morte…
            log.warning("Téléchargement impossible (%s) -> données synthétiques", exc)
    return synthetic_ai4i(), "synthétique (schéma AI4I)"


# ---------------------------------------------------------------- 2. Prétraitement
def preprocess(raw: pd.DataFrame) -> pd.DataFrame:
    """Nettoyage : renommage, suppression des colonnes inutiles ou qui 'trichent'."""
    df = raw.rename(columns=RENAME)
    # UDI / Product ID = identifiants (aucune information physique).
    # TWF, HDF, PWF, OSF, RNF = TYPE de panne -> connus seulement APRÈS la panne :
    # les garder serait une fuite de données (le modèle lirait la réponse).
    df = df.drop(columns=["UDI", "Product ID", "TWF", "HDF", "PWF", "OSF", "RNF"])
    df = df.dropna().drop_duplicates()
    return df


# ---------------------------------------------------------------- 3. Entraînement
def train(df: pd.DataFrame, seed: int = 42):
    x = to_features(df)
    y = df["panne_reelle"].astype(int)

    # Split stratifié : on garde ~3,4 % de pannes dans train ET dans test
    x_train, x_test, y_train, y_test, df_train, df_test = train_test_split(
        x, y, df, test_size=0.2, stratify=y, random_state=seed
    )

    scaler = StandardScaler().fit(x_train)          # appris sur le train uniquement
    model = RandomForestClassifier(
        n_estimators=200,
        min_samples_leaf=2,
        class_weight="balanced",                     # compense le déséquilibre des classes
        n_jobs=-1,
        random_state=seed,
    )
    model.fit(scaler.transform(x_train), y_train)
    return model, scaler, x_test, y_test, df_test


# ---------------------------------------------------------------- 4. Évaluation
def evaluate(model, scaler, x_test, y_test, source: str, threshold: float = 0.5) -> dict:
    proba = model.predict_proba(scaler.transform(x_test))[:, 1]   # = panne_probable
    y_pred = (proba >= threshold).astype(int)
    cm = confusion_matrix(y_test, y_pred)
    metrics = {
        "source_donnees": source,
        "n_test": int(len(y_test)),
        "taux_panne_test": round(float(y_test.mean()), 4),
        "seuil_decision": threshold,
        "f1": round(f1_score(y_test, y_pred), 4),
        "precision": round(precision_score(y_test, y_pred), 4),
        "recall": round(recall_score(y_test, y_pred), 4),
        "roc_auc": round(roc_auc_score(y_test, proba), 4),
        "confusion_matrix": {
            "vrais_negatifs": int(cm[0, 0]), "faux_positifs": int(cm[0, 1]),
            "faux_negatifs": int(cm[1, 0]), "vrais_positifs": int(cm[1, 1]),
        },
        "importance_features": {
            f: round(float(v), 4) for f, v in zip(FEATURES, model.feature_importances_)
        },
    }
    # Même métriques avec le seuil d'alarme ThingsBoard (0.7) pour comparaison
    y_07 = (proba >= 0.7).astype(int)
    metrics["au_seuil_alarme_0.7"] = {
        "precision": round(precision_score(y_test, y_07, zero_division=0), 4),
        "recall": round(recall_score(y_test, y_07), 4),
        "f1": round(f1_score(y_test, y_07), 4),
    }
    return metrics


def save_confusion_png(metrics: dict, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    c = metrics["confusion_matrix"]
    cm = np.array([[c["vrais_negatifs"], c["faux_positifs"]],
                   [c["faux_negatifs"], c["vrais_positifs"]]])
    fig, ax = plt.subplots(figsize=(4.2, 3.8), dpi=150)
    ax.imshow(cm, cmap="Blues")
    for (i, j), v in np.ndenumerate(cm):
        ax.text(j, i, str(v), ha="center", va="center", fontsize=16,
                color="white" if v > cm.max() / 2 else "black")
    ax.set_xticks([0, 1], ["Normal", "Panne"])
    ax.set_yticks([0, 1], ["Normal", "Panne"])
    ax.set_xlabel("Prédit")
    ax.set_ylabel("Réel")
    ax.set_title("Matrice de confusion (seuil 0.5)")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="store_true", help="forcer les données synthétiques")
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    raw, source = load_data(args.synthetic)
    df = preprocess(raw)
    log.info("Données : %s | %d lignes | %.2f %% de pannes",
             source, len(df), 100 * df["panne_reelle"].mean())

    model, scaler, x_test, y_test, df_test = train(df)
    metrics = evaluate(model, scaler, x_test, y_test, source)

    joblib.dump(model, ARTIFACTS / "model.joblib")
    joblib.dump(scaler, ARTIFACTS / "scaler.joblib")
    (ARTIFACTS / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    save_confusion_png(metrics, ARTIFACTS / "confusion_matrix.png")
    df_test.to_csv(DATA_DIR / "test.csv", index=False)   # rejoué par le simulateur

    log.info("F1=%.3f  Precision=%.3f  Recall=%.3f  ROC-AUC=%.3f",
             metrics["f1"], metrics["precision"], metrics["recall"], metrics["roc_auc"])
    log.info("Artefacts écrits dans %s", ARTIFACTS)


if __name__ == "__main__":
    main()
