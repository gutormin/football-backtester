const jsdom = require("jsdom");
const { JSDOM } = jsdom;
const fs = require('fs');

const html = fs.readFileSync('index.html', 'utf8');
const dom = new JSDOM(html, { runScripts: "dangerously" });

// Mock fetch
dom.window.fetch = async (url, options) => {
    return {
        ok: true,
        json: async () => {
            return {
                summary: {
                    net_profit: 100,
                    profit_in_stakes: 10,
                    roi: 5.5,
                    win_rate: 60,
                    avg_odds: 2.0,
                    max_drawdown: 10,
                    total_bets: 100,
                    final_bankroll: 1100,
                    sharpe_ratio: 1.5,
                    sortino_ratio: 2.0,
                    skewness: 0.1
                },
                bets: [],
                equity_curve: [1000, 1100],
                equity_curve_fixed: [1000, 1100],
                equity_curve_proportional: [1000, 1100],
                equity_curve_kelly: [1000, 1100],
                league_stats: [],
                monthly_stats: [],
                odds_stats: [],
                portfolio_optimization: null,
                ai_analysis: { insight: "test" },
                quartiles: {}
            };
        }
    };
};

// Mock Chart.js
dom.window.Chart = class {
    constructor(ctx, config) {
        this.ctx = ctx;
        this.config = config;
    }
    destroy() {}
};
dom.window.equityChart = undefined;
dom.window.leagueChart = undefined;
dom.window.monthlyChart = undefined;
dom.window.oddsChart = undefined;

// Mock ctx functions
dom.window.HTMLCanvasElement.prototype.getContext = function () {
    return {
        createLinearGradient: () => {
            return { addColorStop: () => {} };
        }
    };
};

const appJs = fs.readFileSync('app.js', 'utf8');

try {
    dom.window.eval(appJs);
    console.log("app.js loaded successfully.");
} catch (e) {
    console.error("Error evaluating app.js:", e);
}

// Call runBacktest
(async () => {
    try {
        console.log("Running runBacktest...");
        await dom.window.runBacktest();
        console.log("runBacktest finished.");
    } catch (e) {
        console.error("Error during runBacktest:", e);
    }
})();
