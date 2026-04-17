import streamlit as st
import pandas as pd
import requests
import time

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Multinet NOC - Alerta Total", page_icon="🚨", layout="wide")

# 1. Credenciales (Ajustadas a tus nombres exactos)
try:
    URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
    SMART_TOKEN = st.secrets["smartolt"]["token"].strip()
    
    # Aquí cambiamos 'bot_token' por 'token' para que coincida con tus secretos
    TG_TOKEN = st.secrets["telegram"]["token"]
    TG_CHAT = st.secrets["telegram"]["chat_id"]
except Exception as e:
    st.error(f"❌ Error en Secrets: Falta la llave {e}")
    st.stop()

# --- MEMORIA DEL SISTEMA ---
if 'fallas_activas' not in st.session_state:
    st.session_state.fallas_activas = set()

st.title("🛰️ Multinet NOC: Monitor con Alertas Telegram")

# --- FUNCIÓN DE TELEGRAM ---
def enviar_alerta_tg(mensaje):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT, "text": mensaje, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except:
        pass

# --- MOTOR DE API ---
def llamar_api(endpoint):
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': SMART_TOKEN}
    try:
        r = requests.post(url, headers=headers, timeout=20)
        if r.status_code == 405: r = requests.get(url, headers=headers, timeout=20)
        if r.status_code == 200:
            res = r.json()
            return res.get('response') if res.get('status') else None
    except: return None
    return None

# --- MONITOREO ---
with st.spinner('Escaneando red...'):
    onus = llamar_api("onu/get_onus_statuses")

if onus is not None:
    df = pd.DataFrame(onus)
    
    # ANALIZADOR DE ALERTAS
    for _, row in df.iterrows():
        sn = row['sn']
        nombre = row.get('onu', 'Desconocido')
        status = str(row['status']).lower()
        pon = f"B{row['board']}/P{row['port']}"
        
        es_falla = status != 'online'
        
        # 1. Nueva Falla
        if es_falla and sn not in st.session_state.fallas_activas:
            tipo = "🔌 FALLA DE RED / ENERGÍA" if ("fail" in status or "los" in status) else "🔴 CLIENTE OFFLINE"
            if "unreachable" in status: tipo = "📡 ONU INALCANZABLE"
            
            msg = f"{tipo}\n\n👤 *Cliente:* {nombre}\n🆔 *SN:* `{sn}`\n🔌 *Puerto:* {pon}\n⏱ *Status:* {status.upper()}"
            enviar_alerta_tg(msg)
            st.session_state.fallas_activas.add(sn)

        # 2. Recuperación
        elif not es_falla and sn in st.session_state.fallas_activas:
            msg = f"✅ *RECUPERADO*\n\n👤 *Cliente:* {nombre}\n🆔 *SN:* `{sn}`\nStatus: ONLINE"
            enviar_alerta_tg(msg)
            st.session_state.fallas_activas.remove(sn)

    # --- INTERFAZ ---
    c1, c2, c3 = st.columns(3)
    c1.metric("Total ONUs", len(df))
    online = len(df[df['status'].str.lower() == 'online'])
    c2.metric("Online ✅", online)
    c3.metric("Fallas 🚨", len(st.session_state.fallas_activas), delta_color="inverse")

    st.markdown("---")
    st.subheader("📋 Estado Actual de Clientes")
    
    df['Status_Icon'] = df['status'].apply(lambda x: "🟢" if str(x).lower() == 'online' else "🔴")
    st.dataframe(
        df[['Status_Icon', 'onu', 'sn', 'board', 'port', 'status', 'last_status_change']].rename(
            columns={'onu': 'Nombre/ID', 'board': 'B', 'port': 'P', 'status': 'Estado'}
        ),
        use_container_width=True, hide_index=True
    )
else:
    st.error("❌ Sin conexión con SmartOLT.")

# Refresco
time.sleep(60)
st.rerun()
