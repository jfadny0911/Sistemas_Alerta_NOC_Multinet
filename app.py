import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Multinet NOC - Ultra Intelligence", page_icon="📡", layout="wide")

# 1. Carga de Credenciales
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

st.title("🛰️ Multinet NOC: Centro de Control")

# --- FUNCIONES CORE ---
def enviar_tg(mensaje):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT, "text": mensaje, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def llamar_api(endpoint):
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': SMART_TOKEN}
    try:
        r = requests.post(url, headers=headers, timeout=20)
        if r.status_code == 405: r = requests.get(url, headers=headers, timeout=20)
        return r.json().get('response') if r.status_code == 200 else None
    except: return None

# --- OBTENCIÓN DE DATOS ---
with st.spinner('Sincronizando con SmartOLT...'):
    onus = llamar_api("onu/get_onus_statuses")
    olts = llamar_api("system/get_olts")
    unconfigured = llamar_api("onu/get_unconfigured")
    zonas = llamar_api("system/get_zones")

if onus is not None:
    df = pd.DataFrame(onus)
    # Preparar datos de clientes
    df['NAME_ID'] = df['onu'].fillna(df['sn'])
    df['PUERTO'] = "B" + df['board'].astype(str) + "/P" + df['port'].astype(str)
    
    # --- PROCESAMIENTO DE FALLAS PARA TELEGRAM ---
    df_off = df[df['status'].str.lower() != 'online'].copy()
    hash_actual = "-".join(sorted(df_off['sn'].astype(str).tolist()))

    if hash_actual != st.session_state.ultimo_hash_fallas:
        if not df_off.empty:
            ahora = datetime.now().strftime('%d/%m/%Y %H:%M')
            reporte = f"🚨 *REPORTE DE INCIDENCIAS MULTINET*\n📅 _{ahora}_\n"
            reporte += "------------------------------------------\n\n"
            
            for olt_id in df_off['olt_id'].unique():
                # Intentamos buscar el nombre de la OLT si está en la lista de OLTS
                nombre_olt = olt_id
                if olts:
                    for o in olts:
                        if str(o.get('id')) == str(olt_id):
                            nombre_olt = o.get('name')
                
                reporte += f"🏢 *OLT:* {nombre_olt}\n"
                df_olt = df_off[df_off['olt_id'] == olt_id]
                
                for p in df_olt['PUERTO'].unique():
                    df_p = df_olt[df_olt['PUERTO'] == p]
                    nombres = ", ".join(df_p['NAME_ID'].astype(str).tolist())
                    reporte += f"  🔌 *Puerto:* {p} ({len(df_p)} caídos)\n"
                    reporte += f"  👤 _Clientes:_ {nombres}\n"
                reporte += "\n"
            
            reporte += "------------------------------------------\n"
            reporte += f"📉 *TOTAL OFFLINE:* {len(df_off)}"
            enviar_tg(reporte)
        st.session_state.ultimo_hash_fallas = hash_actual

    # --- INTERFAZ ---
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total ONUs", len(df))
    k2.metric("Online ✅", len(df[df['status'].str.lower() == 'online']))
    k3.metric("Offline 🚨", len(df_off), delta_color="inverse")
    k4.metric("Por Autorizar 🆕", len(unconfigured) if unconfigured else 0)

    st.markdown("---")

    t1, t2, t3 = st.tabs(["🖥️ Monitor de Clientes", "🆕 Por Autorizar", "🏢 Estado de OLTS"])

    with t1:
        st.subheader("📋 Lista de Clientes (Base Completa)")
        df['Icono'] = df['status'].apply(lambda x: "🟢" if str(x).lower() == 'online' else "🔴")
        st.dataframe(df[['Icono', 'NAME_ID', 'sn', 'PUERTO', 'status', 'last_status_change']], use_container_width=True, hide_index=True)

    with t2:
        st.subheader("🆕 Equipos detectados sin configurar")
        if unconfigured:
            st.success(f"Se encontraron {len(unconfigured)} ONUs esperando.")
            st.dataframe(pd.DataFrame(unconfigured), use_container_width=True)
        else:
            st.info("No hay equipos pendientes de autorización.")

    with t3:
        st.subheader("🏢 Estado del Hardware (OLTs)")
        if olts:
            for o in olts:
                # Lógica de estado ultra-robusta
                st_raw = str(o.get('status', '')).lower()
                # Consideramos online si es 'online', '1', 'up', 'active', etc.
                is_online = st_raw in ['online', '1', 'true', 'up', 'active', 'enabled']
                
                nombre = o.get('name', 'OLT Desconocida')
                ip = o.get('ip', 'N/A')
                status_txt = "ONLINE" if is_online else f"OFFLINE ({st_raw})"
                color = "green" if is_online else "red"
                
                st.markdown(f"🖥️ **{nombre}** | IP: `{ip}` | Estado: :{color}[{status_txt}]")
                # Botón de ayuda para debug si siguen saliendo offline
                if not is_online:
                    with st.expander(f"Ver datos crudos de {nombre}"):
                        st.json(o)
        else:
            st.warning("No se recibió información de las OLTs. Verifica los permisos de tu API Key.")

else:
    st.error("❌ No se pudo conectar con SmartOLT.")

# Auto-refresco
time.sleep(60)
st.rerun()
