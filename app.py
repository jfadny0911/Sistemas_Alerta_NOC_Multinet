import streamlit as st
import pandas as pd
import requests
import time

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Multinet NOC - Alerta Total", page_icon="🚨", layout="wide")

# Credenciales
URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
SMART_TOKEN = st.secrets["smartolt"]["token"].strip()
TG_TOKEN = st.secrets["telegram"]["bot_token"]
TG_CHAT = st.secrets["telegram"]["chat_id"]

# --- MEMORIA DEL SISTEMA (Evita spam de mensajes) ---
if 'fallas_activas' not in st.session_state:
    st.session_state.fallas_activas = set() # Aquí guardamos los SN que ya notificamos

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

# --- PROCESO DE MONITOREO ---
with st.spinner('Escaneando red en busca de fallas...'):
    onus = llamar_api("onu/get_onus_statuses")
    zonas = llamar_api("system/get_zones")

if onus is not None:
    df = pd.DataFrame(onus)
    
    # Cruce de Zonas para el mensaje de Telegram
    df_z = pd.DataFrame(zonas) if zonas else pd.DataFrame()
    
    # ANALIZADOR DE ALERTAS
    for _, row in df.iterrows():
        sn = row['sn']
        nombre = row.get('onu', 'Desconocido')
        status = str(row['status']).lower()
        pon = f"B{row['board']}/P{row['port']}"
        
        # Lógica de detección de falla (LoS, PwFail, Offline, etc.)
        es_falla = status != 'online'
        
        # 1. Detectar Nueva Falla
        if es_falla and sn not in st.session_state.fallas_activas:
            # Determinamos el tipo de falla (Si SmartOLT no da el detalle, lo marcamos como Crítico)
            tipo_falla = "🔴 ALERTA DE CAÍDA"
            if "fail" in status or "los" in status:
                tipo_falla = "🔌 FALLA DE ENERGÍA / CORTE FIBRA"
            elif "unreachable" in status:
                tipo_falla = "📡 ONU INALCANZABLE (N/A)"
            
            msg = f"{tipo_falla}\n\n👤 *Cliente:* {nombre}\n🆔 *SN:* `{sn}`\n🔌 *Puerto:* {pon}\n⏱ *Status:* {status.upper()}"
            enviar_alerta_tg(msg)
            st.session_state.fallas_activas.add(sn)
            st.toast(f"Alerta enviada: {nombre}", icon="🚨")

        # 2. Detectar Recuperación (Back Online)
        elif not es_falla and sn in st.session_state.fallas_activas:
            msg = f"✅ *CLIENTE RECUPERADO*\n\n👤 *Cliente:* {nombre}\n🆔 *SN:* `{sn}`\nStatus: ONLINE"
            enviar_alerta_tg(msg)
            st.session_state.fallas_activas.remove(sn)
            st.toast(f"Cliente recuperado: {nombre}", icon="✅")

    # --- INTERFAZ DEL DASHBOARD ---
    c1, c2, c3 = st.columns(3)
    c1.metric("ONUs Totales", len(df))
    online = len(df[df['status'].str.lower() == 'online'])
    c2.metric("Online ✅", online)
    c3.metric("Fallas Activas 🚨", len(st.session_state.fallas_activas), delta_color="inverse")

    st.markdown("---")
    st.subheader("📋 Monitor de Estado en Tiempo Real")
    
    # Mostramos la tabla filtrando las columnas que te interesan
    df['Status_Icon'] = df['status'].apply(lambda x: "🟢" if str(x).lower() == 'online' else "🔴")
    st.dataframe(
        df[['Status_Icon', 'onu', 'sn', 'board', 'port', 'status', 'last_status_change']].rename(
            columns={'onu': 'Nombre/ID', 'board': 'B', 'port': 'P', 'status': 'Estado'}
        ),
        use_container_width=True, hide_index=True
    )

else:
    st.error("Error de conexión. Revisa el Token.")

# Auto-refresco cada 60 segundos
time.sleep(60)
st.rerun()
