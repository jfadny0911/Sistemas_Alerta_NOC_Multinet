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
        # Asegúrate de que google_creds.json exista
        return gspread.service_account(filename='google_creds.json')
    except Exception as e:
        st.error(f"❌ Error conectando a Google Sheets: {e}")
        return None

# --- FUNCIÓN DE TELEGRAM (CON DIAGNÓSTICO) ---
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
        
        # Validar si Telegram lo aceptó
        if respuesta.status_code == 200:
            return True
        else:
            st.error(f"❌ Telegram rechazó el mensaje. Razón: {respuesta.text}")
            return False
            
    except KeyError as e:
        st.error(f"❌ Falla de configuración: Falta la llave {e} en tus secretos (secrets.toml).")
        return False
    except Exception as e:
        st.error(f"❌ Error desconocido al enviar mensaje de Telegram: {e}")
        return False

# --- INICIO DEL DASHBOARD ---
st.title("🖥️ Multinet NOC Intelligence System")

# Estado de notificaciones (Evita spam cada minuto)
if 'ultima_notif' not in st.session_state:
    st.session_state.ultima_notif = {}

# Carga de Datos
gc = conectar_gsheets()
if gc:
    try:
        sh = gc.open(NOMBRE_SHEET)
        df_inv = pd.DataFrame(sh.get_worksheet(0).get_all_records()) # Inventario
        df_logs = pd.DataFrame(sh.worksheet("Log_Fallas").get_all_records()) # Historial
    except Exception as e:
        st.error(f"❌ Error leyendo pestañas del Excel: {e}")
        df_inv = df_logs = pd.DataFrame()
else:
    df_inv = df_logs = pd.DataFrame()

# Llamada a LibreNMS
dispositivos = []
try:
    url_api = f"{st.secrets['librenms']['url']}/devices"
    headers = {'X-Auth-Token': st.secrets['librenms']['token']}
    r = requests.get(url_api, headers=headers, timeout=10)
    
    if r.status_code == 200:
        dispositivos = r.json().get('devices', [])
    else:
        st.error(f"❌ Error LibreNMS ({r.status_code}): {r.text}")
except KeyError as e:
    st.error(f"❌ Falla en secretos: Falta la configuración de LibreNMS ({e}).")
except Exception as e:
    st.warning(f"⚠️ Error conectando a LibreNMS: {e}")

caidos = [d for d in dispositivos if str(d.get('status')) == "0"]

tab1, tab2 = st.tabs(["🔴 Monitor de Fallas", "📈 Historial y Usuarios"])

with tab1:
    if caidos:
        st.error(f"🚨 {len(caidos)} Equipos fuera de línea")
        datos_tabla = []
        ahora = datetime.now()

        for d in caidos:
            did = str(d.get('device_id'))
            nombre = d.get('purpose') or d.get('sysName') or d.get('hostname')
            ip = str(d.get('ip', '')).strip()
            ubicacion = d.get('location', 'N/A')
            
            # 1. Buscar responsable en el Excel
            resp = "Sin asignar"
            if not df_inv.empty:
                m = df_inv[df_inv['IP'] == ip]
                if not m.empty:
                    resp = m.iloc[0]['Responsable']

            # 2. Buscar Atención en Logs de Telegram
            estado = "⌛ Pendiente"
            if not df_logs.empty:
                f = df_logs[(df_logs['Ip'] == ip) & (df_logs['Evento (DOWN / UP)'].str.upper() == 'ASIGNADO')]
                if not f.empty:
                    estado = f.iloc[-1]['Duracion']

            # 3. Disparar Alerta a Telegram
            ultima = st.session_state.ultima_notif.get(did)
            if ultima is None or (ahora - ultima) > timedelta(minutes=30):
                msg_alerta = (
                    f"🔴 *FALLA DE RED DETECTADA*\n\n"
                    f"🖥 *Host:* {nombre}\n"
                    f"🌐 *IP:* {ip}\n"
                    f"📍 *Ubicación:* {ubicacion}\n"
                    f"👤 *Responsable:* {resp}\n\n"
                    f"⚠️ Por favor, asigne un técnico usando el botón."
                )
                if enviar_telegram(msg_alerta, device_id=did):
                    st.session_state.ultima_notif[did] = ahora # Guardar hora si fue exitoso

            # Insertar en la tabla web
            datos_tabla.append({
                "DISPOSITIVO": nombre,
                "DIRECCIÓN IP": ip,
                "UBICACIÓN / RESPONSABLE": f"{ubicacion} | {resp}",
                "ESTADO DE ATENCIÓN": estado
            })
        
        st.dataframe(pd.DataFrame(datos_tabla), use_container_width=True, hide_index=True)
    else:
        st.success("✅ Red Operativa. Todos los sistemas están funcionando con normalidad.")

with tab2:
    st.subheader("Administración de Usuarios e Historial")
    if not df_logs.empty:
        # Ver carga por técnico
        st.write("**Historial filtrado por Técnico:**")
        tecnicos = df_logs['Duracion'].unique()
        sel = st.selectbox("Selecciona un técnico para ver su actividad:", tecnicos)
        st.dataframe(df_logs[df_logs['Duracion'] == sel].tail(10), use_container_width=True)
        
        st.write("**Últimos Movimientos Generales:**")
        st.dataframe(df_logs.tail(15), use_container_width=True)
    else:
        st.info("Aún no hay registros de fallas.")

# Refrescar automáticamente cada minuto
time.sleep(60)
st.rerun()
