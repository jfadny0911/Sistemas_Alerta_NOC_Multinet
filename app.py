import streamlit as st
import pandas as pd
import requests
import gspread
import time
import json
from datetime import datetime, timedelta

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Multinet NOC - SmartOLT", page_icon="📡", layout="wide")
NOMBRE_SHEET = "Inventario_NOC"

# --- FUNCIONES DE APOYO ---
def conectar_gsheets():
    try: return gspread.service_account(filename='google_creds.json')
    except: return None

def enviar_telegram(mensaje, device_id=None):
    try:
        token = st.secrets["telegram"]["token"]
        chat_id = st.secrets["telegram"]["chat_id"]
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": mensaje, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
        return True
    except: return False

# --- CABECERA ---
st.title("🛰️ Dashboard de Clientes y Red - SmartOLT")

if 'ultima_notif' not in st.session_state:
    st.session_state.ultima_notif = {}

# --- OBTENER DATOS DE SMARTOLT ---
onus_data = []
stats = {"online": 0, "offline": 0, "total": 0}

try:
    url_base = st.secrets['smartolt']['url']
    headers = {'X-Token': st.secrets['smartolt']['token']}
    
    # 1. Traer todas las ONUs (Clientes)
    r_onus = requests.get(f"{url_base}/api/onu/get_all", headers=headers, timeout=20)
    
    if r_onus.status_code == 200:
        onus_data = r_onus.json().get('response', [])
        stats["total"] = len(onus_data)
        stats["online"] = len([o for o in onus_data if o.get('status') == 'online'])
        stats["offline"] = len([o for o in onus_data if o.get('status') != 'online'])
    else:
        st.error("Error al conectar con la API de ONUs de SmartOLT")

except Exception as e:
    st.error(f"Error de conexión: {e}")

# --- SECCIÓN 1: MÉTRICAS GENERALES ---
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Total Clientes", stats["total"])
with col2:
    st.metric("Clientes Online", stats["online"], delta_color="normal")
with col3:
    st.metric("Clientes Offline", stats["offline"], delta="- Fallas", delta_color="inverse")
with col4:
    eficiencia = (stats["online"] / stats["total"] * 100) if stats["total"] > 0 else 0
    st.metric("Salud de la Red", f"{eficiencia:.1f}%")

# --- SECCIÓN 2: PESTAÑAS ---
tab1, tab2, tab3 = st.tabs(["🔴 Clientes en Falla", "🏢 Estado de OLTs", "📈 Historial"])

with tab1:
    st.subheader("Clientes fuera de línea (Offline)")
    clientes_off = [o for o in onus_data if o.get('status') != 'online']
    
    if clientes_off:
        df_off = pd.DataFrame(clientes_off)
        # Seleccionamos solo las columnas importantes para no saturar
        columnas_ver = ['name', 'sn', 'olt_name', 'pon_port', 'signal', 'last_online_at']
        # Renombramos para que sea más legible
        df_display = df_off[columnas_ver].rename(columns={
            'name': 'Cliente',
            'sn': 'Serie ONU',
            'olt_name': 'OLT',
            'pon_port': 'Puerto PON',
            'signal': 'Última Señal',
            'last_online_at': 'Visto por última vez'
        })
        
        st.dataframe(df_display, use_container_width=True, hide_index=True)
    else:
        st.success("🎉 ¡Increíble! No hay clientes offline en este momento.")

with tab2:
    st.subheader("Estado de Cabeceras (OLTs)")
    # Aquí puedes mantener el código anterior de /api/system/get_olts
    # para vigilar si una OLT completa se cae.
    try:
        r_olts = requests.get(f"{url_base}/api/system/get_olts", headers=headers, timeout=15)
        if r_olts.status_code == 200:
            olts = r_olts.json().get('response', [])
            for o in olts:
                color = "green" if o.get('status') == 'online' else "red"
                st.markdown(f"**{o.get('name')}**: :{color}[{o.get('status').upper()}] - IP: {o.get('ip')}")
    except:
        st.write("No se pudo cargar el estado de las OLTs.")

# --- AUTO REFRESH ---
time.sleep(60)
st.rerun()
