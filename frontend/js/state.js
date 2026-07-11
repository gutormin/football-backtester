// Shared mutable state between modules — exposed on window for read/write access.
// ES module imports are read-only live bindings, so direct assignment by importers fails.
// All modules reference these via window.xxx (e.g. window.allTelegramTips = tips).
window.allBets = [];
window.allTelegramTips = [];
window.lastScanResults = null;
window.lastScanParams = null;
window.lastBacktestSummary = null;
window.lastBacktestParams = null;
window.appliedOptimizationSuggestions = new Set();
window.currentBetsForPagination = [];
window.currentPage = 1;
window.rowsPerPage = 500;
window.betsAscending = true;
