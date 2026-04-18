import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Multinet NOC - Reporte Global", page_icon="📊", layout="wide")

# 1. Credenciales
try:
    URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
    SMART_TOKEN = st.secrets["smartolt"]["token"].strip()
    TG_TOKEN = st.secrets["telegram"]["token"]
    TG_CHAT = st.secrets["telegram"]["chat_id"]
except Exception as e:
    st.error(f"❌ Error en Secrets: {e}")
    st.stop()

# --- MEMORIA DE ESTADO (Para no repetir el mismo reporte exacto) ---
if 'ultimo_hash_fallas' not in st.session_state:
    st.session_state.ultimo_hash_fallas = ""

st.title("🛰️ Multinet NOC: Reporte de Incidencias Detallado")

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

# --- PROCESO DE ANÁLISIS ---
with st.spinner('Generando reporte de red...'):
    onus = llamar_api("onu/get_onus_statuses")

if onus is not None:
    df = pd.DataFrame(onus)
    df['PUERTO'] = "B" + df['board'].astype(str) + "/P" + df['port'].astype(str)
    df['CLIENTE'] = df['onu'].fillna(df['sn'])
    
    # Filtramos solo los caídos
    df_off = df[df['status'].str.lower() != 'online'].copy()
    
    # Creamos un "Identificador" de la falla actual para saber si algo cambió
    hash_actual = str(sorted(df_off['sn'].tolist()))
    
    if hash_actual != st.session_state.ultimo_hash_fallas:
        if not df_off.empty:
            # --- CONSTRUCCIÓN DEL REPORTE EXTENSO ---
            ahora = datetime.now().strftime('%d/%m/%Y %H:%M')
            reporte = f"🚨 *INFORME GLOBAL DE INCIDENCIAS*\n📅 _Fecha: {ahora}_\n"
            reporte += "------------------------------------------\n\n"
            
            # Agrupamos por OLT y Puerto
            olts_afectadas = df_off['olt_id'].unique()
            
            for olt in olts_afectadas:
                reporte += f"🏢 *OLT:* {olt}\n"
                df_olt = df_off[df_off['olt_id'] == olt]
                
                puertos_afectados = df_olt['PUERTO'].unique()
                for p in puertos_afectados:
                    df_p = df_olt[df_olt['PUERTO'] == p]
                    cant = len(df_p)
                    reporte += f"  🔌 *Puerto:* {p} ({cant} caídos)\n"
                    
                    # Listamos los nombres (IDs) de los clientes en ese puerto
                    nombres = ", ".join(df_p['CLIENTE'].astype(str).tolist())
                    reporte += f"  👤 _Clientes:_ {nombres}\n"
                reporte += "\n"
            
            reporte += "------------------------------------------\n"
            reporte += f"📉 *TOTAL RED OFFLINE:* {len(df_off)} clientes."
            
            # Enviar a Telegram
            enviar_tg(reporte)
        else:
            # Si ya no hay fallas y antes había, avisamos que la red está limpia
            if st.session_state.ultimo_hash_fallas != "":
                enviar_tg("✅ *RED RESTABLECIDA TOTALMENTE*\nTodos los servicios están operando con normalidad.")
        
        # Guardamos el estado para no repetir
        st.session_state.ultimo_hash_fallas = hash_actual

    # --- INTERFAZ DEL DASHBOARD ---
    st.subheader("📋 Vista de Monitoreo")
    df['Estado'] = df['status'].apply(lambda x: "🟢" if str(x).lower() == 'online' else "🔴")
    st.dataframe(
        df[['Estado', 'CLIENTE', 'sn', 'PUERTO', 'status', 'last_status_change']].rename(
            columns={'CLIENTE': 'NAME (ID)', 'sn': 'Serie (SN)', 'status': 'Detalle'}
        ),
        use_container_width=True, hide_index=True
    )

    # Resumen visual en el Dashboard
    c1, c2 = st.columns(2)
    c1.metric("Clientes Totales", len(df))
    c2.metric("Total Offline", len(df_off), delta_color="inverse")

else:
    st.error("❌ No hay comunicación con SmartOLT.")

# Auto-refresco
time.sleep(60)
st.rerun()
