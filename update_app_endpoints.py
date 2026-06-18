import codecs
import re

with codecs.open('C:\\Users\\Gustavo\\.gemini\\antigravity\\scratch\\football-backtester\\backend\\app.py', 'r', 'utf-8') as f:
    content = f.read()

# 1. Update PredictRequest
old_predict_req = """class PredictRequest(BaseModel):
    league: str
    homeTeam: str
    awayTeam: str"""

new_predict_req = """class PredictRequest(BaseModel):
    league: str
    homeTeam: str
    awayTeam: str
    data_source: str = "footballdata"
    futpython_api_key: str = "" """

content = content.replace(old_predict_req, new_predict_req)

# 2. Update get_teams
old_get_teams = """@app.get("/api/teams")
def get_teams(league: str):
    try:
        df = load_league_data(league, start_date='2020-08-01')"""

new_get_teams = """@app.get("/api/teams")
def get_teams(league: str, source: str = "footballdata", api_key: str = ""):
    try:
        df = load_league_data(league, start_date='2020-08-01', data_source=source, api_key=api_key)"""

content = content.replace(old_get_teams, new_get_teams)

# 3. Update predict_matchup
old_predict_matchup = """@app.post("/api/predict")
def predict_matchup(req: PredictRequest):
    try:
        df = load_league_data(req.league, start_date='2020-08-01')"""

new_predict_matchup = """@app.post("/api/predict")
def predict_matchup(req: PredictRequest):
    try:
        df = load_league_data(req.league, start_date='2020-08-01', data_source=req.data_source, api_key=req.futpython_api_key)"""

content = content.replace(old_predict_matchup, new_predict_matchup)

with codecs.open('C:\\Users\\Gustavo\\.gemini\\antigravity\\scratch\\football-backtester\\backend\\app.py', 'w', 'utf-8') as f:
    f.write(content)
print("app.py updated")
