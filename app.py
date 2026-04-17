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
        return None

def enviar_telegram(mensaje, device_id=None):
    try:
        token = st.secrets["telegram"]["token"]
        chat_id = st.secrets["telegram"]["chat_id"]
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": mensaje, "parse_mode": "Markdown"}
        
        if device_id:
            payload["reply_markup"] = json.dumps({
                "inline_keyboard": [[
                    {"text": "🙋‍♂️ Asignarme", "callback_data": f"asignar_{device_id}"}
                ]]
            })
            
        requests.post(url, json=payload, timeout=10)
        return True
    except: 
        return False

# --- CABECERA ---
st.title("🛰️ Dashboard de Clientes y Red - SmartOLT")

# Inicializar sesión para no repetir alertas
if 'ultima_notif' not in st.session_state:
    st.session_state.ultima_notif = {}

# --- OBTENER DATOS DE SMARTOLT (MÉTODO POST) ---
onus_data = []
stats = {"online": 0, "offline": 0, "total": 0}

try:
    url_base = str(st.secrets['smartolt']['url']).rstrip('/')
    headers = {'X-Token': st.secrets['smartolt']['token']}
    
    # Consulta de ONUs usando POST (Corregido)
    r_onus = requests.post(f"{url_base}/api/onu/get_all", headers=headers, timeout=40)
    
    if r_onus.status_code == 200:
        res_json = r_onus.json()
        if res_json.get('status'):
            onus_data = res_json.get('response', [])
            stats["total"] = len(onus_data)
            stats["online"] = len([o for o in onus_data if str(o.get('status')).lower() == 'online'])
            stats["offline"] = stats["total"] - stats["online"]
        else:
            st.error(f"❌ SmartOLT Error: {res_json.get('error')}")
    else:
        st.error(f"❌ Error de Conexión SmartOLT (Código {r_onus.status_code})")

except Exception as e:
    st.error(f"❌ Error crítico: {e}")

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
        cols_interes = {
            'name': 'Cliente',
            'sn': 'Serie ONU',
            'olt_name': 'OLT',
            'pon_port': 'Puerto',
            'signal': 'Señal',
            'last_online_at': 'Visto Últ. Vez'
        }
        # Filtrar solo las columnas que existan en el DataFrame
        existentes = [c for c in cols_interes.keys() if c in df_off.columns]
        df_display = df_off[existentes].rename(columns=cols_interes)
        st.dataframe(df_display, use_container_width=True, hide_index=True)
    else:
        st.success("✅ No se detectan clientes offline.")

with tab2:
    st.subheader("Estado de Cabeceras (OLTs)")
    try:
        r_olts = requests.post(f"{url_base}/api/system/get_olts", headers=headers, timeout=15)
        if r_olts.status_code == 200:
            olts = r_olts.json().get('response', [])
            for o in olts:
                state = str(o.get('status')).lower()
                icon = "🟢" if state == 'online' else "🔴"
                st.write(f"{icon} **{o.get('name')}** - IP: {o.get('ip')} ({state.upper()})")
                
                # Alerta automática si una OLT se cae
                if state != 'online':
                    did = f"olt_{o.get('id')}"
                    ahora = datetime.now()
                    ultima = st.session_state.ultima_notif.get(did)
                    if ultima is None or (ahora - ultima) > timedelta(minutes=30):
                        msg = f"🚨 *OLT CAÍDA:* {o.get('name')}\n🌐 IP: {o.get('ip')}"
                        if enviar_telegram(msg, device_id=did):
                            st.session_state.ultima_notif[did] = ahora
        else:
            st.error("No se pudo obtener el estado de las OLTs.")
    except:
        st.error("Falla al conectar con la API de OLTs.")

with tab3:
    st.subheader("Registros de Google Sheets")
    gc = conectar_gsheets()
    if gc:
        try:
            sh = gc.open(NOMBRE_SHEET)
            df_logs = pd.DataFrame(sh.worksheet("Log_Fallas").get_all_records())
            st.dataframe(df_logs.tail(20), use_container_width=True)
        except:
            st.warning("No se pudo cargar el historial desde Google Sheets.")
    else:
        st.info("Configura google_creds.json para ver el historial.")

# --- AUTO REFRESH ---
time.sleep(60)
st.rerun()
