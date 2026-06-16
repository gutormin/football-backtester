import numpy as np

class PlattCalibrator:
    def __init__(self, learning_rate=0.01, epochs=1000):
        self.A = 1.0
        self.B = 0.0
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.fitted = False

    def _logit(self, p):
        p_clipped = np.clip(p, 1e-5, 1 - 1e-5)
        return np.log(p_clipped / (1 - p_clipped))

    def _sigmoid(self, z):
        z = np.clip(z, -500, 500)
        return 1 / (1 + np.exp(-z))

    def fit(self, probs, y):
        if len(probs) < 20 or len(set(y)) < 2:
            return
            
        probs = np.array(probs)
        y = np.array(y)
        X = self._logit(probs)
        
        m = len(y)
        A = self.A
        B = self.B
        
        for _ in range(self.epochs):
            z = A * X + B
            h = self._sigmoid(z)
            
            dz = h - y
            dA = (1/m) * np.sum(dz * X)
            dB = (1/m) * np.sum(dz)
            
            A -= self.learning_rate * dA
            B -= self.learning_rate * dB
            
        self.A = float(A)
        self.B = float(B)
        self.fitted = True

    def calibrate(self, p):
        if not self.fitted:
            return p
        x = self._logit(p)
        return float(self._sigmoid(self.A * x + self.B))
