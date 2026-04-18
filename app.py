import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Multinet NOC - Inteligencia Artificial", page_icon="🧠", layout="wide")

# Credenciales
try:
    URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
    SMART_TOKEN = st.secrets["smartolt"]["token"].strip()
    TG_TOKEN = st.secrets["telegram"]["token"]
    TG_CHAT = st.secrets["telegram"]["chat_id"]
except Exception as e:
    st.error(f"❌ Error en Secrets: {e}")
    st.stop()

# --- MEMORIA DE ESTADO ---
if 'registro_caidas' not in st.session_state:
    st.session_state.registro_caidas = {}
if 'alertas_enviadas' not in st.session_state:
    st.session_state.alertas_enviadas = set()

st.title("🛰️ Multinet NOC: Inteligencia de Red Activa")

# --- FUNCIONES NÚCLEO ---
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
    diff = fin - inicio
    h, rem = divmod(diff.total_seconds(), 3600)
    m, _ = divmod(rem, 60)
    return f"{int(h)}h {int(m)}m" if h > 0 else f"{int(m)}m"

# --- PROCESO ANALÍTICO ---
with st.spinner('Analizando patrones de falla...'):
    onus = llamar_api("onu/get_onus_statuses")
    zonas_raw = llamar_api("system/get_zones")
    olts = llamar_api("system/get_olts")

if onus is not None:
    df = pd.DataFrame(onus)
    df['PUERTO'] = "B" + df['board'].astype(str) + "/P" + df['port'].astype(str)
    df['CLIENTE'] = df['onu'].fillna(df['sn'])
    ahora_dt = datetime.now()

    # 1. Mapeo de Zonas
    df_z = pd.DataFrame(zonas_raw) if zonas_raw else pd.DataFrame()
    if not df_z.empty:
        df_z['id'] = df_z['id'].astype(str)
        df['zone_id'] = df['zone_id'].astype(str)
        df = pd.merge(df, df_z[['id', 'name']], left_on='zone_id', right_on='id', how='left')
        df['ZONA_TXT'] = df['name'].fillna("Sin Zona")
    else:
        df['ZONA_TXT'] = "Zona " + df['zone_id'].astype(str)

    # 2. IDENTIFICACIÓN DE FALLAS MASIVAS (Inteligencia)
    df_off = df[df['status'].str.lower() != 'online'].copy()
    
    # Agrupamos por OLT y Puerto para detectar fallas de infraestructura
    fallas_por_puerto = df_off.groupby(['olt_id', 'PUERTO']).size().reset_index(name='cuenta')
    puertos_masivos = fallas_por_puerto[fallas_por_puerto['cuenta'] >= 3] # Umbral: 3 ONUs

    # --- LÓGICA DE NOTIFICACIÓN INTELIGENTE ---
    # Revisamos cada puerto con falla masiva
    for _, f in puertos_masivos.iterrows():
        id_alerta = f"MASSIVE_{f['olt_id']}_{f['PUERTO']}"
        if id_alerta not in st.session_state.alertas_enviadas:
            df_p = df_off[(df_off['olt_id'] == f['olt_id']) & (df_off['PUERTO'] == f['PUERTO'])]
            zona_p = df_p['ZONA_TXT'].iloc[0]
            
            msg = f"💥 *FALLA MASIVA DETECTADA*\n"
            msg += f"📍 *Zona:* {zona_p}\n"
            msg += f"🏢 *OLT:* {f['olt_id']}\n"
            msg += f"🔌 *Puerto:* {f['PUERTO']}\n"
            msg += f"📉 *Impacto:* {f['cuenta']} clientes afectados.\n"
            msg += f"⚠️ *Diagnóstico:* Posible corte de fibra o falla de energía en el sector."
            enviar_tg(msg)
            st.session_state.alertas_enviadas.add(id_alerta)

    # Revisamos caídas individuales
    for _, row in df_off.iterrows():
        sn = row['sn']
        status = str(row['status']).lower()
        
        # Si no es parte de una falla masiva ya reportada
        id_p = f"MASSIVE_{row['olt_id']}_{row['PUERTO']}"
        if id_p not in st.session_state.alertas_enviadas:
            if sn not in st.session_state.registro_caidas:
                st.session_state.registro_caidas[sn] = ahora_dt
                
                # Inteligencia de causa
                causa = "Desconexión de Equipo (Manual/Energía)" if "pwfail" in status or "dying" in status else "Falla de Fibra Drop (LOS)"
                
                msg = f"👤 *FALLA INDIVIDUAL*\n"
                msg += f"📝 *ID:* {row['CLIENTE']}\n"
                msg += f"🆔 *SN:* `{sn}`\n"
                msg += f"📍 *Zona:* {row['ZONA_TXT']}\n"
                msg += f"❓ *Posible causa:* {causa}"
                enviar_tg(msg)

    # 3. LÓGICA DE RECUPERACIÓN (SLA)
    for sn in list(st.session_state.registro_caidas.keys()):
        # Si el cliente ya no está en la lista de offline
        if sn not in df_off['sn'].values:
            hora_inicio = st.session_state.registro_caidas[sn]
            duracion = calcular_duracion(hora_inicio, ahora_dt)
            cliente_info = df[df['sn'] == sn].iloc[0]
            
            msg = f"✅ *SERVICIO RECUPERADO*\n"
            msg += f"👤 *Cliente:* {cliente_info['CLIENTE']}\n"
            msg += f"⏳ *Tiempo Offline:* {duracion}\n"
            msg += f"📍 *Zona:* {cliente_info['ZONA_TXT']}"
            enviar_tg(msg)
            del st.session_state.registro_caidas[sn]

    # Limpiar alertas masivas si el puerto se recupera
    for alert_id in list(st.session_state.alertas_enviadas):
        if alert_id.startswith("MASSIVE"):
            _, olt, port = alert_id.split("_", 2)
            # Si ya no hay falla masiva en ese puerto (menos de 2 caídos)
            if len(df_off[(df_off['olt_id'] == olt) & (df_off['PUERTO'] == port)]) < 2:
                enviar_tg(f"✅ *PUERTO RESTABLECIDO*\nEl puerto {port} en OLT {olt} vuelve a estar operativo.")
                st.session_state.alertas_enviadas.remove(alert_id)

    # --- INTERFAZ VISUAL ---
    st.subheader("📋 Resumen de Inteligencia")
    c1, c2, c3 = st.columns(3)
    c1.metric("Online ✅", len(df) - len(df_off))
    c2.metric("Offline ❌", len(df_off), delta_color="inverse")
    c3.metric("Fallas Masivas", len(puertos_masivos), delta_color="inverse")

    st.dataframe(
        df[['status', 'CLIENTE', 'sn', 'ZONA_TXT', 'PUERTO']].rename(
            columns={'status': 'Estado SmartOLT', 'CLIENTE': 'Nombre/ID'}
        ), use_container_width=True, hide_index=True
    )

else:
    st.error("No se pudo conectar a SmartOLT.")

time.sleep(60)
st.rerun()
