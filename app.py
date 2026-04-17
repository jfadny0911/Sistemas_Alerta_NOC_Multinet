import streamlit as st
import pandas as pd
import requests
import gspread
import time
import json
from datetime import datetime, timedelta

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Multinet NOC Intelligence", page_icon="📊", layout="wide")
NOMBRE_SHEET = "Inventario_NOC"

# --- CONEXIÓN A GOOGLE SHEETS ---
def conectar_gsheets():
    try:
        return gspread.service_account(filename='google_creds.json')
    except Exception as e:
        st.error(f"❌ Error conectando a Google Sheets: {e}")
        return None

# --- FUNCIÓN DE TELEGRAM ---
def enviar_telegram(mensaje, device_id=None):
    try:
        token = st.secrets["telegram"]["token"]
        chat_id = st.secrets["telegram"]["chat_id"]
        
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": mensaje, "parse_mode": "Markdown"}
        
        if device_id:
            payload["reply_markup"] = json.dumps({
                "inline_keyboard": [[
                    {"text": "🙋‍♂️ Asignarme", "callback_data": f"asignar_{device_id}"},
                    {"text": "✅ Solucionado", "callback_data": f"ok_{device_id}"}
                ]]
            })
            
        respuesta = requests.post(url, json=payload, timeout=10)
        return respuesta.status_code == 200
    except Exception as e:
        st.error(f"❌ Error enviando mensaje a Telegram: {e}")
        return False

# --- INICIO DEL DASHBOARD ---
st.title("🖥️ Multinet NOC Intelligence System (SmartOLT Edition)")

if 'ultima_notif' not in st.session_state:
    st.session_state.ultima_notif = {}

gc = conectar_gsheets()
if gc:
    try:
        sh = gc.open(NOMBRE_SHEET)
        df_inv = pd.DataFrame(sh.get_worksheet(0).get_all_records())
        df_logs = pd.DataFrame(sh.worksheet("Log_Fallas").get_all_records())
    except:
        df_inv = df_logs = pd.DataFrame()
else:
    df_inv = df_logs = pd.DataFrame()

# --- CONEXIÓN A SMARTOLT ---
olts_caidas = []
try:
    # Endpoint oficial de SmartOLT para listar las OLTs
    url_api = f"{st.secrets['smartolt']['url']}/api/system/get_olts"
    headers = {'X-Token': st.secrets['smartolt']['token']} # Autenticación SmartOLT
    
    r = requests.get(url_api, headers=headers, timeout=15)
    
    if r.status_code == 200:
        respuesta_json = r.json()
        
        # SmartOLT suele enviar los datos dentro de un bloque 'response'
        lista_olts = respuesta_json.get('response', []) if isinstance(respuesta_json, dict) else respuesta_json
        
        # Filtramos los que estén caídos (ajusta 'status' según como te lo devuelva tu OLT)
        for olt in lista_olts:
            estado = str(olt.get('status', '')).lower()
            if estado == 'offline' or estado == 'down' or estado == '0':
                olts_caidas.append(olt)
    else:
        st.error(f"❌ Error SmartOLT ({r.status_code}): Revisa tu URL o API Key.")
except KeyError as e:
    st.error(f"❌ Falla en secretos: Falta la configuración de SmartOLT ({e}).")
except Exception as e:
    st.warning(f"⚠️ Error de red conectando a SmartOLT: {e}")

# --- INTERFAZ WEB ---
tab1, tab2 = st.tabs(["🔴 Monitor de OLTs", "📈 Historial y Usuarios"])

with tab1:
    if olts_caidas:
        st.error(f"🚨 {len(olts_caidas)} OLT(s) fuera de línea detectadas en SmartOLT")
        datos_tabla = []
        ahora = datetime.now()

        for d in olts_caidas:
            did = str(d.get('id', 'N/A'))
            nombre = str(d.get('name', 'OLT Desconocida'))
            ip = str(d.get('ip', 'Sin IP')).strip()
            
            # Buscar responsable
            resp = "Sin asignar"
            if not df_inv.empty and 'IP' in df_inv.columns:
                m = df_inv[df_inv['IP'] == ip]
                if not m.empty: resp = m.iloc[0]['Responsable']

            # Buscar estatus en Telegram
            estado_tel = "⌛ Pendiente"
            if not df_logs.empty:
                f = df_logs[(df_logs['Ip'] == ip) & (df_logs['Evento (DOWN / UP)'].str.upper() == 'ASIGNADO')]
                if not f.empty: estado_tel = f.iloc[-1]['Duracion']

            # Alerta a Telegram
            ultima = st.session_state.ultima_notif.get(did)
            if ultima is None or (ahora - ultima) > timedelta(minutes=30):
                msg_alerta = (
                    f"🔴 *FALLA DE OLT DETECTADA (SmartOLT)*\n\n"
                    f"🖥 *Equipo:* {nombre}\n"
                    f"🌐 *IP:* {ip}\n"
                    f"👤 *Responsable:* {resp}\n\n"
                    f"⚠️ Por favor, asigne un técnico usando el botón."
                )
                if enviar_telegram(msg_alerta, device_id=did):
                    st.session_state.ultima_notif[did] = ahora

            datos_tabla.append({
                "OLT AFECTADA": nombre,
                "DIRECCIÓN IP": ip,
                "ZONA / RESPONSABLE": resp,
                "ESTADO DE ATENCIÓN": estado_tel
            })
        
        st.dataframe(pd.DataFrame(datos_tabla), use_container_width=True, hide_index=True)
    else:
        st.success("✅ SmartOLT Reporta: Todas las OLTs operativas.")

with tab2:
    st.subheader("Administración de Usuarios e Historial")
    if not df_logs.empty:
        tecnicos = df_logs['Duracion'].unique()
        sel = st.selectbox("Selecciona un técnico para ver su actividad:", tecnicos)
        st.dataframe(df_logs[df_logs['Duracion'] == sel].tail(10), use_container_width=True)
    else:
        st.info("Aún no hay registros de fallas.")

time.sleep(60)
st.rerun()
