import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import date
import io

# 1. Seite konfigurieren
st.set_page_config(page_title="Vibe Coding: Strategie-Check Pro", layout="wide")
st.title("📊 Strategie-Vergleich: CC vs. Benchmark")

# 2. Sidebar für die Steuerung
with st.sidebar:
    st.header("Start-Einstellungen")
    start_datum = st.date_input("Start-Datum", date(2015, 1, 1))
    total_kapital = st.number_input("Gesamtkapital (€)", value=800000)
    cash_puffer_start = st.number_input("Start-Cash-Puffer (€)", value=100000) 
    
    st.header("Vergleich")
    benchmarks = {"Nasdaq 100": "QQQ", "S&P 500": "SPY", "MSCI World": "IWDA.AS"}
    wahl_name = st.selectbox("Benchmark-Linie:", list(benchmarks.keys()))
    bench_ticker = benchmarks[wahl_name]
    bench_gewinn_start = st.slider("Bereits enthaltener Gewinn im Benchmark (%)", 0, 100, 0) / 100

    st.header("Entnahme & Logik")
    wunsch_netto = st.number_input("Monatliche Auszahlung (€)", value=6000)
    div_rendite_pa = st.number_input("Dividende p.a. (%)", value=10.0) / 100
    crash_trigger = st.slider("Crash-Schutz bei Drawdown (%)", 10, 40, 20) / 100

# 3. Daten laden
@st.cache_data
def get_data(start_date, ticker):
    data = yf.download([ticker, "QQQ", "QYLD"], start=start_date, auto_adjust=True)
    if isinstance(data.columns, pd.MultiIndex): 
        data = data["Close"]
    return data.ffill()

df_raw = get_data(start_datum, bench_ticker)
df_m = df_raw.resample("ME").last().ffill()

# 4. Simulation
cap_cc = float(total_kapital - cash_puffer_start)
cash_cc = float(cash_puffer_start)
cap_bench_entnahme = float(total_kapital)
cap_bench_pur = float(total_kapital)      

einstand_cc = cap_cc
einstand_bench = cap_bench_entnahme * (1 - bench_gewinn_start)

modus_cc = True
STEUER = 0.26375 
FREI = 0.70      
history = []
events = []
entnommen_total_netto = 0.0

for i in range(len(df_m) - 1):
    akt_d, fol_d = df_m.index[i], df_m.index[i+1]
    
    # Snapshot VOR den monatlichen Bewegungen
    snapshot = {
        "Datum": akt_d, "Jahr": akt_d.year,
        "CC_Gesamt": cap_cc + cash_cc, "Depotwert_CC": cap_cc, "Cashpuffer": cash_cc,
        "Bench_Entnahme": cap_bench_entnahme, "Bench_Pur": cap_bench_pur,
        "Modus": "CC" if modus_cc else "Index", "Steuern_Monat": 0.0,
        "QYLD_Price": float(df_m["QYLD"].iloc[i]), "QQQ_Price": float(df_m["QQQ"].iloc[i])
    }

    qy_p = (df_m["QYLD"].iloc[i+1] / df_m["QYLD"].iloc[i]) - 1
    qqq_p = (df_m["QQQ"].iloc[i+1] / df_m["QQQ"].iloc[i]) - 1
    bench_p = (df_m[bench_ticker].iloc[i+1] / df_m[bench_ticker].iloc[i]) - 1
    
    peak = df_m["QQQ"][:fol_d].max()
    dd = (peak - df_m["QQQ"].iloc[i+1]) / peak
    
    # Crash-Logik
    if dd >= crash_trigger and modus_cc:
        gewinn = cap_cc - einstand_cc
        if gewinn > 0: cap_cc -= (gewinn * FREI * STEUER)
        modus_cc = False
        events.append({"Datum": fol_d, "Typ": "Verkauf", "Drawdown": dd})
    elif dd < 0.05 and not modus_cc:
        modus_cc, einstand_cc = True, cap_cc
        events.append({"Datum": fol_d, "Typ": "Kauf", "Drawdown": dd})

    # Performance CC
    if modus_cc:
        cap_cc *= (1 + qy_p)
        brutto_div = cap_cc * (div_rendite_pa / 12)
        netto_div = brutto_div - (brutto_div * FREI * STEUER)
        cash_cc += netto_div
    else: 
        cap_cc *= (1 + qqq_p)

    # Entnahme CC
    cash_cc -= wunsch_netto
    entnommen_total_netto += wunsch_netto 
    if cash_cc < 0: 
        cap_cc += cash_cc
        cash_cc = 0.0
    
    # Performance Benchmark & Entnahme (Steueroptimiert)
    cap_bench_pur *= (1 + bench_p)
    cap_bench_entnahme *= (1 + bench_p)
    
    g_quote = max(0, (cap_bench_entnahme - einstand_bench) / cap_bench_entnahme) if cap_bench_entnahme > 0 else 0
    eff_st = g_quote * FREI * STEUER
    brutto_v = wunsch_netto / (1 - eff_st)
    
    v_quote = brutto_v / cap_bench_entnahme if cap_bench_entnahme > brutto_v else 1
    einstand_bench *= (1 - v_quote)
    cap_bench_entnahme -= brutto_v
    
    snapshot["Entnommen_Kum"] = entnommen_total_netto
    history.append(snapshot)

results = pd.DataFrame(history)

# 5. UI: Metriken
st.divider()
col1, col2, col3, col4 = st.columns(4)
col1.metric("Endwert CC", f"{results['CC_Gesamt'].iloc[-1]:,.0f} €")
col2.metric("Endwert Benchmark", f"{results['Bench_Entnahme'].iloc[-1]:,.0f} €")
col3.metric("Rest-Puffer", f"{results['Cashpuffer'].iloc[-1]:,.0f} €")
col4.metric("Gesamt Entnommen", f"{entnommen_total_netto:,.0f} €")

# 6. Grafik
st.divider()
fig = go.Figure()

# Flächen für CC
fig.add_trace(go.Scatter(
    x=results["Datum"], y=results["Depotwert_CC"], name="CC Depot",
    stackgroup='one', fillcolor='rgba(31, 119, 180, 0.4)', line=dict(width=0.5, color='#1f77b4'),
    customdata=results[["CC_Gesamt", "Cashpuffer", "Entnommen_Kum"]],
    hovertemplate="<b>CC Strategie</b><br>Gesamt: %{customdata[0]:,.0f} €<br>Depot: %{y:,.0f} €<br>Cash: %{customdata[1]:,.0f} €<br>Entnommen: %{customdata[2]:,.0f} €<extra></extra>"
))
fig.add_trace(go.Scatter(
    x=results["Datum"], y=results["Cashpuffer"], name="CC Puffer",
    stackgroup='one', fillcolor='rgba(44, 160, 44, 0.4)', line=dict(width=0.5, color='#2ca02c'),
    hovertemplate="Puffer-Anteil: %{y:,.0f} €<extra></extra>"
))

# Benchmark Linien
fig.add_trace(go.Scatter(
    x=results["Datum"], y=results["Bench_Entnahme"], name="Benchmark (MIT Entnahme)",
    line=dict(color='#ff7f0e', width=3, dash='dash'),
    hovertemplate="Benchmark (mit Entnahme): %{y:,.0f} €<extra></extra>"
))
fig.add_trace(go.Scatter(
    x=results["Datum"], y=results["Bench_Pur"], name="Benchmark (OHNE Entnahme)",
    line=dict(color='#7f7f7f', width=1.5, dash='dot'),
    hovertemplate="Benchmark (ohne Entnahme): %{y:,.0f} €<extra></extra>"
))

# Vertikale Linien
for ev in events:
    color = "red" if ev["Typ"] == "Verkauf" else "green"
    fig.add_vline(x=ev["Datum"], line_width=2, line_dash="dash", line_color=color)

fig.update_layout(hovermode="x unified", legend=dict(orientation="h", y=1.1), margin=dict(t=80))
st.plotly_chart(fig, use_container_width=True)

# 7. Tabelle & Excel
st.subheader("📅 Historische Daten")
st.dataframe(results.tail(12), use_container_width=True)

buffer = io.BytesIO()
with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
    results.to_excel(writer, index=False, sheet_name='Backtest_Daten')
st.download_button("📥 Excel Download", buffer.getvalue(), "Finanz-Check.xlsx")

# 8. README Expander
with st.expander("📖 Strategie-Erklärung (README)"):
    st.markdown("""
    ### Wirkungsweise des Vergleichs
    * **CC-Strategie:** Verwendet Dividenden (Cashflow), um Entnahmen zu decken. Die Substanz bleibt unangetastet, solange Cash vorhanden ist.
    * **Benchmark MIT Entnahme:** Simuliert den Verkauf von Anteilen inkl. Steuerlast (Brutto-Verkauf für Netto-Auszahlung).
    * **Benchmark OHNE Entnahme:** Zeigt die reine Marktrendite ohne jegliche Kapitalentnahme.
    * **Crash-Schutz:** Reagiert auf Markteinbrüche, um das Kapital in Erholungsphasen im Nasdaq-Index zu halten.
    """)
