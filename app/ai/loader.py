# 모델 로드 #
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib

AI_DIR = Path(__file__).resolve().parent

WEIGHTS_PATH = AI_DIR / "weights"
MODEL_PATH = WEIGHTS_PATH / "gam_model.pkl"

@lru_cache(maxsize=1)
def load_gam_package() -> dict[str, Any]:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"GAM 모델 파일을 찾을 수 없습니다: {MODEL_PATH}"
        )
    
    package = joblib.load(MODEL_PATH)

    if not isinstance(package, dict):
        raise TypeError(
            f"모델 파일 형식이 올바르지 않습니다. dict 형태여야 합니다: {MODEL_PATH}"
        )

    required_keys = ("model", "columns", "goodid_encoder")
    missing_keys = [key for key in required_keys if key not in package]

    if missing_keys:
        raise KeyError(
            f"모델 파일에 필요한 키가 없습니다: {missing_keys}\n"
            f"필수 키: {required_keys}"
        )

    return package


def get_gam_model():
    return load_gam_package()["model"]


def get_x_columns() -> list[str]:
    columns = load_gam_package()["columns"]
    return list(columns)


def get_goodid_encoder():
    return load_gam_package()["goodid_encoder"]


def get_model_path() -> Path:
    return MODEL_PATH


def reload_gam_package() -> dict[str, Any]:
    load_gam_package.cache_clear()
    return load_gam_package()