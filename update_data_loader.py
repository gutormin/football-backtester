import codecs
import re

with codecs.open('C:\\Users\\Gustavo\\.gemini\\antigravity\\scratch\\football-backtester\\backend\\data_loader.py', 'r', 'utf-8') as f:
    content = f.read()

old_code = """                df = df.rename(columns={
                    'Home': 'HomeTeam',
                    'Away': 'AwayTeam',
                    'Home_Score': 'FTHG',
                    'Away_Score': 'FTAG',
                    'Odd_1_FT': 'B365H',
                    'Odd_X_FT': 'B365D',
                    'Odd_2_FT': 'B365A',
                    'Over_FT_2_5': 'B365>2.5',
                    'Under_FT_2_5': 'B365<2.5'
                })
                dataframes.append(df)"""

new_code = """                df = df.rename(columns={
                    'Home': 'HomeTeam',
                    'Away': 'AwayTeam',
                    'Home_Score': 'FTHG',
                    'Away_Score': 'FTAG',
                    'Odd_1_FT': 'B365H',
                    'Odd_X_FT': 'B365D',
                    'Odd_2_FT': 'B365A',
                    'Over_FT_2_5': 'B365>2.5',
                    'Under_FT_2_5': 'B365<2.5'
                })
                
                # Fix comma-separated decimals for all numeric columns in FutPythonTrader
                for col in df.columns:
                    if col not in ['HomeTeam', 'AwayTeam', 'League', 'Date', 'Time']:
                        if df[col].dtype == 'object':
                            df[col] = df[col].astype(str).str.replace(',', '.')
                            df[col] = pd.to_numeric(df[col], errors='ignore')
                            
                dataframes.append(df)"""

if old_code in content:
    content = content.replace(old_code, new_code)
    with codecs.open('C:\\Users\\Gustavo\\.gemini\\antigravity\\scratch\\football-backtester\\backend\\data_loader.py', 'w', 'utf-8') as f:
        f.write(content)
    print("Replaced successfully!")
else:
    print("Old code not found!")
