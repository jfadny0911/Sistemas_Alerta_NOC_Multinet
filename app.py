import streamlit as st
import pd as pd # No es necesario el alias pd si usas pandas directo, pero lo mantengo por tu estilo
import pandas as pd
import requests
import gspread
import time
import json
from datetime import datetime, timedelta

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="NOC Multinet - SmartOLT", page_icon="📡", layout="wide")
NOMBRE_SHEET = "Inventario_NOC"

def conectar_gsheets():
    try: return gspread.service_account(filename='google_creds.json')
    except: return None

# --- LIMPIEZA DE URL ---
# Esto asegura que la URL sea: https://dominio.com/api/onu/get_all
url_limpia = str(st.secrets['smartolt']['url']).rstrip('/')
if not url_limpia.endswith('/api'):
    url_final = f"{url_limpia}/api"
else:
    url_final = url_limpia

headers = {'X-Token': st.secrets['smartolt']['token']}

st.title("🛰️ Sistema NOC Multinet - SmartOLT")

# --- LÓGICA DE DATOS ---
onus_data = []
stats = {"online": 0, "offline": 0, "total": 0}

try:
    # Intentamos obtener los clientes
    # Nota: Si POST falla con 405, a veces es porque esta versión específica de SmartOLT usa GET
    r = requests.post(f"{url_final}/onu/get_all", headers=headers, timeout=30)
    
    # Si da error 405 con POST, intentamos automáticamente con GET
    if r.status_code == 405:
        r = requests.get(f"{url_final}/onu/get_all", headers=headers, timeout=30)

    if r.status_code == 200:
        res = r.json()
        if res.get('status'):
            onus_data = res.get('response', [])
            stats["total"] = len(onus_data)
            stats["online"] = len([o for o in onus_data if str(o.get('status')).lower() == 'online'])
            stats["offline"] = stats["total"] - stats["online"]
        else:
            st.error(f"❌ Error de SmartOLT: {res.get('error')}")
    else:
        st.error(f"❌ Error de Conexión (Código {r.status_code})")
        st.info(f"URL intentada: {url_final}/onu/get_all")

except Exception as e:
    st.error(f"❌ Error crítico: {e}")

# --- INTERFAZ ---
col1, col2, col3 = st.columns(3)
col1.metric("Clientes Totales", stats["total"])
col2.metric("Online ✅", stats["online"])
col3.metric("Offline ❌", stats["offline"], delta_color="inverse")

tab1, tab2 = st.tabs(["🔴 Fallas Actuales", "📊 Historial"])

with tab1:
    clientes_off = [o for o in onus_data if str(o.get('status')).lower() != 'online']
    if clientes_off:
        df = pd.DataFrame(clientes_off)
        # Seleccionamos solo lo que SmartOLT garantiza enviar
        cols = [c for c in ['name', 'sn', 'olt_name', 'pon_port', 'signal'] if c in df.columns]
        st.dataframe(df[cols], use_container_width=True)
    else:
        st.success("Sin clientes offline detectados.")

with tab2:
    st.write("Datos de Google Sheets")
    gc = conectar_gsheets()
    if gc:
        try:
            sh = gc.open(NOMBRE_SHEET)
            st.dataframe(pd.DataFrame(sh.worksheet("Log_Fallas").get_all_records()).tail(10))
        except: st.warning("No se pudo cargar el historial.")

time.sleep(60)
st.rerun()
