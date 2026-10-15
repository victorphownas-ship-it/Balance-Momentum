import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
from streamlit_autorefresh import st_autorefresh

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Monitor de Reversiones 1H",
    layout="wide",
    page_icon="📊",
    initial_sidebar_state="expanded"
)

# Recarga automática cada 5 minutos (300,000 ms)
st_autorefresh(interval=300000, key="datarefresh")

# --- BARRA LATERAL: PARÁMETROS Y CREDENCIALES ---
st.sidebar.title("⚙️ Parámetros del Monitor")

TICKER = st.sidebar.selectbox(
    "Selecciona el Activo",
    ["EURUSD=X", "GC=F", "NQ=F", "ES=F"],
    index=0
)

WINDOW = st.sidebar.number_input("Ventana SMA", min_value=10, max_value=200, value=50, step=5)
Z_THRESHOLD = st.sidebar.number_input("Umbral Z-Score", min_value=1.0, max_value=4.0, value=2.0, step=0.1)

st.sidebar.markdown("---")
st.sidebar.title("📲 Alertas Telegram")
TOKEN = st.sidebar.text_input("Bot Token", value="8284532743:AAEYEn0NO-Be28Sw6vuMOTfZGHc3kTZnwwA", type="password")
CHAT_ID = st.sidebar.text_input("Chat ID", value="1608909365")

def enviar_telegram(mensaje):
    if not TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {'chat_id': CHAT_ID, 'text': mensaje, 'parse_mode': 'Markdown'}
    try:
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        st.sidebar.error(f"Error Telegram: {e}")

# --- DESCARGA Y CÁLCULOS ---
@st.cache_data(ttl=240)
def cargar_datos(ticker):
    data = yf.download(ticker, period="30d", interval="1h", progress=False, auto_adjust=True)
    if data.empty:
        return None
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    
    if data.index.tz is None:
        data.index = data.index.tz_localize('UTC').tz_convert('America/New_York')
    else:
        data.index = data.index.tz_convert('America/New_York')
        
    return data

data = cargar_datos(TICKER)

if data is None:
    st.error("No se pudieron cargar los datos del activo seleccionado.")
    st.stop()

# Cálculos estadísticos
close_prices = data['Close']
ma = close_prices.rolling(window=WINDOW).mean()
std = close_prices.rolling(window=WINDOW).std()

data['Z_Score'] = (close_prices - ma) / std
slope = ma.diff(3)

ultimo_z = data['Z_Score'].iloc[-1]
precio_actual = close_prices.iloc[-1]
hora_ny = data.index[-1].strftime('%Y-%m-%d %H:%M')

# --- DETECCIÓN DE BALANCE ---
rangos_balance = []
en_balance = False
inicio_idx = None

for idx, row in data.iterrows():
    if pd.isna(row['Z_Score']):
        continue

    es_balance = abs(row['Z_Score']) <= 1.0

    if es_balance and not en_balance:
        en_balance = True
        inicio_idx = idx
    elif not es_balance and en_balance:
        en_balance = False
        fin_idx = idx
        periodo = data.loc[inicio_idx:fin_idx]
        rangos_balance.append({
            'inicio': inicio_idx,
            'fin': fin_idx,
            'max': periodo['High'].max(),
            'min': periodo['Low'].min()
        })

if en_balance:
    fin_idx = data.index[-1]
    periodo = data.loc[inicio_idx:fin_idx]
    rangos_balance.append({
        'inicio': inicio_idx,
        'fin': fin_idx,
        'max': periodo['High'].max(),
        'min': periodo['Low'].min(),
        'activo': True
    })

# --- DETERMINACIÓN DEL RÉGIMEN ---
if ultimo_z >= Z_THRESHOLD:
    regimen = "🔴 TRAMPA ALCISTA (Buscando Shorts)"
    guidance = "Precio extremadamente desviado al alza. Posible barrido de liquidez. Esperar rechazo."
    badge_type = "error"
elif ultimo_z <= -Z_THRESHOLD:
    regimen = "🟢 TRAMPA BAJISTA (Buscando Longs)"
    guidance = "Precio extremadamente desviado a la baja. Posible barrido de liquidez. Esperar rechazo."
    badge_type = "success"
elif abs(ultimo_z) <= 1.0:
    regimen = "⚖️ ZONA DE BALANCE"
    guidance = "Mercado en equilibrio orbitando su media. No operar quiebres."
    badge_type = "info"
else:
    regimen = "Transición Direccional"
    guidance = "El precio se aleja de la media, pero sin llegar a extremos manipulables."
    badge_type = "warning"

# Gestión de Estado de Notificaciones Telegram
if 'ultimo_regimen' not in st.session_state:
    st.session_state.ultimo_regimen = ""

if regimen != st.session_state.ultimo_regimen:
    msg_tele = (f"⚠️ *NUEVO RÉGIMEN ESTRUCTURAL (1H)*\n\n"
                f"📊 *Activo:* {TICKER}\n"
                f"💵 *Precio:* `{precio_actual:.5f}`\n"
                f"🎯 *Estado:* {regimen}\n"
                f"📐 *Z-Score:* `{ultimo_z:.2f}` (Límite: ±{Z_THRESHOLD})\n"
                f"🕒 *Hora:* {hora_ny} NY")
    enviar_telegram(msg_tele)
    st.session_state.ultimo_regimen = regimen

# --- INTERFAZ PRINCIPAL ---
st.title(f"📊 Monitor de Reversiones 1H — {TICKER}")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Precio Actual", f"{precio_actual:.5f}")
col2.metric("Z-Score", f"{ultimo_z:.2f}")
col3.metric("Límite Z", f"±{Z_THRESHOLD}")
col4.metric("Hora (NY)", data.index[-1].strftime('%H:%M'))

if badge_type == "error":
    st.error(f"**Régimen Actual:** {regimen} — {guidance}")
elif badge_type == "success":
    st.success(f"**Régimen Actual:** {regimen} — {guidance}")
elif badge_type == "info":
    st.info(f"**Régimen Actual:** {regimen} — {guidance}")
else:
    st.warning(f"**Régimen Actual:** {regimen} — {guidance}")

# --- GRÁFICO PLOTLY ---
fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                    vertical_spacing=0.03, row_heights=[0.7, 0.3])

fig.add_trace(go.Scatter(x=data.index, y=close_prices, name='Precio',
                         line=dict(color='#d1d4dc', width=1.5)), row=1, col=1)
fig.add_trace(go.Scatter(x=data.index, y=ma, name=f'Media ({WINDOW})',
                         line=dict(color='orange', width=1.5, dash='dot')), row=1, col=1)

for r in rangos_balance:
    fig.add_shape(
        type="rect",
        x0=r['inicio'], x1=r['fin'],
        y0=r['min'], y1=r['max'],
        line=dict(color="cyan", width=1.5, dash="dot"),
        fillcolor="rgba(0, 255, 255, 0.1)",
        row=1, col=1
    )

fig.add_trace(go.Scatter(x=data.index, y=data['Z_Score'], name='Z-Score',
                         line=dict(color='cyan', width=1.5)), row=2, col=1)

fig.add_hrect(y0=Z_THRESHOLD, y1=Z_THRESHOLD + 1.5, fillcolor="red", opacity=0.15, line_width=0, row=2, col=1)
fig.add_hrect(y0=-Z_THRESHOLD, y1=-Z_THRESHOLD - 1.5, fillcolor="green", opacity=0.15, line_width=0, row=2, col=1)
fig.add_hline(y=0, line_color="white", opacity=0.3, row=2, col=1)

fig.update_layout(
    template="plotly_dark",
    height=600,
    hovermode='x unified',
    margin=dict(l=20, r=20, t=20, b=20),
    xaxis_rangeslider_visible=False
)
fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])

st.plotly_chart(fig, use_container_width=True)

# --- TABLA HISTORIAL DE RANGOS DE BALANCE ---
st.subheader("📋 Historial de Rangos de Balance (Filtrado 08:00 - 12:00 NY)")

tabla_data = []
for r in rangos_balance:
    horas_rango = data.loc[r['inicio']:r['fin']].index.hour
    superpone_operativa = any((h >= 8 and h <= 12) for h in horas_rango)

    if superpone_operativa:
        tabla_data.append({
            "Inicio (NY)": r['inicio'].strftime('%Y-%m-%d %H:%M'),
            "Fin (NY)": r['fin'].strftime('%Y-%m-%d %H:%M'),
            "Máximo": f"{r['max']:.5f}",
            "Mínimo": f"{r['min']:.5f}",
            "Estado": "En curso" if r.get('activo') else "Completado"
        })

if tabla_data:
    st.dataframe(pd.DataFrame(tabla_data), use_container_width=True)
else:
    st.write("No hay rangos de balance en la ventana operativa de NY durante el periodo analizado.")
