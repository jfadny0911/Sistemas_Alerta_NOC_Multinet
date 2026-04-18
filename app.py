import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Multinet NOC - SLA Monitor", page_icon="⏱️", layout="wide")

# 1. Credenciales
try:
    URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
    SMART_TOKEN = st.secrets["smartolt"]["token"].strip()
    TG_TOKEN = st.secrets["telegram"]["token"]
    TG_CHAT = st.secrets["telegram"]["chat_id"]
except Exception as e:
    st.error(f"❌ Error en Secrets: {e}")
    st.stop()

# --- MEMORIA DE TIEMPOS (Para calcular duración de caída) ---
# Guardamos { "SN": "Hora de inicio de la caída" }
if 'registro_caidas' not in st.session_state:
    st.session_state.registro_caidas = {}

st.title("🛰️ Multinet NOC: Monitor de Cortes y Tiempos de Inactividad")

# --- FUNCIONES ---
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

def calcular_duracion(inicio, fin):
    """Calcula la diferencia de tiempo amigable"""
    diff = fin - inicio
    horas, rem = divmod(diff.total_seconds(), 3600)
    minutos, _ = divmod(rem, 60)
    if horas > 0:
        return f"{int(horas)}h {int(minutos)}m"
    return f"{int(minutos)}m"

# --- PROCESO DE DATOS ---
with st.spinner('Analizando historial de estados...'):
    onus = llamar_api("onu/get_onus_statuses")
    zonas_raw = llamar_api("system/get_zones")
    olts = llamar_api("system/get_olts")

if onus is not None:
    df = pd.DataFrame(onus)
    df['PUERTO'] = "B" + df['board'].astype(str) + "/P" + df['port'].astype(str)
    df['CLIENTE'] = df['onu'].fillna(df['sn'])
    
    # 1. Unir con nombres de Zonas
    if zonas_raw:
        df_z = pd.DataFrame(zonas_raw)
        df_z['id'] = df_z['id'].astype(str)
        df['zone_id'] = df['zone_id'].astype(str)
        df = pd.merge(df, df_z[['id', 'name']], left_on='zone_id', right_on='id', how='left')
        df['ZONA_TXT'] = df['name'].fillna("Sin Zona")
    else:
        df['ZONA_TXT'] = "Zona ID: " + df['zone_id'].astype(str)

    # --- LÓGICA DE ALERTAS Y TIEMPOS ---
    ahora_dt = datetime.now()
    df_off = df[df['status'].str.lower() != 'online'].copy()

    for _, row in df.iterrows():
        sn = row['sn']
        nombre = row['CLIENTE']
        zona = row['ZONA_TXT']
        status = str(row['status']).lower()
        es_online = status == 'online'

        # DETECTAR NUEVA CAÍDA
        if not es_online and sn not in st.session_state.registro_caidas:
            # Guardamos la hora de inicio (Desde cuándo está caído)
            st.session_state.registro_caidas[sn] = ahora_dt
            
            msg = f"🔴 *FALLA DETECTADA*\n"
            msg += f"👤 *Cliente:* {nombre}\n"
            msg += f"🆔 *SN:* `{sn}`\n"
            msg += f"📍 *Zona:* {zona}\n"
            msg += f"🔌 *Puerto:* {row['PUERTO']}\n"
            msg += f"⏱ *Desde:* {ahora_dt.strftime('%H:%M')}"
            enviar_tg(msg)

        # DETECTAR RECUPERACIÓN (Cálculo de tiempo total)
        elif es_online and sn in st.session_state.registro_caidas:
            hora_inicio = st.session_state.registro_caidas[sn]
            tiempo_fuera = calcular_duracion(hora_inicio, ahora_dt)
            
            msg = f"✅ *SERVICIO RESTABLECIDO*\n"
            msg += f"👤 *Cliente:* {nombre}\n"
            msg += f"🆔 *SN:* `{sn}`\n"
            msg += f"📍 *Zona:* {zona}\n"
            msg += f"⏳ *Tiempo fuera:* {tiempo_fuera}\n"
            msg += f"✨ *Estado:* Online ahora."
            enviar_tg(msg)
            
            # Limpiamos de la memoria de caídas
            del st.session_state.registro_caidas[sn]

    # --- REPORTE GLOBAL (Similar a la imagen de PON Outage) ---
    with st.sidebar:
        if st.button("🚀 Enviar Reporte Global de Outages"):
            if not df_off.empty:
                reporte = f"📡 *PON OUTAGE REPORT*\n"
                reporte += "----------------------------------\n"
                # Agrupamos por OLT y Puerto
                for olt_id in df_off['olt_id'].unique():
                    nombre_olt = next((o.get('name') for o in olts if str(o.get('id')) == str(olt_id)), olt_id) if olts else olt_id
                    reporte += f"🏢 *OLT:* {nombre_olt}\n"
                    
                    df_p_off = df_off[df_off['olt_id'] == olt_id]
                    for p in df_p_off['PUERTO'].unique():
                        df_final = df_p_off[df_p_off['PUERTO'] == p]
                        zona_p = df_final['ZONA_TXT'].iloc[0]
                        # Calculamos tiempo promedio de este grupo
                        reporte += f"  📍 *Zona:* {zona_p}\n"
                        reporte += f"  🔌 *Port:* {p} ({len(df_final)} ONUs)\n"
                        reporte += f"  👤 *IDs:* {', '.join(df_final['CLIENTE'].astype(str).tolist())}\n"
                    reporte += "\n"
                enviar_tg(reporte)
            else:
                enviar_tg("✅ *RED OK:* No se detectan puertos con fallas.")

    # --- DASHBOARD VISUAL ---
    k1, k2, k3 = st.columns(3)
    k1.metric("Online ✅", len(df) - len(df_off))
    k2.metric("Offline 🔴", len(df_off), delta_color="inverse")
    k3.metric("Fallas de Puerto", len(df_off['PUERTO'].unique()) if not df_off.empty else 0)

    st.subheader("📋 Estado Detallado (Similar a SmartOLT)")
    df['Downtime'] = df['sn'].apply(lambda x: calcular_duracion(st.session_state.registro_caidas[x], ahora_dt) if x in st.session_state.registro_caidas else "---")
    
    st.dataframe(
        df[['status', 'CLIENTE', 'sn', 'ZONA_TXT', 'PUERTO', 'Downtime']].rename(
            columns={'status': 'Estado', 'CLIENTE': 'Nombre (Name)', 'Downtime': 'Tiempo Caído'}
        ),
        use_container_width=True, hide_index=True
    )

else:
    st.error("Error al conectar con SmartOLT.")

time.sleep(60)
st.rerun()
