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

# Conexión Segura a Google Sheets
def conectar_gsheets():
    try:
        # En GitHub/Streamlit Cloud, usaremos st.secrets para las credenciales de Google
        # o el archivo google_creds.json si lo subes (Cuidado con la privacidad)
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
                "inline_keyboard": [[
                    {"text": "🙋‍♂️ Asignarme", "callback_data": f"asignar_{device_id}"},
                    {"text": "✅ Solucionado", "callback_data": f"ok_{device_id}"}
                ]]
            })
        requests.post(url, json=payload, timeout=10)
        return True
    except: return False

st.title("🖥️ Multinet NOC Intelligence System")

# Carga de Datos
gc = conectar_gsheets()
if gc:
    sh = gc.open(NOMBRE_SHEET)
    df_inv = pd.DataFrame(sh.get_worksheet(0).get_all_records())
    df_logs = pd.DataFrame(sh.worksheet("Log_Fallas").get_all_records())
else:
    df_inv = df_logs = pd.DataFrame()

# API LibreNMS
try:
    headers = {'X-Auth-Token': st.secrets['librenms']['token']}
    r = requests.get(f"{st.secrets['librenms']['url']}/devices", headers=headers, timeout=10)
    dispositivos = r.json().get('devices', [])
except: dispositivos = []

caidos = [d for d in dispositivos if str(d.get('status')) == "0"]

tab1, tab2 = st.tabs(["🔴 Monitor de Fallas", "📈 Historial y Usuarios"])

with tab1:
    if caidos:
        st.error(f"🚨 {len(caidos)} Equipos fuera de línea")
        datos_tabla = []
        for d in caidos:
            nombre = d.get('purpose') or d.get('sysName') or d.get('hostname')
            ip = str(d.get('ip', '')).strip()
            ubicacion = d.get('location', 'N/A')
            
            # Buscar responsable en Excel
            resp = "Sin asignar"
            if not df_inv.empty:
                m = df_inv[df_inv['IP'] == ip]
                if not m.empty: resp = m.iloc[0]['Responsable']

            # Buscar Atención en Logs
            estado = "⌛ Pendiente"
            if not df_logs.empty:
                f = df_logs[(df_logs['Ip'] == ip) & (df_logs['Evento (DOWN / UP)'].str.upper() == 'ASIGNADO')]
                if not f.empty: estado = f.iloc[-1]['Duracion']

            datos_tabla.append({
                "DISPOSITIVO": nombre,
                "DIRECCIÓN IP": ip,
                "UBICACIÓN / RESPONSABLE": f"{ubicacion} | {resp}",
                "ESTADO DE ATENCIÓN": estado
            })
        
        st.dataframe(pd.DataFrame(datos_tabla), use_container_width=True, hide_index=True)
    else:
        st.success("✅ Red Operativa")

with tab2:
    st.subheader("Administración de Usuarios")
    if not df_logs.empty:
        # Ver carga por técnico
        tecnicos = df_logs['Duracion'].unique()
        sel = st.selectbox("Filtrar por Técnico:", tecnicos)
        st.table(df_logs[df_logs['Duracion'] == sel].tail(5))

time.sleep(60)
st.rerun()
