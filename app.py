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
    try: 
        return gspread.service_account(filename='google_creds.json')
    except: 
        return None

def enviar_telegram(mensaje, device_id=None):
    try:
        token = st.secrets["telegram"]["token"]
        chat_id = st.secrets["telegram"]["chat_id"]
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": mensaje, "parse_mode": "Markdown"}
        if device_id:
            payload["reply_markup"] = json.dumps({
                "inline_keyboard": [[{"text": "🙋‍♂️ Asignarme", "callback_data": f"asignar_{device_id}"}]]
            })
        requests.post(url, json=payload, timeout=10)
        return True
    except: 
        return False

# --- CABECERA ---
st.title("🛰️ Dashboard de Clientes y Red - SmartOLT")

if 'ultima_notif' not in st.session_state:
    st.session_state.ultima_notif = {}

# --- PROCESAMIENTO DE URL (LIMPIEZA) ---
# Esto evita que se duplique el "/api" o las barras "/"
url_cruda = str(st.secrets['smartolt']['url']).rstrip('/')
if url_cruda.endswith('/api'):
    url_base = url_cruda
else:
    url_base = f"{url_cruda}/api"

headers = {'X-Token': st.secrets['smartolt']['token']}

# --- OBTENER DATOS DE ONUS (CLIENTES) ---
onus_data = []
stats = {"online": 0, "offline": 0, "total": 0}

try:
    # IMPORTANTE: Usamos POST y una URL limpia
    r_onus = requests.post(f"{url_base}/onu/get_all", headers=headers, timeout=40)
    
    if r_onus.status_code == 200:
        res_json = r_onus.json()
        if res_json.get('status'):
            onus_data = res_json.get('response', [])
            stats["total"] = len(onus_data)
            stats["online"] = len([o for o in onus_data if str(o.get('status')).lower() == 'online'])
            stats["offline"] = stats["total"] - stats["online"]
        else:
            st.error(f"❌ SmartOLT reportó un error: {res_json.get('error')}")
    else:
        st.error(f"❌ Error API ONUs (Código {r_onus.status_code}): {r_onus.text}")
except Exception as e:
    st.error(f"❌ Error de conexión al buscar clientes: {e}")

# --- SECCIÓN 1: MÉTRICAS GENERALES ---
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Total Clientes", stats["total"])
with col2:
    st.metric("Clientes Online", stats["online"])
with col3:
    st.metric("Clientes Offline", stats["offline"], delta_color="inverse")
with col4:
    salud = (stats["online"] / stats["total"] * 100) if stats["total"] > 0 else 0
    st.metric("Salud de la Red", f"{salud:.1f}%")

st.markdown("---")

# --- SECCIÓN 2: PESTAÑAS ---
tab1, tab2, tab3 = st.tabs(["🔴 Clientes en Falla", "🏢 Estado de OLTs", "📈 Historial"])

with tab1:
    st.subheader("Clientes fuera de línea (Offline)")
    clientes_off = [o for o in onus_data if str(o.get('status')).lower() != 'online']
    
    if clientes_off:
        df_off = pd.DataFrame(clientes_off)
        # Columnas que SmartOLT suele devolver
        cols_map = {
            'name': 'Cliente', 'sn': 'Serie ONU', 'olt_name': 'OLT',
            'pon_port': 'Puerto', 'signal': 'Señal', 'last_online_at': 'Visto Últ. Vez'
        }
        existentes = [c for c in cols_map.keys() if c in df_off.columns]
        st.dataframe(df_off[existentes].rename(columns=cols_map), use_container_width=True, hide_index=True)
    else:
        st.success("✅ No hay clientes offline detectados.")

with tab2:
    st.subheader("Estado de Cabeceras (OLTs)")
    try:
        r_olts = requests.post(f"{url_base}/system/get_olts", headers=headers, timeout=15)
        if r_olts.status_code == 200:
            olts = r_olts.json().get('response', [])
            for o in olts:
                st.write(f"🖥️ **{o.get('name')}** - IP: {o.get('ip')} - Status: {o.get('status')}")
        else:
            st.error(f"Error OLTs (Código {r_olts.status_code})")
    except:
        st.error("Falla al conectar con la sección de OLTs.")

with tab3:
    st.subheader("Historial (Google Sheets)")
    gc = conectar_gsheets()
    if gc:
        try:
            sh = gc.open(NOMBRE_SHEET)
            df_logs = pd.DataFrame(sh.worksheet("Log_Fallas").get_all_records())
            st.dataframe(df_logs.tail(20), use_container_width=True)
        except:
            st.warning("No se pudo leer el Excel.")

# --- AUTO REFRESH ---
time.sleep(60)
st.rerun()
