"""
fx.py — Conversione in EUR di serie di prezzi in altra valuta.

Usa i cambi storici settimanali. Fonte primaria: Yahoo Finance
(simboli tipo "USDEUR=X"); fallback: investing.com (cross valutari).
Le serie vengono allineate per data con tolleranza di 7 giorni.
"""

import datetime as dt

import pandas as pd

_CACHE: dict[tuple, pd.DataFrame] = {}


def _fx_from_yahoo(cur: str, start, end) -> pd.DataFrame:
    import yfinance as yf
    t = yf.Ticker(f"{cur}EUR=X")
    hist = t.history(start=start, end=end, interval="1wk", auto_adjust=False)
    if hist is None or hist.empty or "Close" not in hist.columns:
        return pd.DataFrame()
    df = hist.reset_index()[["Date", "Close"]].dropna()
    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None).dt.normalize()
    return df.rename(columns={"Date": "Data", "Close": "Cambio"})


def _fx_from_investing(cur: str, start, end) -> pd.DataFrame:
    from investing_fetcher import search_isin, get_weekly_history
    try:
        quotes = search_isin(f"{cur}/EUR")
    except Exception:
        return pd.DataFrame()
    quotes = [q for q in quotes
              if (q.get("symbol", "").upper().replace(" ", "") == f"{cur}/EUR")]
    if not quotes:
        return pd.DataFrame()
    df = get_weekly_history(int(quotes[0]["id"]), start, end)
    return df.rename(columns={"Prezzo": "Cambio"})


def get_fx_weekly(cur: str, start, end) -> pd.DataFrame:
    """Serie settimanale del cambio cur→EUR. Colonne: Data, Cambio."""
    cur = cur.upper()
    key = (cur, str(start), str(end))
    if key in _CACHE:
        return _CACHE[key]
    df = pd.DataFrame()
    try:
        df = _fx_from_yahoo(cur, start, end)
    except Exception:
        df = pd.DataFrame()
    if df.empty:
        try:
            df = _fx_from_investing(cur, start, end)
        except Exception:
            df = pd.DataFrame()
    _CACHE[key] = df
    return df


def convert_to_eur(prices: pd.DataFrame, currency: str, start, end) -> pd.DataFrame:
    """
    Converte una serie di prezzi (colonne Data, Prezzo) in EUR.
    Gestisce anche GBp/GBX (pence: prezzo/100, poi GBP→EUR).
    Ritorna DataFrame vuoto se il cambio non e' recuperabile.
    """
    cur = currency.strip()
    df = prices.copy()

    if cur in ("GBp", "GBX", "gbp_pence"):
        df["Prezzo"] = df["Prezzo"] / 100.0
        cur = "GBP"
    cur = cur.upper()
    if cur == "EUR":
        return df

    fx = get_fx_weekly(cur, start - dt.timedelta(days=10), end)
    if fx.empty:
        return pd.DataFrame()

    df = df.sort_values("Data")
    fx = fx.sort_values("Data")
    merged = pd.merge_asof(df, fx, on="Data", direction="nearest",
                           tolerance=pd.Timedelta(days=7))
    merged = merged.dropna(subset=["Cambio"])
    if merged.empty:
        return pd.DataFrame()
    merged["Prezzo"] = merged["Prezzo"] * merged["Cambio"]
    return merged[["Data", "Prezzo"]]
