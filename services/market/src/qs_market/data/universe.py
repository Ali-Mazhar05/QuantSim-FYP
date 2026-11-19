"""The starting universe: 30 large-cap US equities and 10 ETFs (PRD FR-20).

Plain data, so the seed needs neither the network nor the Nasdaq symbol directory.
Each row is (symbol, name, sector, listing exchange MIC, asset class). The calendar is
XNYS and the currency USD for all of them.
"""

UNIVERSE: tuple[tuple[str, str, str, str, str], ...] = (
    ("AAPL", "Apple Inc.", "Technology", "XNAS", "equity"),
    ("MSFT", "Microsoft Corporation", "Technology", "XNAS", "equity"),
    ("NVDA", "NVIDIA Corporation", "Technology", "XNAS", "equity"),
    ("GOOGL", "Alphabet Inc. Class A", "Communication Services", "XNAS", "equity"),
    ("AMZN", "Amazon.com, Inc.", "Consumer Discretionary", "XNAS", "equity"),
    ("META", "Meta Platforms, Inc.", "Communication Services", "XNAS", "equity"),
    ("TSLA", "Tesla, Inc.", "Consumer Discretionary", "XNAS", "equity"),
    ("AVGO", "Broadcom Inc.", "Technology", "XNAS", "equity"),
    ("COST", "Costco Wholesale Corporation", "Consumer Staples", "XNAS", "equity"),
    ("NFLX", "Netflix, Inc.", "Communication Services", "XNAS", "equity"),
    ("ADBE", "Adobe Inc.", "Technology", "XNAS", "equity"),
    ("PEP", "PepsiCo, Inc.", "Consumer Staples", "XNAS", "equity"),
    ("CSCO", "Cisco Systems, Inc.", "Technology", "XNAS", "equity"),
    ("INTC", "Intel Corporation", "Technology", "XNAS", "equity"),
    ("AMD", "Advanced Micro Devices, Inc.", "Technology", "XNAS", "equity"),
    ("BRK.B", "Berkshire Hathaway Inc. Class B", "Financials", "XNYS", "equity"),
    ("JPM", "JPMorgan Chase & Co.", "Financials", "XNYS", "equity"),
    ("V", "Visa Inc.", "Financials", "XNYS", "equity"),
    ("MA", "Mastercard Incorporated", "Financials", "XNYS", "equity"),
    ("BAC", "Bank of America Corporation", "Financials", "XNYS", "equity"),
    ("WMT", "Walmart Inc.", "Consumer Staples", "XNYS", "equity"),
    ("KO", "The Coca-Cola Company", "Consumer Staples", "XNYS", "equity"),
    ("PG", "The Procter & Gamble Company", "Consumer Staples", "XNYS", "equity"),
    ("JNJ", "Johnson & Johnson", "Health Care", "XNYS", "equity"),
    ("UNH", "UnitedHealth Group Incorporated", "Health Care", "XNYS", "equity"),
    ("LLY", "Eli Lilly and Company", "Health Care", "XNYS", "equity"),
    ("XOM", "Exxon Mobil Corporation", "Energy", "XNYS", "equity"),
    ("CVX", "Chevron Corporation", "Energy", "XNYS", "equity"),
    ("HD", "The Home Depot, Inc.", "Consumer Discretionary", "XNYS", "equity"),
    ("DIS", "The Walt Disney Company", "Communication Services", "XNYS", "equity"),
    ("SPY", "SPDR S&P 500 ETF Trust", "Broad Market ETF", "XNYS", "etf"),
    ("QQQ", "Invesco QQQ Trust", "Broad Market ETF", "XNAS", "etf"),
    ("IWM", "iShares Russell 2000 ETF", "Broad Market ETF", "XNYS", "etf"),
    ("DIA", "SPDR Dow Jones Industrial Average ETF Trust", "Broad Market ETF", "XNYS", "etf"),
    ("VTI", "Vanguard Total Stock Market ETF", "Broad Market ETF", "XNYS", "etf"),
    ("VOO", "Vanguard S&P 500 ETF", "Broad Market ETF", "XNYS", "etf"),
    ("XLF", "Financial Select Sector SPDR Fund", "Sector ETF", "XNYS", "etf"),
    ("XLK", "Technology Select Sector SPDR Fund", "Sector ETF", "XNYS", "etf"),
    ("XLE", "Energy Select Sector SPDR Fund", "Sector ETF", "XNYS", "etf"),
    ("GLD", "SPDR Gold Shares", "Commodity ETF", "XNYS", "etf"),
)

CALENDAR = "XNYS"
CURRENCY = "USD"
