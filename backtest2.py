import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import date
import io

# 1. Seite konfigurieren
st.set_page_config(page_title="Strategie-Check Pro", layout="wide")
st.title("📊 Strategie-Check: CC-Strategie vs. Benchmark")

# 2. Sidebar
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
cap_cc, cash_cc = float(total_kapital - cash_puffer_start), float(cash_puffer_start)
cap_bench_e, cap_bench_p = float(total_kapital), float(total_kapital)
einstand_cc, einstand_bench = cap_cc, float(total_kapital) * (1 - bench_gewinn_start)
modus_cc, history, events, entnommen_n = True, [], [], 0.0
STEUER, FREI = 0.26375, 0.70

for i in range(len(df_m) - 1):
    akt_d, fol_d = df_m.index[i], df_m.index[i+1]
    snapshot = {
        "Datum": akt_d, "Jahr": akt_d.year, "CC_Gesamt": cap_cc + cash_cc, 
        "Depotwert_CC": cap_cc, "Cashpuffer": cash_cc, "Bench_Entnahme": cap_bench_e, 
        "Bench_Pur": cap_bench_p, "Modus": "CC" if modus_cc else "Index"
    }
    
    qy_p = (df_m["QYLD"].iloc[i+1] / df_m["QYLD"].iloc[i]) - 1
    qqq_p = (df_m["QQQ"].iloc[i+1] / df_m["QQQ"].iloc[i]) - 1
    bench_p = (df_m[bench_ticker].iloc[i+1] / df_m[bench_ticker].iloc[i]) - 1
    
    peak = df_m["QQQ"][:fol_d].max()
    dd = (peak - df_m["QQQ"].iloc[i+1]) / peak
    
    if dd >= crash_trigger and modus_cc:
        g = cap_cc - einstand_cc
        if g > 0: cap_cc -= (g * FREI * STEUER)
        modus_cc = False
        events.append({"Datum": fol_d, "Typ": "Verkauf"})
    elif dd < 0.05 and not modus_cc:
        modus_cc, einstand_cc = True, cap_cc
        events.append({"Datum": fol_d, "Typ": "Kauf"})

    if modus_cc:
        cap_cc *= (1 + qy_p)
        div = (cap_cc * (div_rendite_pa / 12)) * (1 - (FREI * STEUER))
        cash_cc += div
    else: cap_cc *= (1 + qqq_p)

    cash_cc -= wunsch_netto
    entnommen_n += wunsch_netto
    if cash_cc < 0: cap_cc += cash_cc; cash_cc = 0.0
    
    cap_bench_p *= (1 + bench_p)
    cap_bench_e *= (1 + bench_p)
    g_q = max(0, (cap_bench_e - einstand_bench) / cap_bench_e) if cap_bench_e > 0 else 0
    brutto_v = wunsch_netto / (1 - (g_q * FREI * STEUER))
    v_q = brutto_v / cap_bench_e if cap_bench_e > brutto_v else 1
    einstand_bench *= (1 - v_q)
    cap_bench_e -= brutto_v
    
    snapshot["Entnommen_Kum"] = entnommen_n
    history.append(snapshot)

results = pd.DataFrame(history)

# --- Grafik ---
st.divider()
fig = go.Figure()

fig.add_trace(go.Scatter(
    x=results["Datum"], y=results["Depotwert_CC"], name="Depotwert (CC)",
    stackgroup='one', fillcolor='rgba(31, 119, 180, 0.6)', line=dict(width=0.5, color='#1f77b4'),
    customdata=results[["CC_Gesamt", "Cashpuffer", "Entnommen_Kum"]],
    hovertemplate="<b>CC Strategie</b><br>Gesamt: %{customdata[0]:,.0f} €<br>Depot: %{y:,.0f} €<br>Cash: %{customdata[1]:,.0f} €<extra></extra>"
))
fig.add_trace(go.Scatter(
    x=results["Datum"], y=results["Cashpuffer"], name="Cashpuffer",
    stackgroup='one', fillcolor='rgba(44, 160, 44, 0.6)', line=dict(width=0.5, color='#2ca02c'),
    hovertemplate="Cash Anteil: %{y:,.0f} €<extra></extra>"
))

fig.add_trace(go.Scatter(
    x=results["Datum"], y=results["Bench_Entnahme"], name="Benchmark MIT Entnahme",
    line=dict(color='#ff7f0e', width=3, dash='dash'),
    hovertemplate="Benchmark (mit Entnahme): %{y:,.0f} €<extra></extra>"
))
fig.add_trace(go.Scatter(
    x=results["Datum"], y=results["Bench_Pur"], name="Benchmark OHNE Entnahme",
    line=dict(color='#7f7f7f', width=2, dash='dot'),
    hovertemplate="Benchmark (ohne Entnahme): %{y:,.0f} €<extra></extra>"
))

for ev in events:
    col = "red" if ev["Typ"] == "Verkauf" else "green"
    fig.add_vline(x=ev["Datum"], line_width=2, line_dash="dash", line_color=col)
    fig.add_annotation(
        x=ev["Datum"], y=1.05, yref="paper", 
        text=f"<b>{ev['Typ']}</b>", showarrow=False, font=dict(color=col, size=12)
    )

fig.update_layout(hovermode="x unified", legend=dict(orientation="h", y=1.15), margin=dict(t=80))
st.plotly_chart(fig, use_container_width=True)

# Tabelle & Excel
st.subheader("📅 Detail-Daten")
st.dataframe(results.tail(12), use_container_width=True)
buffer = io.BytesIO()
with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
    results.to_excel(writer, index=False, sheet_name='Backtest')
st.download_button("📥 Excel Download", buffer.getvalue(), "Finanz-Check.xlsx")

# --- Ausführliches README ---
with st.expander("📖 README: Erklärung & Wirkungsweise der Strategie"):
    st.markdown("""
    ### 📊 CC-Strategie vs. Benchmark Simulator

    Dieses interaktive Dashboard dient dem Backtesten und Vergleichen einer **Covered Call (CC) ETF-Strategie** mit einer klassischen **Buy & Hold (Benchmark) Strategie** während der Entsparphase. 
    Das Tool legt besonderen Wert auf eine **100 % realistische steuerliche Betrachtung** (deutsches Steuerrecht inkl. Teilfreistellung) und beinhaltet einen dynamischen **Crash-Schutz** für den CC-ETF.

    ---

    #### ✨ Kernfunktionen

    * **Dynamischer Backtest:** Nutzt reale historische Kursdaten via Yahoo Finance (`yfinance`) ab 2015.
    * **Interaktive Sidebar:** Passe Kapital, Entnahme, Puffer und Dividende in Echtzeit an.
    * **Realistische Steuersimulation:** Berechnet Kapitalertragsteuer (26,375 %) inkl. 30 % Teilfreistellung (Faktor 0,7) für Dividenden und Kursgewinne.
    * **Intelligenter Crash-Schutz:** Wechselt bei einstellbarem Drawdown automatisch vom CC-ETF in den Nasdaq 100 und kehrt bei Erholung zurück.
    * **Visualisierung:** Gestapelte Flächen (Depot + Puffer) und Benchmark-Linien für maximale Transparenz.

    ---

    #### ⚖️ Die Wirkungsweise des Vergleichs

    **1. Die CC-Strategie (Die "Goldene Gans")**
    Zielt auf maximalen Cashflow ab, um die Substanz nicht antasten zu müssen.
    * **Setup:** Kapital wird in ETF-Depot und Cash-Puffer aufgeteilt.
    * **Motor:** Der ETF schüttet hohe Dividenden aus, die (netto) den Puffer füllen.
    * **Entnahme:** Kosten werden ausschließlich aus dem Cash-Puffer gedeckt. Die Anteilszahl bleibt konstant, solange der Puffer > 0 ist.

    **2. Die Benchmark-Strategie (Der "Substanz-Verzehr")**
    Klassischer Buy & Hold Ansatz (z.B. MSCI World) ohne hohe Ausschüttungen.
    * **Setup:** Gesamtkapital liegt im Index-ETF.
    * **Entnahme:** Monatlicher Verkauf von Anteilen.
    * **Steuer-Effekt:** Der Code berechnet den Gewinnanteil und entnimmt einen höheren Brutto-Betrag, um die Steuerlast zu decken und das gewünschte Netto auszuzahlen.
    * **Historischer Gewinn:** Ermöglicht die Simulation eines bereits im Plus befindlichen Depots zum Startzeitpunkt.

    ---

    #### 🛡️ Der Crash-Schutz (Drawdown-Logik)

    Covered Call ETFs fallen in Crashs stark, erholen sich aber langsamer. Der Algorithmus fungiert als Notbremse:
    1. **Beobachtung:** Misst monatlich den Drawdown des Nasdaq 100 zum Allzeithoch.
    2. **Flucht (Rote Linie):** Bei Erreichen des Schwellenwerts (z.B. -20 %) wird in den puren Nasdaq (QQQ) gewechselt.
    3. **Rückkehr (Grüne Linie):** Bei Erholung (Drawdown < 5 %) erfolgt der Rückwechsel in den CC-ETF.
    """)
