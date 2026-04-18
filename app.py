import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime
import plotly.express as px

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Multinet NOC - Enterprise", page_icon="🛡️", layout="wide")

# 1. Credenciales
try:
    URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
    SMART_TOKEN = st.secrets["smartolt"]["token"].strip()
    TG_TOKEN = st.secrets["telegram"]["token"]
    TG_CHAT = st.secrets["telegram"]["chat_id"]
except:
    st.error("❌ Configura los Secrets correctamente.")
    st.stop()

# Persistencia de memoria
if 'registro_caidas' not in st.session_state: st.session_state.registro_caidas = {}
if 'contador_flapping' not in st.session_state: st.session_state.contador_flapping = {}

st.title("🛡️ Multinet NOC: Gestión Proactiva")

def llamar_api(endpoint):
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': SMART_TOKEN}
    try:
        # Aumentamos el timeout a 30 segundos para procesos pesados
        r = requests.post(url, headers=headers, timeout=30)
        if r.status_code == 405: 
            r = requests.get(url, headers=headers, timeout=30)
        return r.json().get('response') if r.status_code == 200 else None
    except Exception as e:
        return None

# --- MOTOR DE DATOS INTELIGENTE ---
with st.spinner('Sincronizando con SmartOLT (Modo Inteligente)...'):
    # INTENTO 1: Información avanzada (dBm, etc)
    onus_data = llamar_api("onu/get_all")
    modo_avanzado = True
    
    # FALLBACK: Si falla el avanzado, usamos el básico
    if onus_data is None:
        onus_data = llamar_api("onu/get_onus_statuses")
        modo_avanzado = False
        st.warning("⚠️ Usando Modo Básico: La API avanzada no respondió a tiempo.")

    olts = llamar_api("system/get_olts")
    unconfigured = llamar_api("onu/get_unconfigured")

if onus_data:
    df = pd.DataFrame(onus_data)
    df['PUERTO'] = "B" + df['board'].astype(str) + "/P" + df['port'].astype(str)
    
    # Manejo de nombres: get_all usa 'name', get_onus_statuses usa 'onu'
    nombre_col = 'name' if 'name' in df.columns else 'onu'
    df['CLIENTE'] = df[nombre_col].fillna(df['sn'])

    # --- KPI PRINCIPALES ---
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Base Total", len(df))
    online_df = df[df['status'].str.lower() == 'online']
    c2.metric("Online ✅", len(online_df))
    c3.metric("Offline ❌", len(df) - len(online_df), delta_color="inverse")
    c4.metric("Nuevas 🆕", len(unconfigured) if unconfigured else 0)

    st.markdown("---")

    # --- PESTAÑAS ---
    t_mon, t_signal, t_hw = st.tabs(["🖥️ Monitor Real-Time", "📡 Análisis Óptico", "🏢 Estado Hardware"])

    with t_mon:
        st.subheader("Control de Dispositivos")
        # Tabla de monitoreo
        df['Icon'] = df['status'].apply(lambda x: "🟢" if str(x).lower() == 'online' else "🔴")
        cols = ['Icon', 'CLIENTE', 'sn', 'PUERTO', 'status']
        if modo_avanzado and 'signal' in df.columns: cols.append('signal')
        
        st.dataframe(df[cols], use_container_width=True, hide_index=True)

    with t_signal:
        if modo_avanzado and 'signal' in df.columns:
            st.subheader("Radar de Potencia Óptica")
            df['signal_num'] = pd.to_numeric(df['signal'], errors='coerce')
            
            # Gráfica de salud de fibra
            fig = px.histogram(df, x="signal_num", nbins=25, title="Distribución de Señales dBm", color_discrete_sequence=['#00CC96'])
            st.plotly_chart(fig, use_container_width=True)
            
            criticos = df[df['signal_num'] < -27]
            st.error(f"Se detectaron {len(criticos)} clientes con señal crítica (Peor a -27dBm)")
            st.dataframe(criticos[['CLIENTE', 'sn', 'signal', 'PUERTO']], use_container_width=True)
        else:
            st.info("ℹ️ La información de señal (dBm) no está disponible en modo básico.")

    with t_hw:
        st.subheader("Estado de las OLTs")
        if olts:
            for o in olts:
                st_raw = str(o.get('status')).lower()
                is_up = st_raw in ['online', 'up', '1', 'active']
                color = "green" if is_up else "red"
                st.markdown(f"🏢 **{o.get('name')}** | IP: `{o.get('ip')}` | Estado: :{color}[{st_raw.upper()}]")

else:
    st.error("❌ No se pudo obtener ningún tipo de información de la API. Revisa tu Token y la URL.")

time.sleep(60)
st.rerun()
