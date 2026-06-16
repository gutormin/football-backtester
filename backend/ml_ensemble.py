import numpy as np
try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except ImportError:
    HAS_XGB = False
    from sklearn.ensemble import RandomForestClassifier

class MLEnsemble:
    def __init__(self, market_name):
        self.market_name = market_name
        if HAS_XGB:
            self.model = XGBClassifier(
                n_estimators=50,
                max_depth=3,
                learning_rate=0.1,
                use_label_encoder=False,
                eval_metric='logloss',
                n_jobs=1
            )
        else:
            self.model = RandomForestClassifier(
                n_estimators=50,
                max_depth=4,
                n_jobs=1,
                random_state=42
            )
        self.is_fitted = False
        
    def fit(self, X, y):
        """
        X: list of feature lists [ [f1, f2, ...], ... ]
        y: list of outcomes [0, 1, 0, 1, ...]
        """
        if len(X) < 100 or len(set(y)) < 2:
            return False
            
        X_arr = np.array(X)
        y_arr = np.array(y)
        
        self.model.fit(X_arr, y_arr)
        self.is_fitted = True
        return True
        
    def predict_proba(self, features):
        """
        features: list of feature values [f1, f2, ...]
        returns the probability of class 1 (win)
        """
        if not self.is_fitted:
            return None
            
        X_arr = np.array([features])
        probs = self.model.predict_proba(X_arr)
        
        # probs has shape (1, 2). probs[0][1] is probability of class 1
        # If the model only saw one class (shouldn't happen due to len(set(y)) >= 2 guard), it might fail,
        # but sklearn handles it.
        
        if probs.shape[1] > 1:
            return float(probs[0][1])
        else:
            return float(self.model.classes_[0])
