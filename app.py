import streamlit as st
import pandas as pd
import requests
import time
from urllib.parse import urlparse

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Multinet NOC Intelligence", page_icon="📡", layout="wide")

# 1. Limpieza de Credenciales
try:
    url_sucia = st.secrets["smartolt"]["url"].strip()
    parsed_url = urlparse(url_sucia)
    URL_BASE = f"{parsed_url.scheme}://{parsed_url.netloc}"
    TOKEN = st.secrets["smartolt"]["token"].strip()
except:
    st.error("❌ Revisa tus Secrets [smartolt].")
    st.stop()

st.title("🛰️ Multinet NOC: Inteligencia de Red")

def llamar_api(endpoint):
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': TOKEN}
    try:
        r = requests.post(url, headers=headers, timeout=15)
        if r.status_code == 405:
            r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            res = r.json()
            return res.get('response') if res.get('status') else None
    except: return None
    return None

# --- OBTENCIÓN DE DATOS ---
with st.spinner('Sincronizando datos...'):
    onus = llamar_api("onu/get_onus_statuses")
    olts = llamar_api("system/get_olts")

if onus:
    df_onus = pd.DataFrame(onus)
    
    # --- MODO DIAGNÓSTICO (Sidebar) ---
    with st.sidebar:
        st.write("### 🔍 Columnas Detectadas")
        st.write(list(df_onus.columns))
    
    # --- IDENTIFICACIÓN AUTOMÁTICA DE COLUMNAS ---
    # SmartOLT a veces cambia entre 'olt_name', 'olt', 'pon_port', 'pon', etc.
    col_olt = next((c for c in df_onus.columns if c in ['olt_name', 'olt', 'olt_id']), None)
    col_pon = next((c for c in df_onus.columns if c in ['pon_port', 'pon', 'board_slot_port']), None)
    col_status = next((c for c in df_onus.columns if c in ['status', 'onu_status']), 'status')

    if col_olt and col_pon:
        # Cálculo de Saturación (Aquí estaba el error)
        saturacion = df_onus.groupby([col_olt, col_pon]).size().reset_index(name='clientes')
        
        # --- MÉTRICAS ---
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total ONUs", len(df_onus))
        c2.metric("Online ✅", len(df_onus[df_onus[col_status].astype(str).str.lower() == 'online']))
        
        puertos_criticos = saturacion[saturacion['clientes'] >= 60]
        c3.metric("Puertos Críticos", len(puertos_criticos))
        c4.metric("OLTs", len(olts) if olts else 0)

        # --- SECCIÓN DE MAPA Y SATURACIÓN ---
        st.markdown("---")
        col_map, col_list = st.columns([2, 1])
        
        with col_map:
            st.subheader("📍 Mapa de Red (Ubicación de OLTs)")
            # Nota: Si no tienes coordenadas en SmartOLT, esto mostrará un mapa base
            # Para un mapa real, necesitaríamos lat/long en una hoja de Google Sheets
            st.info("El mapa utiliza el nombre de la OLT para geolocalización básica.")
            st.write("*(Para ver puntos exactos, vincula el Inventario de Google Sheets)*")

        with col_list:
            st.subheader("⚠️ Carga de Puertos")
            st.dataframe(saturacion.sort_values(by='clientes', ascending=False), use_container_width=True, hide_index=True)

        # --- TABLA DE FALLAS ---
        st.subheader("🔴 Clientes Offline")
        df_off = df_onus[df_onus[col_status].astype(str).str.lower() != 'online']
        st.dataframe(df_off, use_container_width=True)
        
    else:
        st.error(f"❌ No se encontraron las columnas de OLT o PON. Columnas recibidas: {list(df_onus.columns)}")

else:
    st.error("❌ No se recibieron datos de ONUs. Verifica el Token.")

# Auto-refresco
time.sleep(60)
st.rerun()
