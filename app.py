import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Multinet NOC - Soporte & Altas", page_icon="🔧", layout="wide")

# 1. Credenciales
try:
    URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
    SMART_TOKEN = st.secrets["smartolt"]["token"].strip()
    TG_TOKEN = st.secrets["telegram"]["token"]
    TG_CHAT = st.secrets["telegram"]["chat_id"]
except:
    st.error("❌ Revisa los Secrets.")
    st.stop()

# --- MEMORIA TÉCNICA (Persistencia) ---
if 'registro_caidas' not in st.session_state: st.session_state.registro_caidas = {}
if 'nombres_cache' not in st.session_state: st.session_state.nombres_cache = {}

st.title("🔧 Multinet NOC: Soporte y Gestión de Bajas/Altas")

# --- FUNCIONES ---
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

# --- SIDEBAR: GESTIÓN DE CACHÉ ---
with st.sidebar:
    st.header("⚙️ Gestión de Soporte")
    if st.button("♻️ Refrescar Base de Datos (Nombres)"):
        with st.spinner("Sincronizando clientes actuales..."):
            data_all = llamar_api("onu/get_all", timeout=60)
            if data_all:
                # Limpiamos caché viejo para eliminar ONUs borradas
                st.session_state.nombres_cache = {str(r['sn']): r.get('name', r['sn']) for r in data_all}
                st.success("Base de datos de nombres actualizada.")
            else: st.error("No se pudo conectar con la base de datos avanzada.")

# --- PROCESO DE MONITOREO ---
with st.spinner('Actualizando vista de red...'):
    onus_raw = llamar_api("onu/get_onus_statuses")
    unconfigured = llamar_api("onu/get_unconfigured")

if onus_raw:
    df = pd.DataFrame(onus_raw)
    df['sn'] = df['sn'].astype(str)
    df['PUERTO'] = "B" + df['board'].astype(str) + "/P" + df['port'].astype(str)
    df['CLIENTE'] = df['sn'].apply(lambda x: st.session_state.nombres_cache.get(x, x))
    
    sn_actuales = set(df['sn'].tolist())
    ahora_dt = datetime.now()

    # --- LÓGICA INTELIGENTE DE BAJAS Y CAMBIOS ---
    # 1. Limpieza de ONUs eliminadas (Si estaba en caídas pero ya no existe en la OLT)
    sns_en_memoria = list(st.session_state.registro_caidas.keys())
    for sn_memoria in sns_en_memoria:
        if sn_memoria not in sn_actuales:
            # La ONU fue eliminada de SmartOLT por soporte
            del st.session_state.registro_caidas[sn_memoria]

    # 2. Procesamiento de Alertas
    for _, row in df.iterrows():
        sn, nombre, status = row['sn'], row['CLIENTE'], str(row['status']).lower()
        
        if status != 'online' and sn not in st.session_state.registro_caidas:
            st.session_state.registro_caidas[sn] = ahora_dt
            enviar_tg(f"🔴 *FALLA:* {nombre}\n🔌 Puerto: {row['PUERTO']}\n⚠️ Status: {status.upper()}")
            
        elif status == 'online' and sn in st.session_state.registro_caidas:
            inicio = st.session_state.registro_caidas[sn]
            duracion = str(ahora_dt - inicio).split('.')[0]
            enviar_tg(f"✅ *RECUPERADO:* {nombre}\n⏳ Estuvo fuera: {duracion}")
            del st.session_state.registro_caidas[sn]

    # --- INTERFAZ ---
    k1, k2, k3 = st.columns(3)
    k1.metric("Online ✅", len(df[df['status']=='online']))
    k2.metric("Offline ❌", len(df[df['status']!='online']))
    k3.metric("Por Autorizar 🆕", len(unconfigured) if unconfigured else 0)

    tab_soporte, tab_nuevas = st.tabs(["👥 Gestión de Clientes", "🆕 Nuevas (Para Autorizar)"])

    with tab_soporte:
        st.subheader("Buscador de Soporte")
        busc = st.text_input("Buscar por SN o Nombre para verificar estado")
        df_view = df.copy()
        if busc:
            df_view = df_view[df_view['sn'].contains(busc, case=False) | df_view['CLIENTE'].contains(busc, case=False)]
        
        df_view['Estado'] = df_view['status'].apply(lambda x: "🟢 Online" if x=='online' else "🔴 Offline")
        st.dataframe(df_view[['Estado', 'CLIENTE', 'sn', 'PUERTO', 'last_status_change']], use_container_width=True, hide_index=True)

    with tab_nuevas:
        st.subheader("ONUs detectadas en campo (Sin Autorizar)")
        if unconfigured:
            st.warning("⚠️ Hay equipos esperando autorización. Dale a 'Refrescar' después de agregarlos.")
            st.dataframe(pd.DataFrame(unconfigured), use_container_width=True)
        else:
            st.success("No hay equipos pendientes. ¡Todo el soporte está al día!")

else:
    st.error("❌ Error de comunicación con SmartOLT.")

time.sleep(60)
st.rerun()
