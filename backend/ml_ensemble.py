import logging
import numpy as np

logger = logging.getLogger(__name__)

from xgboost import XGBClassifier
logger.info("[MLEnsemble] XGBoost será usado.")

class MLEnsemble:
    """
    Wrapper de modelo ML usado no backtester cronológico.

    Parâmetros XGBoost calibrados para dados de apostas esportivas:
    - n_estimators=300: suficiente para capturar padrões sem overfitting.
    - max_depth=4: captura interações de 2ª/3ª ordem sem memorizar ruído.
    - learning_rate=0.05: shrinkage agressivo, complementa os 300 estimadores.
    - subsample=0.8 / colsample_bytree=0.8: regularização estocástica.
    - min_child_weight=15: exige pelo menos 15 amostras por folha — crítico
      em janelas pequenas (<500 apostas) para evitar folhas com 1-2 amostras.
    - scale_pos_weight: balanceamento automático se classes forem desiguais.

    Nota: o modelo só é aplicado quando is_fitted=True E n_samples >= 200.
    Abaixo disso, o Poisson puro é mais confiável.
    """

    # Mínimo de amostras para treinar — aumentado de 100 para 200
    # para evitar que o modelo tente aprender com janelas muito pequenas.
    MIN_SAMPLES_TO_FIT = 200

    def __init__(self, market_name: str):
        self.market_name = market_name
        self.model_backend = "xgboost"
        self.is_fitted = False
        self.n_samples_trained = 0

        self.model = XGBClassifier(
            n_estimators=300,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=15,
            eval_metric="logloss",
            use_label_encoder=False,
            verbosity=0,
            n_jobs=1,
        )

    def fit(self, X, y) -> bool:
        """
        Treina o modelo.

        Retorna True se o treino ocorreu, False se os dados foram insuficientes.
        Exige MIN_SAMPLES_TO_FIT amostras e pelo menos 2 classes distintas.
        """
        if len(X) < self.MIN_SAMPLES_TO_FIT or len(set(y)) < 2:
            return False

        X_arr = np.array(X)
        y_arr = np.array(y)

        self.model.fit(X_arr, y_arr)
        self.is_fitted = True
        self.n_samples_trained = len(X)

        logger.debug(
            "[MLEnsemble:%s] Treinado com %d amostras usando %s.",
            self.market_name, len(X), self.model_backend
        )
        return True

    def predict_proba(self, features) -> float | None:
        """
        Retorna P(win) para um único jogo.

        Retorna None se o modelo ainda não foi treinado (< MIN_SAMPLES_TO_FIT).
        O chamador deve tratar None como "usar probabilidade do Poisson pura".
        """
        if not self.is_fitted:
            return None

        X_arr = np.array([features])
        probs = self.model.predict_proba(X_arr)

        # probs.shape == (1, 2): probs[0][1] = P(classe 1 = vitória)
        if probs.shape[1] > 1:
            return float(probs[0][1])
        # Edge case: modelo viu só uma classe (não deve ocorrer com o guard acima)
        return float(self.model.classes_[0])

    def get_diagnostics(self) -> dict:
        """
        Retorna metadados sobre o estado do modelo para inclusão no payload
        do backtest — permite ao frontend mostrar se ML foi realmente aplicado.
        """
        return {
            "ml_backend": self.model_backend,
            "ml_is_fitted": self.is_fitted,
            "ml_samples_trained": self.n_samples_trained,
            "ml_min_samples_required": self.MIN_SAMPLES_TO_FIT,
        }
