import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Multinet NOC - Hybrid Intelligence", page_icon="📡", layout="wide")

# 1. Credenciales
try:
    URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
    SMART_TOKEN = st.secrets["smartolt"]["token"].strip()
    TG_TOKEN = st.secrets["telegram"]["token"]
    TG_CHAT = st.secrets["telegram"]["chat_id"]
except:
    st.error("❌ Revisa tus Secrets [smartolt] y [telegram].")
    st.stop()

# --- MEMORIA DE SESIÓN ---
if 'registro_caidas' not in st.session_state: st.session_state.registro_caidas = {}
if 'nombres_cache' not in st.session_state: st.session_state.nombres_cache = {}
if 'df_avanzado' not in st.session_state: st.session_state.df_avanzado = None

st.title("🛰️ Multinet NOC: Gestión Híbrida Inteligente")

# --- FUNCIONES CORE ---
def enviar_tg(mensaje):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TG_CHAT, "text": mensaje, "parse_mode": "Markdown"})

def llamar_api(endpoint, timeout=15):
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': SMART_TOKEN}
    try:
        r = requests.post(url, headers=headers, timeout=timeout)
        if r.status_code == 405: r = requests.get(url, headers=headers, timeout=timeout)
        return r.json().get('response') if r.status_code == 200 else None
    except: return None

# --- BARRA LATERAL: ESCANEO DE SEÑALES ---
with st.sidebar:
    st.header("⚙️ Herramientas Pro")
    st.write("Si el modo avanzado falla, usa este botón para forzar la lectura de dBm y Nombres.")
    if st.button("🔍 Realizar Escaneo Profundo (dBm)"):
        with st.spinner("Consultando señales ópticas... (Puede tardar)"):
            data_pro = llamar_api("onu/get_all", timeout=60) # Timeout largo de 1 min
            if data_pro:
                st.session_state.df_avanzado = pd.DataFrame(data_pro)
                # Guardamos nombres en caché
                for _, r in st.session_state.df_avanzado.iterrows():
                    st.session_state.nombres_cache[r['sn']] = r.get('name', r['sn'])
                st.success("✅ ¡Datos de señal y nombres actualizados!")
            else:
                st.error("❌ El servidor SmartOLT sigue sin responder a la consulta pesada.")

# --- PROCESO DE MONITOREO RÁPIDO (Dashboard) ---
with st.spinner('Sincronizando estado de red...'):
    onus_raw = llamar_api("onu/get_onus_statuses")
    unconfigured = llamar_api("onu/get_unconfigured")
    olts = llamar_api("system/get_olts")

if onus_raw:
    df = pd.DataFrame(onus_raw)
    df['PUERTO'] = "B" + df['board'].astype(str) + "/P" + df['port'].astype(str)
    # Buscamos el nombre en el caché si existe, si no usamos el SN
    df['CLIENTE'] = df['sn'].apply(lambda x: st.session_state.nombres_cache.get(x, x))
    
    # 1. LÓGICA DE ALERTAS INTELIGENTES (Mismo nivel que antes)
    df_off = df[df['status'].str.lower() != 'online'].copy()
    ahora_dt = datetime.now()
    
    for _, row in df.iterrows():
        sn, nombre = row['sn'], row['CLIENTE']
        status = str(row['status']).lower()
        
        if status != 'online' and sn not in st.session_state.registro_caidas:
            st.session_state.registro_caidas[sn] = ahora_dt
            # Detectar causa
            causa = "🔌 Desconexión / Energía" if "pwfail" in status else "✂️ Corte de Fibra (LOS)"
            enviar_tg(f"🔴 *FALLA*\n👤 {nombre}\n📍 Puerto: {row['PUERTO']}\n❓ Causa: {causa}")
            
        elif status == 'online' and sn in st.session_state.registro_caidas:
            inicio = st.session_state.registro_caidas[sn]
            duracion = str(ahora_dt - inicio).split('.')[0]
            enviar_tg(f"✅ *RECUPERADO*\n👤 {nombre}\n⏳ Tiempo fuera: {duracion}")
            del st.session_state.registro_caidas[sn]

    # --- INTERFAZ ---
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total ONUs", len(df))
    k2.metric("Online ✅", len(df) - len(df_off))
    k3.metric("Offline ❌", len(df_off), delta_color="inverse")
    k4.metric("Nuevas 🆕", len(unconfigured) if unconfigured else 0)

    st.markdown("---")
    t_mon, t_signal, t_hw = st.tabs(["🖥️ Monitor Principal", "📡 Radar de Señal", "🏢 Salud de OLTs"])

    with t_mon:
        st.subheader("Estado de Clientes en Tiempo Real")
        df['Icon'] = df['status'].apply(lambda x: "🟢" if str(x).lower() == 'online' else "🔴")
        st.dataframe(df[['Icon', 'CLIENTE', 'sn', 'PUERTO', 'status', 'last_status_change']], use_container_width=True, hide_index=True)

    with t_signal:
        if st.session_state.df_avanzado is not None:
            st.subheader("Análisis Óptico (Último Escaneo)")
            df_adv = st.session_state.df_avanzado
            df_adv['signal_num'] = pd.to_numeric(df_adv['signal'], errors='coerce')
            
            # Mostrar solo los que están críticos
            criticos = df_adv[df_adv['signal_num'] < -27]
            if not criticos.empty:
                st.error(f"⚠️ {len(criticos)} clientes con señal crítica")
                st.dataframe(criticos[['name', 'sn', 'signal', 'status']], use_container_width=True)
            else:
                st.success("Toda la red tiene niveles de señal aceptables.")
        else:
            st.info("💡 Haz clic en 'Realizar Escaneo Profundo' en la barra lateral para ver los niveles de señal (dBm).")

    with t_hw:
        if olts:
            for o in olts:
                st_olt = str(o.get('status')).lower()
                color = "green" if st_olt in ['online', 'up', '1'] else "red"
                st.markdown(f"🏢 **{o.get('name')}** | IP: `{o.get('ip')}` | Estado: :{color}[{st_olt.upper()}]")

else:
    st.error("❌ Sin conexión a SmartOLT.")

time.sleep(60)
st.rerun()
