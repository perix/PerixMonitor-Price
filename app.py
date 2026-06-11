"""
app.py — PerixMonitor Price: lettura storico prezzi settimanali in EUR.

Avvio:  streamlit run app.py
"""

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from exports import build_executed_workbook, build_report_workbook
from price_fetcher import build_output_workbook, fetch_asset, read_asset_list

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

APP_VERSION = "3.0"

st.set_page_config(page_title="PerixMonitor Price", page_icon="📈", layout="wide")
st.title("📈 PerixMonitor Price — Lettura storico prezzi")
st.caption(f"Versione {APP_VERSION} — fonti: investing.com → fondidoc.it → Yahoo Finance")
st.caption(
    "Carica la lista asset (formato Lista_All_Assets.xlsx), scegli il periodo, "
    "avvia la lettura. Prezzi settimanali in EUR (borsa di Milano preferita, poi "
    "altre borse europee; conversione automatica in EUR se la quotazione è in "
    "altra valuta). Fonti: investing.com, Yahoo Finance."
)

# ---------- 1. Caricamento file ----------
uploaded = st.file_uploader(
    "1. File Excel con la lista degli asset (colonne: ISIN, Descrizione Asset)",
    type=["xlsx"],
)

assets = None
if uploaded:
    try:
        assets = read_asset_list(uploaded)
        st.success(f"File letto correttamente: {len(assets)} asset trovati.")
        with st.expander("Mostra lista asset"):
            st.dataframe(assets, use_container_width=True, hide_index=True)
    except Exception as exc:
        st.error(f"Errore nella lettura del file: {exc}")

# ---------- 2. Range di date ----------
st.subheader("2. Periodo")
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input(
        "Data inizio", value=date.today() - timedelta(days=365),
        max_value=date.today(), format="DD/MM/YYYY",
    )
with col2:
    end_date = st.date_input(
        "Data fine", value=date.today(),
        max_value=date.today(), format="DD/MM/YYYY",
    )

if start_date >= end_date:
    st.warning("La data di inizio deve precedere la data di fine.")

# ---------- 3. Lettura ----------
st.subheader("3. Lettura storico prezzi")
run = st.button(
    "▶ Lettura storico prezzi",
    type="primary",
    disabled=(assets is None or assets.empty or start_date >= end_date),
)

if run:
    results = []
    progress = st.progress(0.0)
    status = st.empty()
    n = len(assets)

    for i, row in assets.iterrows():
        isin, desc = row["ISIN"], row["Descrizione Asset"]
        status.info(f"({i + 1}/{n}) Recupero {isin} — {desc} …")
        try:
            res = fetch_asset(isin, desc, start_date, end_date)
        except Exception as exc:
            from price_fetcher import FetchResult
            res = FetchResult(isin, desc, ok=False, reason=f"Errore imprevisto: {exc}")
        results.append(res)
        progress.progress((i + 1) / n)

    status.empty()
    st.session_state["results"] = results
    st.session_state["input_bytes"] = uploaded.getvalue()
    st.session_state["input_name"] = uploaded.name
    st.session_state["period"] = (start_date, end_date)

# ---------- 4. Risultati ----------
if "results" in st.session_state:
    results = st.session_state["results"]
    p_start, p_end = st.session_state["period"]
    ok = [r for r in results if r.ok]
    ko = [r for r in results if not r.ok]
    tot_rows = sum(len(r.prices) for r in ok)

    st.subheader("Risultato")
    c1, c2, c3 = st.columns(3)
    c1.metric("Asset recuperati", f"{len(ok)} / {len(results)}")
    c2.metric("Righe di prezzo", tot_rows)
    c3.metric("Asset scartati", len(ko))

    if ok:
        st.markdown("**Asset recuperati:**")
        st.dataframe(
            pd.DataFrame(
                [{"ISIN": r.isin, "Descrizione": r.description, "Simbolo": r.symbol,
                  "Borsa": r.exchange, "Valuta": r.currency, "Fonte": r.source,
                  "Settimane": len(r.prices)} for r in ok]
            ),
            use_container_width=True, hide_index=True,
        )

    if ko:
        st.markdown("**⚠ Asset NON recuperati:**")
        st.dataframe(
            pd.DataFrame(
                [{"ISIN": r.isin, "Descrizione": r.description, "Motivo": r.reason}
                 for r in ko]
            ),
            use_container_width=True, hide_index=True,
        )

    # ---------- 5. Download ----------
    st.subheader("Download")
    period_tag = f"{p_start.strftime('%d-%m-%Y')}_{p_end.strftime('%d-%m-%Y')}"
    stem = Path(st.session_state["input_name"]).stem

    d1, d2, d3 = st.columns(3)
    if ok:
        with d1:
            st.download_button(
                "💾 File prezzi (TemplatePrezzi)",
                data=build_output_workbook(results),
                file_name=f"Prezzi_{period_tag}.xlsx",
                mime=XLSX_MIME, type="primary",
            )
    with d2:
        st.download_button(
            "📋 Report esiti (xlsx)",
            data=build_report_workbook(results),
            file_name=f"Report_{period_tag}.xlsx",
            mime=XLSX_MIME,
        )
    with d3:
        try:
            executed = build_executed_workbook(
                st.session_state["input_bytes"], results)
            st.download_button(
                f"📄 {stem}-executed.xlsx",
                data=executed,
                file_name=f"{stem}-executed.xlsx",
                mime=XLSX_MIME,
            )
        except Exception as exc:
            st.error(f"File executed non generabile: {exc}")

    st.caption(
        "Note: le settimane seguono la convenzione della fonte (investing.com: "
        "domenica; Yahoo: lunedì). 'Valuta' tipo USD→EUR indica prezzi convertiti "
        "in EUR col cambio storico settimanale."
    )
