import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import date
import io

# 1. Seite konfigurieren
st.set_page_config(page_title="Vibe Coding: Strategie-Check", layout="wide")
st.title("📊 Meine CC-Strategie vs. Benchmark")

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

# 4. Simulation initialisieren
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
entnommen_bench_brutto_total = 0.0 

# Simulations-Schleife
for i in range(len(df_m) - 1):
    akt_d, fol_d = df_m.index[i], df_m.index[i+1]
    
    snapshot = {
        "Datum": akt_d, "Jahr": akt_d.year,
        "CC_Gesamt": cap_cc + cash_cc, "Depotwert": cap_cc, "Cashpuffer": cash_cc,
        "Entnommen_Total_Netto": entnommen_total_netto, 
        "Bench_Entnahme": cap_bench_entnahme, "Bench_Brutto_Total": entnommen_bench_brutto_total,
        "Bench_Pur": cap_bench_pur,           
        "QYLD_Price": float(df_m["QYLD"].iloc[i]), "QQQ_Price": float(df_m["QQQ"].iloc[i]), 
        "Modus": "CC" if modus_cc else "Index", 
        "Steuern_Monat": 0.0,
        "Bench_Entnahme_Brutto_Monat": 0.0, 
        "Bench_Steuer_Monat": 0.0           
    }

    steuer_monat = 0.0 
    qy_p = (df_m["QYLD"].iloc[i+1] / df_m["QYLD"].iloc[i]) - 1
    qqq_p = (df_m["QQQ"].iloc[i+1] / df_m["QQQ"].iloc[i]) - 1
    bench_p = (df_m[bench_ticker].iloc[i+1] / df_m[bench_ticker].iloc[i]) - 1
    
    peak = df_m["QQQ"][:fol_d].max()
    dd = (peak - df_m["QQQ"].iloc[i+1]) / peak
    
    if dd >= crash_trigger and modus_cc:
        gewinn = cap_cc - einstand_cc
        if gewinn > 0: 
            steuer_fall = gewinn * FREI * STEUER
            cap_cc -= steuer_fall
            steuer_monat += steuer_fall
        modus_cc = False
        events.append({"Datum": fol_d, "Typ": "Verkauf", "Drawdown": dd})
        
    elif dd < 0.05 and not modus_cc:
        modus_cc, einstand_cc = True, cap_cc
        events.append({"Datum": fol_d, "Typ": "Kauf", "Drawdown": dd})

    if modus_cc:
        cap_cc *= (1 + qy_p)
        brutto_div = cap_cc * (div_rendite_pa / 12)
        steuer_div = brutto_div * (FREI * STEUER) 
        netto_div = brutto_div - steuer_div
        cash_cc += netto_div
        steuer_monat += steuer_div
    else: 
        cap_cc *= (1 + qqq_p)

    cash_cc -= wunsch_netto
    entnommen_total_netto += wunsch_netto 
    if cash_cc < 0: 
        cap_cc += cash_cc
        cash_cc = 0.0
    
    cap_bench_pur *= (1 + bench_p)
    cap_bench_entnahme *= (1 + bench_p)
    
    if cap_bench_entnahme > einstand_bench:
        gewinn_quote = (cap_bench_entnahme - einstand_bench) / cap_bench_entnahme
    else:
        gewinn_quote = 0.0
        
    eff_steuer_quote = gewinn_quote * FREI * STEUER
    brutto_entnahme = wunsch_netto / (1 - eff_steuer_quote)
    bench_steuer = brutto_entnahme - wunsch_netto
    
    cap_before = cap_bench_entnahme
    cap_bench_entnahme -= brutto_entnahme
    entnommen_bench_brutto_total += brutto_entnahme
    
    if cap_before > 0:
        verkaufs_quote = brutto_entnahme / cap_before
        einstand_bench *= (1 - verkaufs_quote)

    snapshot["Steuern_Monat"] = steuer_monat
    snapshot["Bench_Entnahme_Brutto_Monat"] = brutto_entnahme
    snapshot["Bench_Steuer_Monat"] = bench_steuer
    
    history.append(snapshot)

results = pd.DataFrame(history)

# 5. Metriken & Fazit
st.divider()

puffer_leer_df = results[results["Cashpuffer"] == 0]
if not puffer_leer_df.empty:
    leer_datum = puffer_leer_df.iloc[0]["Datum"].strftime("%B %Y")
    st.error(f"🚨 **Achtung:** Dein Cash-Puffer war im **{leer_datum}** komplett aufgebraucht!")
else:
    st.success(f"✅ **Starkes Setup!** Dein Cash-Puffer hat die gesamte Zeit überlebt. Du hast {entnommen_total_netto:,.0f} € entnommen.")

col1, col2, col3, col4 = st.columns(4)
cc_endwert = results["CC_Gesamt"].iloc[-1]
bench_endwert = results["Bench_Entnahme"].iloc[-1]
cash_endwert = results["Cashpuffer"].iloc[-1]

col1.metric("Endwert CC-Strategie", f"{cc_endwert:,.0f} €", f"{cc_endwert - total_kapital:,.0f} €")
col2.metric("Endwert Benchmark", f"{bench_endwert:,.0f} €", f"{bench_endwert - total_kapital:,.0f} €")
col3.metric("Restlicher Cash-Puffer", f"{cash_endwert:,.0f} €", f"{cash_endwert - cash_puffer_start:,.0f} €", delta_color="normal")
col4.metric("Entnommen (Netto)", f"{entnommen_total_netto:,.0f} €")

st.divider()

# 6. Diagramm
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=results["Datum"], y=results["Depotwert"], name="Depotwert (CC)", 
    mode='lines', line=dict(width=0), fillcolor='rgba(31, 119, 180, 0.7)', stackgroup='one', hovertemplate="Depot: %{y:,.0f} €<extra></extra>"
))
fig.add_trace(go.Scatter(
    x=results["Datum"], y=results["Cashpuffer"], name="Cashpuffer", 
    mode='lines', line=dict(width=0), fillcolor='rgba(44, 160, 44, 0.7)', stackgroup='one', hovertemplate="Cash: %{y:,.0f} €<extra></extra>"
))
fig.add_trace(go.Scatter(
    x=results["Datum"], y=results["Bench_Entnahme"], name=f"Benchmark ({wahl_name}) MIT Entnahme", 
    line=dict(width=3, dash='dash', color='#ff7f0e'), hovertemplate="Benchmark (mit Entnahme): %{y:,.0f} €<extra></extra>"
))
fig.add_trace(go.Scatter(
    x=results["Datum"], y=results["Bench_Pur"], name=f"Benchmark ({wahl_name}) OHNE Entnahme", 
    line=dict(width=2, dash='dot', color='#7f7f7f'), hovertemplate="Benchmark (ohne Entnahme): %{y:,.0f} €<extra></extra>"
))

for ev in events:
    color = "red" if ev["Typ"] == "Verkauf" else "green"
    fig.add_vline(x=ev["Datum"], line_width=1.5, line_dash="dash", line_color=color)

fig.update_layout(margin=dict(t=40), hovermode="x unified")
st.plotly_chart(fig, width='stretch')

# 7. Tabelle
st.subheader("📅 Jährliche Details (Stand 01.01.)")

yearly = results.groupby("Jahr").first().reset_index()
yearly_taxes = results.groupby("Jahr")["Steuern_Monat"].sum().reset_index()

yearly["Gezahlte_Steuern"] = yearly_taxes["Steuern_Monat"]
yearly["CC_Kurs_pa"] = yearly["QYLD_Price"].pct_change().shift(-1) * 100
yearly["Nasdaq_Kurs_pa"] = yearly["QQQ_Price"].pct_change().shift(-1) * 100
yearly["Bench_Entnahme_Endwert"] = results.groupby("Jahr")["Bench_Entnahme"].first().values

def color_returns(val):
    if pd.isna(val): return ''
    return f'background-color: {"#ff9999" if val < 0 else "#99ff99"}; color: black'

def color_modus(val):
    return 'background-color: #ffcccc; color: black; font-weight: bold' if val == 'Index' else 'background-color: #e6f2ff; color: black'

styled_df = (
    yearly[["Jahr", "CC_Gesamt", "Depotwert", "Cashpuffer", "Gezahlte_Steuern", "Bench_Entnahme_Endwert", "CC_Kurs_pa", "Nasdaq_Kurs_pa", "Modus"]]
    .style.format({
        "CC_Gesamt": "{:,.2f} €", "Depotwert": "{:,.2f} €", "Cashpuffer": "{:,.2f} €",
        "Gezahlte_Steuern": "{:,.2f} €", "Bench_Entnahme_Endwert": "{:,.2f} €",
        "CC_Kurs_pa": "{:,.2f} %", "Nasdaq_Kurs_pa": "{:,.2f} %"
    })
    .map(color_returns, subset=["CC_Kurs_pa", "Nasdaq_Kurs_pa"])
    .map(color_modus, subset=["Modus"])
)

st.dataframe(styled_df, width='stretch')

# 8. Excel Download
st.divider()
st.subheader("📥 Berechnungen als Excel herunterladen")

df_cc = results[["Datum", "Depotwert", "Cashpuffer", "CC_Gesamt", "Steuern_Monat", "Modus"]].copy()
df_cc["Datum"] = df_cc["Datum"].dt.date 
df_cc.rename(columns={
    "CC_Gesamt": "Gesamtwert_CC", 
    "Steuern_Monat": "Gezahlte_Steuern_Monat"
}, inplace=True)

df_bench = results[["Datum", "Bench_Entnahme", "Bench_Entnahme_Brutto_Monat", "Bench_Steuer_Monat", "Entnommen_Total_Netto"]].copy()
df_bench["Datum"] = df_bench["Datum"].dt.date
df_bench["Netto_Entnahme_Monat"] = wunsch_netto 
df_bench.rename(columns={
    "Bench_Entnahme": "Depotwert_Benchmark",
    "Bench_Entnahme_Brutto_Monat": "Brutto_Verkauf_Monat",
    "Bench_Steuer_Monat": "Gezahlte_Steuer_beim_Verkauf"
}, inplace=True)

df_bench = df_bench[["Datum", "Depotwert_Benchmark", "Netto_Entnahme_Monat", "Gezahlte_Steuer_beim_Verkauf", "Brutto_Verkauf_Monat", "Entnommen_Total_Netto"]]

buffer = io.BytesIO()

with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
    df_cc.to_excel(writer, index=False, sheet_name='CC_Strategie_Monatlich')
    df_bench.to_excel(writer, index=False, sheet_name='Benchmark_Entnahme_Monatlich')

st.download_button(
    label="📊 Excel-Datei generieren & laden",
    data=buffer.getvalue(),
    file_name="Backtest_Ergebnisse_Monatlich.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

# 9. README Expander (Neu hinzugefügt)
st.divider()
with st.expander("📖 README: Erklärung & Wirkungsweise der Strategie"):
    st.markdown("""
    ### 📊 CC-Strategie vs. Benchmark Simulator

    Dieses interaktive Dashboard dient dem Backtesten und Vergleichen einer **Covered Call (CC) ETF-Strategie** mit einer klassischen **Buy & Hold (Benchmark) Strategie** während der Entsparphase. 
    Das Tool legt besonderen Wert auf eine **100 % realistische steuerliche Betrachtung** (deutsches Steuerrecht inkl. Teilfreistellung) und beinhaltet einen dynamischen **Crash-Schutz** für den CC-ETF.

    ---

    #### ✨ Kernfunktionen

    * **Dynamischer Backtest:** Ziehe reale historische Kursdaten via Yahoo Finance und teste beliebige Zeiträume ab 2015.
    * **Interaktives Dashboard:** Passe Parameter wie Startkapital, monatliche Entnahme, Cash-Puffer und Dividendenrendite in Echtzeit an.
    * **Realistische Steuersimulation:** Das System berechnet die deutsche Kapitalertragsteuer (26,375 %) unter Berücksichtigung der 30 % Teilfreistellung für Aktien-ETFs (Faktor 0,7) – sowohl für Dividenden als auch für Kursgewinne beim Anteilsverkauf.
    * **Intelligenter Crash-Schutz:** Ein Algorithmus, der bei einem einstellbaren Drawdown automatisch vom CC-ETF in den Nasdaq 100 flüchtet und erst bei Markterholung zurückkehrt.
    * **Visualisierung:** Gestapelte Flächendiagramme (Depot + Puffer) und Vergleichslinien zeigen dir auf einen Blick, wo dein Kapital steckt.
    * **Excel-Export:** Lade die exakten Berechnungen (Steuern, Entnahmen, Depotwerte) aufgeschlüsselt nach Monaten in zwei separaten Tabellenblättern herunter.

    ---

    #### ⚖️ Die Wirkungsweise des Vergleichs (Das Herzstück)

    Die App vergleicht nicht einfach nur zwei Linien im Chart, sondern simuliert zwei völlig unterschiedliche finanzielle "Lebensentwürfe" in der Entnahmephase. 

    **1. Die CC-Strategie (Die "Goldene Gans")**
    Diese Strategie zielt auf maximalen Cashflow ab, um die Substanz (die ETF-Anteile) nicht antasten zu müssen.
    * **Das Setup:** Dein Kapital wird aufgeteilt in ein ETF-Depot (z.B. QYLD) und einen risikoarmen Cash-Puffer (Tagesgeld).
    * **Der Motor:** Der ETF schüttet jeden Monat eine hohe Dividende aus. Nach Abzug der Steuern fließt dieses Geld in deinen Cash-Puffer.
    * **Die Entnahme:** Deine monatlichen Lebenshaltungskosten nimmst du **ausschließlich** aus dem Cash-Puffer. Die Anzahl deiner ETF-Anteile bleibt erhalten. Nur wenn der Puffer auf 0 € fällt, führt das System Notverkäufe durch.

    **2. Die Benchmark-Strategie (Der "Substanz-Verzehr")**
    Dies ist der klassische Buy & Hold Ansatz (z.B. S&P 500 oder MSCI World) ohne nennenswerte Dividenden.
    * **Das Setup:** Dein gesamtes Kapital liegt zu 100 % im Index-ETF.
    * **Die Entnahme:** Um deine monatliche Auszahlung zu erhalten, **musst du jeden Monat ETF-Anteile verkaufen**.
    * **Der Steuer-Effekt (Brutto vs. Netto):** Wenn du z.B. 6.000 € auf dem Konto brauchst, berechnet der Code exakt, wie viel Prozent deines Portfolios aus Kursgewinnen bestehen. Er entnimmt einen **höheren Brutto-Betrag**, um die Steuern zu decken. 
    * **Der "Historische Gewinn":** Da ein solches Depot meist über Jahre bespart wurde, kannst du in der Seitenleiste einstellen, wie viel Prozent des Startkapitals bereits aus steuerpflichtigen Kursgewinnen bestehen.

    ---

    #### 🛡️ Der Crash-Schutz (Drawdown-Logik)

    Da Covered Call ETFs in extremen Crashs stark fallen, sich danach aber durch die gecappten Kursgewinne kaum erholen, besitzt die CC-Strategie eine "Notbremse".

    1. **Beobachtung:** Das System misst monatlich den Abstand des Marktes (Nasdaq 100) zu seinem letzten Allzeithoch (Drawdown).
    2. **Flucht (Rote Linie):** Sobald der Drawdown deinen Schwellenwert erreicht, wird der CC-ETF fiktiv komplett verkauft und in den puren Nasdaq 100 umgeschichtet. So nimmst du die steile Erholungsphase zu 100 % mit.
    3. **Rückkehr (Grüne Linie):** Sobald sich der Markt erholt hat und der Drawdown geringer als 5 % ist, schichtet das System das Kapital zurück in den CC-ETF, um die Dividenden-Ernte fortzusetzen.
    """)
