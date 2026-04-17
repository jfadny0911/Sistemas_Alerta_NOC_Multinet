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
    except Exception as e: 
        st.sidebar.error(f"Error Google Sheets: {e}")
        return None

def enviar_telegram(mensaje, device_id=None):
    try:
        token = st.secrets["telegram"]["token"]
        chat_id = st.secrets["telegram"]["chat_id"]
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": mensaje, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
        return True
    except: 
        return False

# --- CABECERA ---
st.title("🛰️ Dashboard de Clientes y Red - SmartOLT")

if 'ultima_notif' not in st.session_state:
    st.session_state.ultima_notif = {}

# --- OBTENER DATOS DE SMARTOLT ---
onus_data = []
stats = {"online": 0, "offline": 0, "total": 0}

try:
    # Quitamos la barra diagonal final de la URL si el usuario la puso por accidente
    url_base = str(st.secrets['smartolt']['url']).rstrip('/')
    headers = {'X-Token': st.secrets['smartolt']['token']}
    
    # 1. Traer todas las ONUs (Clientes) con un timeout más alto
    r_onus = requests.get(f"{url_base}/api/onu/get_all", headers=headers, timeout=40)
    
    if r_onus.status_code == 200:
        # Algunos endpoints de SmartOLT devuelven la lista directo, otros dentro de 'response'
        data_json = r_onus.json()
        onus_data = data_json.get('response', []) if isinstance(data_json, dict) else data_json
        
        stats["total"] = len(onus_data)
        stats["online"] = len([o for o in onus_data if str(o.get('status')).lower() == 'online'])
        stats["offline"] = stats["total"] - stats["online"]
    else:
        # AQUÍ ESTÁ EL DIAGNÓSTICO EXACTO
        st.error(f"❌ Error SmartOLT ONUs (Código {r_onus.status_code}): {r_onus.text}")

except KeyError as e:
    st.error(f"❌ Falla en secretos: Falta la llave {e} en secrets.toml")
except requests.exceptions.Timeout:
    st.error("⏳ SmartOLT tardó demasiado en responder. Tu red tiene muchos clientes o la API está lenta.")
except Exception as e:
    st.error(f"❌ Error de conexión: {e}")

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

st.markdown("---")

# --- SECCIÓN 2: PESTAÑAS ---
tab1, tab2, tab3 = st.tabs(["🔴 Clientes en Falla", "🏢 Estado de OLTs", "📈 Historial del NOC"])

with tab1:
    st.subheader("Clientes fuera de línea (Offline)")
    clientes_off = [o for o in onus_data if str(o.get('status')).lower() != 'online']
    
    if clientes_off:
        df_off = pd.DataFrame(clientes_off)
        
        # Filtramos las columnas si existen en la respuesta de SmartOLT
        columnas_disponibles = df_off.columns.tolist()
        columnas_ver = []
        nombres_amigables = {}
        
        if 'name' in columnas_disponibles: 
            columnas_ver.append('name')
            nombres_amigables['name'] = 'Cliente'
        if 'sn' in columnas_disponibles:
            columnas_ver.append('sn')
            nombres_amigables['sn'] = 'Serie ONU'
        if 'olt_name' in columnas_disponibles:
            columnas_ver.append('olt_name')
            nombres_amigables['olt_name'] = 'OLT'
        if 'pon_port' in columnas_disponibles:
            columnas_ver.append('pon_port')
            nombres_amigables['pon_port'] = 'Puerto PON'
        if 'signal' in columnas_disponibles:
            columnas_ver.append('signal')
            nombres_amigables['signal'] = 'Última Señal'
        if 'last_online_at' in columnas_disponibles:
            columnas_ver.append('last_online_at')
            nombres_amigables['last_online_at'] = 'Visto última vez'
            
        if columnas_ver:
            df_display = df_off[columnas_ver].rename(columns=nombres_amigables)
            st.dataframe(df_display, use_container_width=True, hide_index=True)
        else:
            st.dataframe(df_off, use_container_width=True) # Por si la API devuelve algo distinto
    else:
        if stats["total"] > 0:
            st.success("🎉 ¡Increíble! No hay clientes offline en este momento.")
        else:
            st.info("Esperando datos de la API...")

with tab2:
    st.subheader("Estado de Cabeceras (OLTs)")
    try:
        r_olts = requests.get(f"{url_base}/api/system/get_olts", headers=headers, timeout=15)
        if r_olts.status_code == 200:
            data_olts = r_olts.json()
            olts = data_olts.get('response', []) if isinstance(data_olts, dict) else data_olts
            
            for o in olts:
                estado_str = str(o.get('status', 'offline')).lower()
                color = "green" if estado_str in ['online', '1', 'up'] else "red"
                st.markdown(f"**{o.get('name', 'OLT')}**: :{color}[{estado_str.upper()}] - IP: {o.get('ip', 'N/A')}")
        else:
            st.error(f"Error cargando OLTs: {r_olts.status_code}")
    except Exception as e:
        st.write("No se pudo cargar el estado de las OLTs.")

with tab3:
    st.subheader("Historial de Atención de Fallas (Google Sheets)")
    gc = conectar_gsheets()
    if gc:
        try:
            sh = gc.open(NOMBRE_SHEET)
            df_logs = pd.DataFrame(sh.worksheet("Log_Fallas").get_all_records())
            if not df_logs.empty:
                st.dataframe(df_logs.tail(15), use_container_width=True)
            else:
                st.info("No hay registros en el archivo Log_Fallas.")
        except Exception as e:
            st.warning("No se pudo leer la pestaña Log_Fallas del Excel.")
    else:
        st.error("Conexión a Google Sheets no disponible.")

# --- AUTO REFRESH ---
time.sleep(60)
st.rerun()
