"""Centralized model constants — single source of truth for all tunable parameters."""

# ── Dixon-Coles (rho) ──────────────────────────────────────────────
RHO_FALLBACK = -0.085
RHO_MLE_BOUNDS = (-0.20, 0.05)
RHO_MLE_WINDOW = 200
RHO_MLE_MIN_MATCHES = 50
RHO_CACHE_INVALIDATION_MATCHES = 50

# ── Decay ──────────────────────────────────────────────────────────
TIME_DECAY_XI = 0.0065          # Exponential time decay (half-life ~106 days)
PERFORMANCE_DECAY_BASE = 0.06    # Performance-weighted decay for rolling form
PERFORMANCE_REFERENCE_GAMES = 38  # Reference season length for league scaling

# ── Overdispersion (Negative Binomial) ─────────────────────────────
NB_ALPHA_HOME = 0.12
NB_ALPHA_AWAY = 0.10

# ── Shrinkage ──────────────────────────────────────────────────────
SHRINKAGE_FT = 0.70              # Full-time ratings (70% data / 30% prior)
SHRINKAGE_HT = 0.60              # Half-time ratings (60% data / 40% prior)
RATING_CAP_LOW = 0.4
RATING_CAP_HIGH = 2.5
LAMBDA_CAP_LOW = 0.5
LAMBDA_CAP_HIGH = 5.0
LAMBDA_CAP_HT_LOW = 0.35
LAMBDA_CAP_HT_HIGH = 2.5

# ── Blending weights ───────────────────────────────────────────────
BLEND_XG = 0.50
BLEND_SOT = 0.30
BLEND_GOALS = 0.20
BLEND_NO_XG_GOALS = 0.60
BLEND_NO_XG_SOT = 0.40

# ── Elo ────────────────────────────────────────────────────────────
ELO_K_FACTOR = 20
ELO_HOME_ADVANTAGE = 65

# ── HT rating caps ──────────────────────────────────────────────────
HT_RATING_CAP_LOW = 0.5
HT_RATING_CAP_HIGH = 2.0
HT_AWAY_FLOOR_FACTOR = 0.7

# ── Score matrix ───────────────────────────────────────────────────
MAX_GOALS = 8
