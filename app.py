import streamlit as st
import pandas as pd
import requests
import time
from urllib.parse import urlparse

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Multinet Ultra-NOC", page_icon="🌐", layout="wide")

# Credenciales con manejo de errores
try:
    URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
    TOKEN = st.secrets["smartolt"]["token"].strip()
except:
    st.error("❌ Configura los Secrets [smartolt] correctamente.")
    st.stop()

# Coordenadas (Asegúrate de que coincidan con los nombres en tu captura)
MAPA_ZONAS = {
    "Conchalio": [13.4912, -89.3789],
    "San Blas": [13.4850, -89.3500],
    "El Encanto": [13.4820, -89.3400],
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
    
    # TRADUCCIÓN DE ZONAS
    if zonas:
        df_z = pd.DataFrame(zonas)
        df_z['id'] = df_z['id'].astype(str)
        df['zone_id'] = df['zone_id'].astype(str)
        df = pd.merge(df, df_z[['id', 'name']], left_on='zone_id', right_on='id', how='left')
    else:
        df['name'] = "Zona " + df['zone_id'].astype(str)

    df['pon'] = "B" + df['board'].astype(str) + "/P" + df['port'].astype(str)

    # --- KPI'S ---
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total ONUs", len(df))
    
    # Manejo seguro de status para el conteo
    online_count = len(df[df['status'].fillna('').str.lower() == 'online'])
    k2.metric("Online ✅", online_count)
    
    # Identificar puertos saturados
    sat = df.groupby(['olt_id', 'pon']).size().reset_index(name='total')
    puertos_llenos = len(sat[sat['total'] >= 60])
    k3.metric("Puertos Sat.", puertos_llenos, delta=">60 ONUs", delta_color="inverse")
        
    k4.metric("Nuevas (Unconf)", len(unconfigured) if unconfigured else 0)

    st.markdown("---")

    # --- CUERPO DEL DASHBOARD ---
    col_izq, col_der = st.columns([1, 1])

    with col_izq:
        st.subheader("📍 Mapa de Nodos")
        # Limpieza de nombres para el mapa
        df['name'] = df['name'].fillna('Desconocida')
        df_map = df.groupby('name').size().reset_index(name='clientes')
        map_points = []
        for _, r in df_map.iterrows():
            coords = MAPA_ZONAS.get(r['name'], MAPA_ZONAS["Default"])
            map_points.append({'lat': coords[0], 'lon': coords[1], 'size': r['clientes']})
        st.map(pd.DataFrame(map_points), size='size')

    with col_der:
        st.subheader("🏗️ Carga por Puerto")
        st.bar_chart(sat.set_index('pon')['total'])

    # --- PESTAÑAS DETALLADAS ---
    t_fallas, t_nuevas, t_hardware = st.tabs(["🔴 Fallas Actuales", "🆕 Por Autorizar", "🏢 Inventario OLTs"])

    with t_fallas:
        df_off = df[df['status'].fillna('').str.lower() != 'online']
        if not df_off.empty:
            st.dataframe(df_off[['sn', 'name', 'pon', 'last_status_change']], use_container_width=True)
        else:
            st.success("Red limpia. Cero fallas detectadas.")

    with t_nuevas:
        if unconfigured:
            st.info("Equipos detectados esperando configuración:")
            st.dataframe(pd.DataFrame(unconfigured), use_container_width=True)
        else:
            st.write("No hay equipos pendientes.")

    with t_hardware:
        if olts:
            for o in olts:
                # SOLUCIÓN AL ATTRIBUTE ERROR: Manejo seguro de strings
                n_olt = o.get('name') or 'OLT Desconocida'
                ip_olt = o.get('ip') or 'N/A'
                st_olt = str(o.get('status') or 'offline').upper()
                
                c_status = "green" if st_olt == "ONLINE" else "red"
                st.markdown(f"🖥️ **{n_olt}** | IP: `{ip_olt}` | Estado: :{c_status}[{st_olt}]")
        else:
            st.warning("No se recibió información de las OLTs.")

else:
    st.error("❌ Sin conexión con la API de SmartOLT.")

# Refresh
time.sleep(60)
st.rerun()
