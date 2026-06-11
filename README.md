# PerixMonitor Price — Lettura storico prezzi

Applicazione web locale (Streamlit) che legge una lista di asset da Excel e
recupera i prezzi storici **settimanali in EUR** da Yahoo Finance, producendo
un file Excel nel formato `TemplatePrezzi.xlsx`.

## Requisiti

Python 3.10 o superiore installato su Windows (https://www.python.org/downloads/,
spuntare "Add Python to PATH" durante l'installazione).

## Avvio

Doppio clic su `avvia_app.bat`. Al primo avvio installa le librerie necessarie,
poi apre l'applicazione nel browser (indirizzo http://localhost:8501).

In alternativa, da terminale nella cartella del progetto:

    python -m pip install -r requirements.txt
    python -m streamlit run app.py

## Uso

1. Carica il file Excel con la lista asset (colonne obbligatorie: `ISIN`,
   `Descrizione Asset` — stesso formato di `Lista_All_Assets.xlsx`).
2. Inserisci data inizio e data fine (formato gg/mm/aaaa).
3. Premi **Lettura storico prezzi**.
4. Al termine scarica il file risultato con il pulsante dedicato.

## Fonti dati e logica di selezione

Per ogni ISIN l'app interroga due fonti in cascata:

1. **investing.com** (fonte primaria, API interna del sito): ricerca per
   ISIN, preferenza Borsa di Milano poi borse dell'area Euro, verifica
   che la valuta sia EUR (letta dalla pagina dello strumento), storico
   settimanale dall'endpoint chart. Copre BTP, fondi, ETF.
2. **fondidoc.it** (FIDA — seconda fonte, specializzata in fondi ed ETF
   distribuiti in Italia): ricerca ISIN → codice interno, serie NAV
   giornaliera già convertita in EUR dal server, ricampionata su base
   settimanale (ultimo NAV della settimana, etichetta = lunedì).
3. **Yahoo Finance** (ultimo fallback): ricerca per ISIN più varianti
   di borsa (`.MI`, `.DE`, `.AS`, `.PA`, `.F`).

**Conversione valuta**: le quotazioni EUR native sono sempre preferite; se
uno strumento è disponibile solo in altra valuta (USD, GBP, CHF, ...), i
prezzi vengono convertiti automaticamente in EUR con il cambio storico
settimanale (fonte Yahoo, fallback investing.com), allineato per data.
Nella colonna "Valuta" del report questi casi appaiono come "USD→EUR".
I prezzi in pence britannici (GBp) vengono prima divisi per 100.

Se tutte le fonti falliscono, l'asset finisce nel foglio "Non Recuperati"
con i motivi di entrambe le fonti, separati da `||`.

## File generati

- `Prezzi_<periodo>.xlsx` — prezzi in formato TemplatePrezzi (+ foglio
  "Non Recuperati");
- `Report_<periodo>.xlsx` — esiti in due fogli: "Recuperati" (con simbolo,
  borsa, valuta, fonte) e "Non Recuperati" (con motivo);
- `<nome input>-executed.xlsx` — copia del file di input con tre colonne
  aggiunte: "Price Recovered" (Yes/No), "Trade Site", "Source".

## Formato di output

File `.xlsx` con foglio `Sheet1` e colonne `ISIN`, `Descrizione Asset`,
`Data` (formato gg/mm/aaaa), `Prezzo Corrente (EUR)`. La descrizione è quella
del file di input. Il prezzo è la chiusura settimanale ("Price"/Close).
Gli asset non recuperati sono elencati nel foglio `Non Recuperati` con il motivo.

## Limiti noti (leggere prima dell'uso)

- **API non ufficiale**: l'API interna di investing.com non è documentata
  né garantita; può smettere di funzionare se il sito cambia, e l'uso
  automatizzato non è previsto dai loro Terms of Service. L'app fa una
  pausa tra le richieste per non sovraccaricare il servizio.
- **Strumenti non coperti**: certificati (Vontobel `DE000VJ...`,
  BNP `NLBNPIT...`/`XS...`) e prodotti non quotati pubblicamente
  (es. ELTIF) non sono presenti su nessuna delle due fonti e vanno
  gestiti manualmente.
- **Convenzione data settimanale**: le etichette delle settimane seguono
  la fonte: investing.com usa tipicamente la domenica, Yahoo il lunedì.
  Le date tra le due fonti possono quindi differire di un giorno.
- **Fondi multi-classe**: per ISIN con più classi di quota l'app verifica
  la valuta sulla pagina dello strumento e accetta solo EUR; classi solo
  in USD vengono scartate (nessuna conversione di cambio automatica).
- L'app richiede connessione internet.

## File del progetto

- `app.py` — interfaccia web (Streamlit)
- `price_fetcher.py` — orchestrazione: investing.com primario, Yahoo fallback
- `investing_fetcher.py` — accesso all'API interna di investing.com
- `fondidoc_fetcher.py` — accesso ai NAV di fondidoc.it (FIDA)
- `fx.py` — conversione valuta→EUR con cambi storici settimanali
- `exports.py` — report esiti xlsx e file -executed.xlsx
- `requirements.txt` — librerie Python necessarie
- `avvia_app.bat` — avvio rapido per Windows
