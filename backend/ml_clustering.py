import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA

def extract_league_features(league_code, df):
    """Extrai características estatísticas de uma liga a partir do seu dataframe de partidas."""
    if df.empty:
        return None
        
    df = df.copy()
    df['FTHG'] = pd.to_numeric(df['FTHG'], errors='coerce')
    df['FTAG'] = pd.to_numeric(df['FTAG'], errors='coerce')
    df = df.dropna(subset=['FTHG', 'FTAG'])
    
    if len(df) < 20: # Ignorar ligas com dados insuficientes
        return None
        
    total_goals = df['FTHG'] + df['FTAG']
    
    home_wins = (df['FTHG'] > df['FTAG']).mean()
    draws = (df['FTHG'] == df['FTAG']).mean()
    away_wins = (df['FTHG'] < df['FTAG']).mean()
    
    over25 = (total_goals > 2.5).mean()
    btts = ((df['FTHG'] > 0) & (df['FTAG'] > 0)).mean()
    
    avg_goals = total_goals.mean()
    
    return {
        'league': league_code,
        'avg_goals': float(avg_goals),
        'home_win_pct': float(home_wins),
        'draw_pct': float(draws),
        'away_win_pct': float(away_wins),
        'over25_pct': float(over25),
        'btts_pct': float(btts),
        'matches_count': len(df)
    }

def cluster_leagues(features_list, n_clusters=None):
    """
    Agrupa as ligas usando K-Means e gera coordenadas 2D (PCA) para visualização.
    """
    if not features_list or len(features_list) < 3:
        return {'error': 'Ligas insuficientes para clusterização. Selecione pelo menos 3 ligas com dados válidos.'}
        
    df = pd.DataFrame(features_list)
    
    # Selecionar features para o algoritmo
    X = df[['avg_goals', 'home_win_pct', 'draw_pct', 'over25_pct', 'btts_pct']]
    
    # Padronização (Z-Score)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # Se n_clusters não foi definido, tenta estimar um valor razoável
    if n_clusters is None or n_clusters < 2:
        n_clusters = max(2, min(5, int(np.sqrt(len(df) / 2))))
        
    n_clusters = min(n_clusters, len(df) - 1)
        
    # Agrupamento K-Means
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    clusters = kmeans.fit_predict(X_scaled)
    df['cluster'] = int(clusters) if isinstance(clusters, int) else clusters.tolist() # fix typing for json
    
    # Redução de Dimensionalidade (PCA) para X e Y do gráfico
    pca = PCA(n_components=2)
    pca_result = pca.fit_transform(X_scaled)
    df['pca_x'] = pca_result[:, 0].tolist()
    df['pca_y'] = pca_result[:, 1].tolist()
    
    # Preparar resultado para o frontend
    result_list = df.to_dict('records')
    
    # Compilar dados macro por cluster
    clusters_info = []
    for c in range(n_clusters):
        cluster_data = df[df['cluster'] == c]
        if len(cluster_data) > 0:
            clusters_info.append({
                'cluster_id': int(c),
                'count': int(len(cluster_data)),
                'avg_goals': float(cluster_data['avg_goals'].mean()),
                'over25_pct': float(cluster_data['over25_pct'].mean()),
                'home_win_pct': float(cluster_data['home_win_pct'].mean()),
                'draw_pct': float(cluster_data['draw_pct'].mean()),
                'btts_pct': float(cluster_data['btts_pct'].mean()),
                'leagues': cluster_data['league'].tolist()
            })
        
    return {
        'points': result_list,
        'clusters': clusters_info,
        'x_variance_explained': float(pca.explained_variance_ratio_[0]),
        'y_variance_explained': float(pca.explained_variance_ratio_[1])
    }
