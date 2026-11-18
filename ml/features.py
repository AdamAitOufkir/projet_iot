"""Transformation des features partagée entre l'entraînement (train.py) et l'inférence (api.py).

Avoir UNE seule fonction garantit que le modèle reçoit en production
exactement les mêmes colonnes, dans le même ordre, qu'à l'entraînement.
"""
from __future__ import annotations

import pandas as pd

# Noms des colonnes du CSV AI4I 2020 -> noms courts utilisés dans les messages JSON
RENAME = {
    "Type": "type",
    "Air temperature [K]": "air_temp_k",
    "Process temperature [K]": "process_temp_k",
    "Rotational speed [rpm]": "rpm",
    "Torque [Nm]": "torque_nm",
    "Tool wear [min]": "tool_wear_min",
    "Machine failure": "panne_reelle",
}

# Type de produit : L = Low, M = Medium, H = High quality (ordre naturel -> encodage ordinal)
TYPE_CODE = {"L": 0, "M": 1, "H": 2}

# Les 6 entrées du modèle (ordre fixe)
FEATURES = ["type_code", "air_temp_k", "process_temp_k", "rpm", "torque_nm", "tool_wear_min"]


def to_features(df: pd.DataFrame) -> pd.DataFrame:
    """Prend un DataFrame avec les noms courts et renvoie la matrice X du modèle."""
    x = df.copy()
    x["type_code"] = x["type"].map(TYPE_CODE).fillna(TYPE_CODE["M"]).astype(int)
    return x[FEATURES].astype(float)
