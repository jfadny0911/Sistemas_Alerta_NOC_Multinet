import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Multinet NOC - Reporte Forzado", page_icon="📡", layout="wide")

# 1. Credenciales
try:
    URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
    SMART_TOKEN = st.secrets["smartolt"]["token"].strip()
    TG_TOKEN = st.secrets["telegram"]["token"]
    TG_CHAT = st.secrets["telegram"]["chat_id"]
except Exception as e:
    st.error(f"❌ Error en Secrets: {e}")
    st.stop()

# --- MEMORIA ---
if 'ultimo_hash_fallas' not in st.session_state:
    st.session_state.ultimo_hash_fallas = ""

st.title("🛰️ Multinet NOC: Monitoreo y Alertas")

# --- FUNCIONES ---
def enviar_tg(mensaje):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT, "text": mensaje, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except: return False

def llamar_api(endpoint):
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': SMART_TOKEN}
    try:
        r = requests.post(url, headers=headers, timeout=20)
        if r.status_code == 405: r = requests.get(url, headers=headers, timeout=20)
        return r.json().get('response') if r.status_code == 200 else None
    except: return None

# --- LÓGICA DE CONSTRUCCIÓN DE REPORTE ---
def generar_texto_reporte(df_total, df_caidos, olts_lista):
    ahora = datetime.now().strftime('%d/%m/%Y %H:%M')
    msg = f"📊 *INFORME DE ESTADO MULTINET*\n📅 _{ahora}_\n"
    msg += "------------------------------------------\n"
    msg += f"✅ *Online:* {len(df_total) - len(df_caidos)}\n"
    msg += f"🔴 *Offline:* {len(df_caidos)}\n"
    msg += "------------------------------------------\n\n"
    
    if not df_caidos.empty:
        for olt_id in df_caidos['olt_id'].unique():
            nombre_olt = next((o.get('name') for o in olts_lista if str(o.get('id')) == str(olt_id)), f"OLT {olt_id}") if olts_lista else f"OLT {olt_id}"
            msg += f"🏢 *OLT:* {nombre_olt}\n"
            df_p_off = df_caidos[df_caidos['olt_id'] == olt_id]
            for p in df_p_off['PUERTO'].unique():
                clientes = ", ".join(df_p_off[df_p_off['PUERTO'] == p]['NAME_ID'].astype(str).tolist())
                msg += f"  🔌 *Port:* {p} ({len(df_p_off[df_p_off['PUERTO'] == p])} caídos)\n"
                msg += f"  👤 _IDs:_ {clientes}\n"
            msg += "\n"
    else:
        msg += "✅ No se detectan fallas en la red."
    return msg

# --- OBTENCIÓN DE DATOS ---
with st.spinner('Sincronizando...'):
    onus = llamar_api("onu/get_onus_statuses")
    olts = llamar_api("system/get_olts")
    unconfigured = llamar_api("onu/get_unconfigured")

if onus is not None:
    df = pd.DataFrame(onus)
    df['NAME_ID'] = df['onu'].fillna(df['sn'])
    df['PUERTO'] = "B" + df['board'].astype(str) + "/P" + df['port'].astype(str)
    df_off = df[df['status'].str.lower() != 'online'].copy()

    # --- SIDEBAR: BOTONES DE ACCIÓN ---
    with st.sidebar:
        st.header("📲 Centro de Notificaciones")
        if st.button("🚀 Enviar Reporte de Estado Ahora"):
            texto = generar_texto_reporte(df, df_off, olts)
            if enviar_tg(texto): st.success("Reporte enviado a Telegram")
            else: st.error("Error al enviar")
        
        if st.button("🔔 Prueba de Bot"):
            if enviar_tg("Test rápido: Bot funcionando"): st.success("Test OK")

    # --- MONITOREO AUTOMÁTICO (Solo si hay cambios) ---
    hash_actual = "-".join(sorted(df_off['sn'].astype(str).tolist()))
    if hash_actual != st.session_state.ultimo_hash_fallas:
        if not df_off.empty:
            enviar_tg(generar_texto_reporte(df, df_off, olts))
        st.session_state.ultimo_hash_fallas = hash_actual

    # --- INTERFAZ ---
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ONUs Totales", len(df))
    c2.metric("Online ✅", len(df) - len(df_off))
    c3.metric("Offline 🔴", len(df_off), delta_color="inverse")
    c4.metric("Nuevas 🆕", len(unconfigured) if unconfigured else 0)

    st.markdown("---")
    st.subheader("📋 Detalle de Clientes")
    df['Status_Icon'] = df['status'].apply(lambda x: "🟢" if str(x).lower() == 'online' else "🔴")
    st.dataframe(df[['Status_Icon', 'NAME_ID', 'sn', 'PUERTO', 'status', 'last_status_change']], use_container_width=True, hide_index=True)

else:
    st.error("❌ No se pudo conectar a SmartOLT.")

# Refresco cada 60s
time.sleep(60)
st.rerun()
