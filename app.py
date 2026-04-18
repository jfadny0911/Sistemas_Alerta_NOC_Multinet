import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Multinet NOC - SmartView", page_icon="📡", layout="wide")

# 1. Credenciales
try:
    URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
    SMART_TOKEN = st.secrets["smartolt"]["token"].strip()
    TG_TOKEN = st.secrets["telegram"]["token"]
    TG_CHAT = st.secrets["telegram"]["chat_id"]
except:
    st.error("❌ Revisa los Secrets.")
    st.stop()

# --- MEMORIA TÉCNICA (Persistencia) ---
if 'db_clientes' not in st.session_state: st.session_state.db_clientes = {}
if 'registro_caidas' not in st.session_state: st.session_state.registro_caidas = {}

st.title("🛰️ Multinet NOC: SmartView Intelligence")

# --- FUNCIONES CORE ---
def enviar_tg(mensaje):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT, "text": mensaje, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def llamar_api(endpoint, timeout=30):
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': SMART_TOKEN}
    try:
        r = requests.post(url, headers=headers, timeout=timeout)
        if r.status_code == 405: r = requests.get(url, headers=headers, timeout=timeout)
        return r.json().get('response') if r.status_code == 200 else None
    except: return None

# --- SIDEBAR: SINCRONIZACIÓN ---
with st.sidebar:
    st.header("⚙️ Panel de Control")
    st.info("⚠️ Si ves 'No Sincronizado', presiona el botón de abajo.")
    if st.button("♻️ Sincronizar Datos de Clientes"):
        with st.spinner("Conectando con base de datos maestra..."):
            # get_all es la única que trae Name y Address or Comment
            data_full = llamar_api("onu/get_all", timeout=90)
            if data_full:
                # Guardamos todo en memoria usando el SN como llave
                st.session_state.db_clientes = {
                    str(r['sn']).strip(): {
                        'name_id': str(r.get('name', 'N/A')),
                        'address': str(r.get('address_or_comment', 'N/A')),
                        'zona': str(r.get('zone_name', 'N/A'))
                    } for r in data_full
                }
                st.success(f"✅ {len(st.session_state.db_clientes)} Clientes cargados.")
                time.sleep(2)
                st.rerun()
            else:
                st.error("SmartOLT tardó demasiado en responder. Reintenta.")

# --- PROCESO DE MONITOREO ---
onus_status = llamar_api("onu/get_onus_statuses")

if onus_status is not None:
    df = pd.DataFrame(onus_status)
    df['sn'] = df['sn'].astype(str).str.strip()
    
    # Función de cruce de datos segura
    def get_info(sn, campo):
        return st.session_state.db_clientes.get(sn, {}).get(campo, "No Sincronizado")

    df['NAME_ID'] = df['sn'].apply(lambda x: get_info(x, 'name_id'))
    df['DIRECCION'] = df['sn'].apply(lambda x: get_info(x, 'address'))
    df['ZONA_DETALLE'] = df['sn'].apply(lambda x: get_info(x, 'zona'))
    df['PUERTO'] = "B" + df['board'].astype(str) + "/P" + df['port'].astype(str)
    
    df_off = df[df['status'].str.lower() != 'online'].copy()

    # --- INDICADORES ---
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Clientes Totales", len(df))
    c2.metric("Online ✅", len(df) - len(df_off))
    c3.metric("Offline ❌", len(df_off), delta_color="inverse")
    c4.metric("Fallas de Puerto", len(df_off['PUERTO'].unique()) if not df_off.empty else 0)

    # --- AVISO SI NO HAY SYNC ---
    if not st.session_state.db_clientes:
        st.warning("👈 Por favor, abre el menú de la izquierda y pulsa 'Sincronizar Datos' para ver Nombres y Direcciones.")

    st.markdown("---")
    
    # BUSCADOR
    busc = st.text_input("🔍 Buscar por Código (Name), Nombre o SN")
    if busc:
        mask = (df['sn'].str.contains(busc, case=False, na=False) | 
                df['NAME_ID'].str.contains(busc, case=False, na=False) |
                df['DIRECCION'].str.contains(busc, case=False, na=False))
        df = df[mask]

    # TABLA MAESTRA
    st.subheader("📋 Monitor Maestro de Red")
    df['Status_Punto'] = df['status'].apply(lambda x: "🟢" if str(x).lower() == 'online' else "🔴")
    
    cols_tab = ['Status_Punto', 'NAME_ID', 'DIRECCION', 'sn', 'ZONA_DETALLE', 'PUERTO', 'status', 'last_status_change']
    st.dataframe(
        df[cols_tab].rename(columns={
            'NAME_ID': 'NAME (Código)', 
            'DIRECCION': 'Address or Comment',
            'ZONA_DETALLE': 'ZONA',
            'status': 'Status',
            'last_status_change': 'Since'
        }), 
        use_container_width=True, hide_index=True
    )

else:
    st.error("❌ Error de conexión con SmartOLT.")

# Auto-refresco
time.sleep(60)
st.rerun()
