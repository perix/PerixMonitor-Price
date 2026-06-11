"""
fondidoc_fetcher.py — Recupero NAV storici da fondidoc.it (FIDA).

Copre i fondi (e molti ETF) distribuiti in Italia. Il server converte
direttamente in EUR (parametro cur=EUR), quindi non serve conversione.

Flusso:
  1. ricerca ISIN:  /Ricerca/Res?txt=<ISIN>  → codici interni delle classi
     (es. FFAGGA; possono contenere caratteri speciali come '$', URL-encoded);
     se un ISIN ha piu' classi/viste, viene preferita quella col nome "EUR";
  2. serie storica: /Chart/ChartData?ids=<codice>&cur=EUR&nl=1
                    &dateFrom=<ms>&dateEnd=<ms>
     → JSON { codice: { desc, cur, data: [[t, nav], ...] } }
     dove t = secondi Unix / 100, mezzanotte italiana;
  3. i NAV giornalieri vengono ricampionati su base settimanale
     (ultimo NAV della settimana, etichettato col lunedi').

NOTA: endpoint non documentato; puo' cambiare senza preavviso.
"""

import datetime as dt
import re
from urllib.parse import quote, unquote

import pandas as pd

try:
    from curl_cffi import requests as _rq
    _IMPERSONATE = True
except ImportError:  # pragma: no cover
    import requests as _rq
    _IMPERSONATE = False

SEARCH_URL = "https://www.fondidoc.it/Ricerca/Res?txt={isin}"
DATA_URL = ("https://www.fondidoc.it/Chart/ChartData"
            "?ids={code}&cur=EUR&nl=1&dateFrom={f}&dateEnd={t}")

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "*/*",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.fondidoc.it/",
}


def _get(url: str, timeout: int = 25):
    kwargs = {"headers": _HEADERS, "timeout": timeout}
    if _IMPERSONATE:
        kwargs["impersonate"] = "chrome"
    return _rq.get(url, **kwargs)


def search_codes(isin: str) -> list[tuple[str, str]]:
    """
    Cerca l'ISIN; ritorna [(codice, nome), ...] ordinati per preferenza:
    prima le classi/viste con 'EUR' nel nome. Lista vuota se non trovato.
    """
    r = _get(SEARCH_URL.format(isin=isin))
    if r.status_code != 200:
        return []
    html = r.text
    # link tipo /d/Index/<codice>/<isin>_<slug>">Nome classe<
    pat = re.compile(
        r"/d/Index/([^/\"'\s]+)/" + re.escape(isin) + r"[^\"'>]*[\"']?>([^<]*)<",
        re.I)
    matches = [(unquote(c), n.strip()) for c, n in pat.findall(html)]
    if not matches:
        m = re.search(r"/d/Index/([^/\"'\s]+)/", html)
        return [(unquote(m.group(1)), "")] if m else []
    # dedup mantenendo l'ordine
    seen, out = set(), []
    for c, n in matches:
        if c not in seen:
            seen.add(c)
            out.append((c, n))
    out.sort(key=lambda cn: 0 if "EUR" in cn[1].upper() else 1)
    return out


def get_weekly_history(code: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    """Storico settimanale EUR (ultimo NAV della settimana). Colonne: Data, Prezzo."""
    f = int(dt.datetime(start.year, start.month, start.day,
                        tzinfo=dt.timezone.utc).timestamp() * 1000)
    t = int(dt.datetime(end.year, end.month, end.day, 23, 59,
                        tzinfo=dt.timezone.utc).timestamp() * 1000)
    r = _get(DATA_URL.format(code=quote(code, safe=""), f=f, t=t))
    if r.status_code != 200:
        return pd.DataFrame()
    payload = r.json() or {}
    series = payload.get(code)
    if series is None and payload:
        # il server puo' normalizzare il codice: usa la prima serie disponibile
        series = next(iter(payload.values()), None)
    rows = (series or {}).get("data") or []
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["ts", "Prezzo"]).dropna()
    # timestamp = secondi Unix / 100, riferiti alla mezzanotte italiana:
    # vanno convertiti al fuso Europe/Rome o le date slittano di un giorno
    df["Data"] = (pd.to_datetime(df["ts"] * 100, unit="s", utc=True)
                    .dt.tz_convert("Europe/Rome")
                    .dt.tz_localize(None)
                    .dt.normalize())
    df = df[(df["Data"] >= pd.Timestamp(start)) & (df["Data"] <= pd.Timestamp(end))]
    if df.empty:
        return pd.DataFrame()

    # ultimo NAV della settimana, etichettato col lunedi' (convenzione Yahoo)
    wk = (df.sort_values("Data")
            .groupby(df["Data"].dt.to_period("W-SUN"))["Prezzo"].last())
    return pd.DataFrame({
        "Data": [p.start_time.normalize() for p in wk.index],
        "Prezzo": wk.values,
    })


def fetch_from_fondidoc(isin: str, start: dt.date,
                        end: dt.date) -> tuple[pd.DataFrame, dict, str]:
    """
    Recupera lo storico settimanale EUR per un ISIN, provando in ordine
    le classi trovate. Ritorna (DataFrame, info, motivo_fallimento).
    """
    try:
        candidates = search_codes(isin)
    except Exception as exc:
        return pd.DataFrame(), {}, f"fondidoc: ricerca fallita ({exc})"
    if not candidates:
        return pd.DataFrame(), {}, "fondidoc: ISIN non trovato"

    tried = []
    for code, name in candidates[:4]:
        try:
            df = get_weekly_history(code, start, end)
        except Exception as exc:
            tried.append(f"{code}: errore ({exc})")
            continue
        if df.empty:
            tried.append(f"{code}: nessun dato nel periodo")
            continue
        info = {"symbol": code, "exchange": "NAV (fondidoc)", "currency": "EUR",
                "source": "fondidoc.it", "desc": name}
        return df, info, ""

    return pd.DataFrame(), {}, "fondidoc: " + "; ".join(tried[:4])
