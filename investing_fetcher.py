"""
investing_fetcher.py — Recupero prezzi storici settimanali da investing.com
(API interna non documentata, la stessa usata dal sito web).

Flusso per ogni ISIN:
  1. ricerca:   https://api.investing.com/api/search/v2/search?q=<ISIN>
     restituisce gli strumenti corrispondenti con id numerico e borsa;
  2. selezione: preferenza Borsa di Milano, poi borse dell'area Euro;
  3. valuta:    la pagina dello strumento riporta "Currency in XXX";
     si accetta solo EUR (per i fondi il controllo e' obbligatorio,
     per strumenti quotati su borse area-Euro si assume EUR se la
     pagina non e' leggibile);
  4. storico:   endpoint chart tvc4.investing.com → OHLC settimanale.

NOTA: API non ufficiale. Puo' smettere di funzionare se investing.com
cambia il sito; l'uso automatizzato non e' previsto dai loro ToS.
"""

import random
import re
import time
import datetime as dt

import pandas as pd

try:
    from curl_cffi import requests as _rq
    _IMPERSONATE = True
except ImportError:  # pragma: no cover
    import requests as _rq
    _IMPERSONATE = False

SEARCH_URL = "https://api.investing.com/api/search/v2/search?q={q}"
CHART_URL = ("https://tvc4.investing.com/{uid}/0/0/0/0/history"
             "?symbol={pair_id}&resolution=W&from={f}&to={t}")
PAGE_URL = "https://www.investing.com{path}?cid={pair_id}"

# Borse area Euro (i prezzi locali sono in EUR).
EURO_EXCHANGES = {
    "milan", "xetra", "frankfurt", "stuttgart", "munich", "dusseldorf",
    "berlin", "hamburg", "hanover", "paris", "amsterdam", "brussels",
    "lisbon", "madrid", "vienna", "dublin", "luxembourg", "helsinki",
    "athens", "italy",
}

_HEADERS_API = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "domain-id": "www",
    "Referer": "https://www.investing.com/",
}


def _get(url: str, timeout: int = 25):
    kwargs = {"headers": _HEADERS_API, "timeout": timeout}
    if _IMPERSONATE:
        kwargs["impersonate"] = "chrome"
    return _rq.get(url, **kwargs)


def _exchange_rank(exchange: str) -> int:
    e = (exchange or "").strip().lower()
    if e == "milan":
        return 0
    if e in EURO_EXCHANGES:
        return 1
    return 2


def search_isin(isin: str) -> list[dict]:
    """Cerca l'ISIN; ritorna i candidati ordinati per preferenza borsa."""
    r = _get(SEARCH_URL.format(q=isin))
    r.raise_for_status()
    quotes = (r.json() or {}).get("quotes", []) or []
    quotes.sort(key=lambda q: _exchange_rank(q.get("exchange", "")))
    return quotes


def _page_currency(quote: dict) -> str:
    """Legge la valuta dalla pagina dello strumento. '' se non determinabile."""
    path = quote.get("url") or ""
    if not path:
        return ""
    try:
        r = _get(PAGE_URL.format(path=path.split("?")[0], pair_id=quote["id"]))
        if r.status_code != 200:
            return ""
        html = r.text
        m = re.search(r"Currency in[^A-Za-z]{0,80}?([A-Z]{3})", html)
        if m:
            return m.group(1)
        m = re.search(r'"currency"\s*:\s*"([A-Z]{3})"', html)
        return m.group(1) if m else ""
    except Exception:
        return ""


def get_weekly_history(pair_id: int, start: dt.date, end: dt.date) -> pd.DataFrame:
    """Storico settimanale (chiusure) per uno strumento. Colonne: Data, Prezzo."""
    uid = "".join(random.choices("0123456789abcdef", k=32))
    f = int(dt.datetime(start.year, start.month, start.day,
                        tzinfo=dt.timezone.utc).timestamp())
    t = int(dt.datetime(end.year, end.month, end.day, 23, 59,
                        tzinfo=dt.timezone.utc).timestamp())
    r = _get(CHART_URL.format(uid=uid, pair_id=pair_id, f=f, t=t))
    r.raise_for_status()
    data = r.json()
    if data.get("s") != "ok" or not data.get("t"):
        return pd.DataFrame()
    dates = [dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date()
             for ts in data["t"]]
    df = pd.DataFrame({"Data": pd.to_datetime(dates), "Prezzo": data["c"]})
    return df.dropna()


def fetch_from_investing(isin: str, start: dt.date, end: dt.date,
                         pause: float = 1.0) -> tuple[pd.DataFrame, dict, str]:
    """
    Recupera lo storico settimanale EUR per un ISIN.
    Ritorna (DataFrame, info_strumento, motivo_fallimento).
    DataFrame vuoto + motivo se non recuperabile.
    """
    try:
        candidates = search_isin(isin)
    except Exception as exc:
        return pd.DataFrame(), {}, f"investing.com: ricerca fallita ({exc})"
    if not candidates:
        return pd.DataFrame(), {}, "investing.com: ISIN non trovato"

    tried = []
    non_eur = []  # candidati in altra valuta: usati solo se nessuna quotazione EUR
    for q in candidates[:6]:
        time.sleep(pause)  # evita rate limiting
        label = f"{q.get('symbol', '?')}@{q.get('exchange', '?')}"
        qtype = (q.get("type") or "").lower()
        is_fund = "fund" in qtype
        rank = _exchange_rank(q.get("exchange", ""))

        if not is_fund and rank <= 1:
            # strumento quotato su una borsa dell'area Euro: il prezzo
            # locale e' in EUR per costruzione. Niente verifica via pagina:
            # la pagina mostra il listing di default (spesso Londra/USD)
            # ignorando la borsa richiesta, e produrrebbe falsi scarti.
            currency = "EUR"
        else:
            currency = _page_currency(q)
        if currency and currency != "EUR":
            non_eur.append((q, currency))
            tried.append(f"{label}: valuta {currency}")
            continue
        if not currency:
            # valuta non leggibile (solo fondi o borse extra-Euro):
            # troppo rischioso procedere senza conferma
            tried.append(f"{label}: valuta non verificabile")
            continue

        try:
            df = get_weekly_history(int(q["id"]), start, end)
        except Exception as exc:
            tried.append(f"{label}: errore storico ({exc})")
            continue
        if df.empty:
            tried.append(f"{label}: nessun dato nel periodo")
            continue

        info = {"symbol": q.get("symbol", ""), "exchange": q.get("exchange", ""),
                "currency": currency or "EUR", "source": "investing.com",
                "pair_id": q.get("id")}
        return df, info, ""

    # Nessuna quotazione EUR: si ripiega sulla migliore in altra valuta
    # (la conversione in EUR e' a carico del chiamante).
    for q, currency in non_eur:
        try:
            df = get_weekly_history(int(q["id"]), start, end)
        except Exception:
            continue
        if df.empty:
            continue
        info = {"symbol": q.get("symbol", ""), "exchange": q.get("exchange", ""),
                "currency": currency, "source": "investing.com",
                "pair_id": q.get("id")}
        return df, info, ""

    return pd.DataFrame(), {}, ("investing.com: nessuna quotazione utilizzabile. "
                                "Tentativi: " + "; ".join(tried[:6]))
