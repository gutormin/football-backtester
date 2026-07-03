from sklearn.isotonic import IsotonicRegression
import numpy as np

class IsotonicCalibrator:
    """
    Non-parametric probability calibrator using Isotonic Regression.

    Isotonic Regression is more robust than Platt scaling (sigmoid fitting)
    when dealing with class imbalance — common in sports betting where win/draw
    rates are highly skewed. It makes no parametric assumptions about the
    calibration curve shape.
    """
    def __init__(self, epochs=200):
        self.model = IsotonicRegression(out_of_bounds='clip')
        self.fitted = False

    def fit(self, probs, y):
        if len(probs) < 20 or len(set(y)) < 2:
            return

        probs = np.array(probs, dtype=float)
        y = np.array(y, dtype=float)

        try:
            self.model.fit(probs, y)
            self.fitted = True
        except Exception:
            self.fitted = False

    def calibrate(self, p):
        if not self.fitted:
            return p
        try:
            val = self.model.predict(np.array([p]))[0]
            return float(np.clip(val, 0.001, 0.999))
        except Exception:
            return p
