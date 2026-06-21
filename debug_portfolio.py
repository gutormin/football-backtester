from backend.history_manager import load_history
from backend.portfolio_backtester import run_portfolio
import traceback

def test():
    try:
        history = load_history()
        if not history:
            print("No history found.")
            return
        
        # Select first 2 strategies
        ids = [h['id'] for h in history[:2]]
        print(f"Running portfolio for IDs: {ids}")
        
        res = run_portfolio(ids)
        if "error" in res:
            print("Error returned by run_portfolio:", res["error"])
        else:
            print("Success! Final Bankroll:", res.get("final_bankroll"))
    except Exception as e:
        print("Exception caught:")
        traceback.print_exc()

if __name__ == "__main__":
    test()
