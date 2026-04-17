import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Multinet Ultra-NOC", page_icon="🌐", layout="wide")

# 1. Credenciales
try:
    URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
    TOKEN = st.secrets["smartolt"]["token"].strip()
except:
    st.error("❌ Configura los Secrets [smartolt] correctamente.")
    st.stop()

# 2. Coordenadas de Zonas (Copia los nombres de tu captura)
# Reemplaza con las coordenadas reales de tus nodos
MAPA_ZONAS = {
    "San Pedro Masahuat": [13.5436, -89.0403],
    "Conchalio": [13.4912, -89.3789],
    "San Blas": [13.4850, -89.3500],
    "El Encanto": [13.4820, -89.3400],
    "Default": [13.6800, -89.1800]
}

st.title("🚀 Multinet NOC: Gestión Integral SmartOLT")

# --- MOTOR DE API ---
def llamar_api(endpoint):
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': TOKEN}
    try:
        r = requests.post(url, headers=headers, timeout=20)
        if r.status_code == 405: r = requests.get(url, headers=headers, timeout=20)
        if r.status_code == 200:
            res = r.json()
            return res.get('response') if res.get('status') else None
    except: return None
    return None

# --- CARGA MASIVA ---
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
        df['Zona'] = df['name'].fillna("Sin Zona")
    else:
        df['Zona'] = df['zone_id']

    # LIMPIEZA Y FORMATO
    df['Estado'] = df['status'].apply(lambda x: "🟢 ONLINE" if str(x).lower() == 'online' else "🔴 OFFLINE")
    df['pon'] = "B" + df['board'].astype(str) + "/P" + df['port'].astype(str)
    
    # --- FILA 1: KPI'S GLOBALES ---
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Base Instalada", len(df))
    online_total = len(df[df['status'].str.lower() == 'online'])
    k2.metric("Clientes Online", online_total)
    k3.metric("Clientes Offline", len(df) - online_total, delta_color="inverse")
    k4.metric("Nuevas por Autorizar", len(unconfigured) if unconfigured else 0)

    st.markdown("---")

    # --- FILA 2: PESTAÑAS OPERATIVAS ---
    tab_list, tab_map, tab_sat, tab_hw, tab_new = st.tabs([
        "👥 Lista de Clientes", 
        "📍 Mapa de Red", 
        "🏗️ Saturación PON", 
        "🏢 Estado OLTs",
        "🆕 Nuevas ONUs"
    ])

    with tab_list:
        st.subheader("🔍 Buscador Maestro de Clientes")
        busqueda = st.text_input("Buscar por SN o ID", placeholder="Ej: HWTC... o 20260397")
        
        df_view = df.copy()
        if busqueda:
            df_view = df_view[
                (df_view['sn'].str.contains(busqueda, case=False)) | 
                (df_view['onu'].str.contains(busqueda, case=False))
            ]
        
        # Tabla detallada como la de SmartOLT
        st.dataframe(
            df_view[['onu', 'sn', 'Estado', 'Zona', 'pon', 'last_status_change']].rename(
                columns={'onu': 'Nombre/ID', 'sn': 'Número de Serie', 'pon': 'Puerto PON', 'last_status_change': 'Último Cambio'}
            ),
            use_container_width=True, hide_index=True
        )

    with tab_map:
        st.subheader("📍 Distribución Geográfica por Zonas")
        # Agrupar para el mapa
        df_map = df.groupby('Zona').size().reset_index(name='total')
        map_points = []
        for _, r in df_map.iterrows():
            coords = MAPA_ZONAS.get(r['Zona'], MAPA_ZONAS["Default"])
            map_points.append({'lat': coords[0], 'lon': coords[1], 'size': r['total'] * 10})
        
        st.map(pd.DataFrame(map_points), latitude='lat', longitude='lon', size='size')

    with tab_sat:
        st.subheader("📊 Carga de Puertos (Capacidad)")
        sat = df.groupby(['olt_id', 'pon']).size().reset_index(name='total')
        sat['Carga %'] = (sat['total'] / 64 * 100).round(1)
        
        col_bar, col_tab = st.columns([2, 1])
        with col_bar:
            st.bar_chart(sat.set_index('pon')['total'])
        with col_tab:
            st.write("Puertos con más carga:")
            st.dataframe(sat.sort_values(by='total', ascending=False).head(10), hide_index=True)

    with tab_hw:
        st.subheader("🖥️ Salud del Hardware")
        if olts:
            for o in olts:
                n_olt = o.get('name') or 'OLT'
                st_raw = str(o.get('status') or 'offline').upper()
                color = "green" if st_raw == "ONLINE" else "red"
                with st.expander(f"OLT: {n_olt} - {o.get('ip')}"):
                    st.markdown(f"**Estado:** :{color}[{st_raw}]")
                    st.write(f"**Modelo:** {o.get('hardware_version', 'N/A')}")
        else:
            st.info("No se pudo obtener información detallada de las OLTs.")

    with tab_new:
        st.subheader("🆕 ONUs Detectadas (Pendientes de Autorizar)")
        if unconfigured:
            df_un = pd.DataFrame(unconfigured)
            st.success(f"Se han detectado {len(df_un)} equipos nuevos.")
            st.dataframe(df_un[['sn', 'olt_id', 'board', 'port', 'model']], use_container_width=True)
        else:
            st.write("No hay equipos nuevos esperando en la red.")

else:
    st.error("❌ No se pudo conectar a la API. Revisa tus credenciales.")

# Refresco
time.sleep(60)
st.rerun()
