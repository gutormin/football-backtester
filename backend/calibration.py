from sklearn.isotonic import IsotonicRegression
import numpy as np

class PlattCalibrator:
    """
    Isotonic Calibrator wrapper. We keep the class name PlattCalibrator to 
    maintain compatibility with imports in other backend modules.
    
    Isotonic Regression is non-parametric and significantly more robust 
    than Platt scaling (sigmoid fitting) when dealing with class imbalance 
    (e.g., highly skewed win rates/draw rates in sports betting).
    """
    def __init__(self, epochs=200):
        # PlattCalibrator signatures had 'epochs', we accept it for compatibility
        self.model = IsotonicRegression(out_of_bounds='clip')
        self.fitted = False

    def fit(self, probs, y):
        # We need a reasonable sample size and at least 2 distinct classes to fit
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
            # Clip between 0.1% and 99.9% to avoid division by zero or infinite odds
            return float(np.clip(val, 0.001, 0.999))
        except Exception:
            return p
