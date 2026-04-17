import streamlit as st
import pandas as pd
import requests
import time
from urllib.parse import urlparse

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Multinet Ultra-NOC", page_icon="🌐", layout="wide")

# Credenciales
try:
    URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
    TOKEN = st.secrets["smartolt"]["token"].strip()
except:
    st.error("❌ Revisa tus Secrets.")
    st.stop()

# Diccionario de coordenadas (Actualiza con tus datos reales)
MAPA_ZONAS = {
    "Conchalio": [13.4912, -89.3789],
    "San Blas": [13.4850, -89.3500],
    "Default": [13.6800, -89.1800]
}

st.title("🚀 Multinet NOC: Gestión Integral")

def llamar_api(endpoint):
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': TOKEN}
    try:
        r = requests.post(url, headers=headers, timeout=12)
        if r.status_code == 405: r = requests.get(url, headers=headers, timeout=12)
        if r.status_code == 200:
            res = r.json()
            return res.get('response') if res.get('status') else None
    except: return None
    return None

# --- CARGA DE DATOS ---
with st.spinner('Extrayendo inteligencia de red...'):
    onus = llamar_api("onu/get_onus_statuses")
    olts = llamar_api("system/get_olts")
    zonas = llamar_api("system/get_zones")
    unconfigured = llamar_api("onu/get_unconfigured")

if onus is not None:
    df = pd.DataFrame(onus)
    
    # --- LIMPIEZA DE COLUMNAS (Basado en tu reporte anterior) ---
    # Columnas recibidas: ['sn', 'olt_id', 'board', 'port', 'onu', 'zone_id', 'status', ...]
    
    # 1. TRADUCCIÓN DE ZONAS
    if zonas:
        df_z = pd.DataFrame(zonas)
        df = pd.merge(df, df_z[['id', 'name']], left_on='zone_id', right_on='id', how='left')
    else:
        df['name'] = "Zona " + df['zone_id'].astype(str)

    # 2. SEÑAL ÓPTICA (Manejo de error si no existe)
    tiene_signal = 'signal' in df.columns
    if tiene_signal:
        df['signal_num'] = pd.to_numeric(df['signal'], errors='coerce')
    
    # 3. IDENTIFICADOR DE PUERTO
    df['pon'] = "B" + df['board'].astype(str) + "/P" + df['port'].astype(str)

    # --- KPI'S ---
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total ONUs", len(df))
    
    online_count = len(df[df['status'].str.lower() == 'online'])
    k2.metric("Online ✅", online_count)
    
    # Solo mostramos señal crítica si la columna existe
    if tiene_signal:
        criticos = len(df[df['signal_num'] < -27])
        k3.metric("Señal Crítica", criticos, delta_color="inverse")
    else:
        k3.metric("Señal", "N/A en Status", help="Este endpoint no provee dBm")
        
    k4.metric("Por Autorizar", len(unconfigured) if unconfigured else 0)

    st.markdown("---")

    # --- CUERPO DEL DASHBOARD ---
    col_izq, col_der = st.columns([1, 1])

    with col_izq:
        st.subheader("📍 Mapa de Nodos")
        # Agrupar por nombre de zona para el mapa
        df_map = df.groupby('name').size().reset_index(name='clientes')
        map_points = []
        for _, r in df_map.iterrows():
            coords = MAPA_ZONAS.get(r['name'], MAPA_ZONAS["Default"])
            map_points.append({'lat': coords[0], 'lon': coords[1], 'size': r['clientes']})
        st.map(pd.DataFrame(map_points), size='size')

    with col_der:
        st.subheader("🏗️ Capacidad por Puerto (Saturación)")
        sat = df.groupby(['olt_id', 'pon']).size().reset_index(name='total')
        st.bar_chart(sat.set_index('pon')['total'])
        if not sat[sat['total'] >= 60].empty:
            st.warning("Hay puertos llegando al límite de 60 ONUs.")

    # --- PESTAÑAS DETALLADAS ---
    t_fallas, t_nuevas, t_hardware = st.tabs(["🔴 Fallas", "🆕 Por Autorizar", "🏢 Inventario OLTs"])

    with t_fallas:
        df_off = df[df['status'].str.lower() != 'online']
        st.dataframe(df_off[['sn', 'name', 'pon', 'last_status_change']], use_container_width=True)

    with t_nuevas:
        if unconfigured:
            st.info("ONUs detectadas en la red esperando SN:")
            st.dataframe(pd.DataFrame(unconfigured), use_container_width=True)
        else:
            st.success("No hay equipos pendientes de configuración.")

    with t_hardware:
        if olts:
            for o in olts:
                st.write(f"🖥️ **{o.get('name')}** | IP: {o.get('ip')} | Status: {o.get('status').upper()}")
        else:
            st.write("No se pudo cargar la información de hardware.")

else:
    st.error("❌ No se recibieron datos. Revisa la conexión con SmartOLT.")

# Auto-refresco
time.sleep(60)
st.rerun()
