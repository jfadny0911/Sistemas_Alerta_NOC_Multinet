import streamlit as st
import pandas as pd
import requests
import time
from urllib.parse import urlparse

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Multinet NOC - Clientes", page_icon="📡", layout="wide")

# Credenciales
URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
TOKEN = st.secrets["smartolt"]["token"].strip()

st.title("🛰️ Multinet NOC: Gestión de Clientes y Estados")

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

# --- CARGA DE DATOS ---
with st.spinner('Sincronizando base de datos de clientes...'):
    # Usamos get_onus_statuses para velocidad y get_zones para nombres
    onus = llamar_api("onu/get_onus_statuses")
    zonas = llamar_api("system/get_zones")

if onus is not None:
    df = pd.DataFrame(onus)
    
    # 1. TRADUCCIÓN DE ZONAS (Para que diga "San Pedro Masahuat")
    if zonas:
        df_z = pd.DataFrame(zonas)
        df_z['id'] = df_z['id'].astype(str)
        df['zone_id'] = df['zone_id'].astype(str)
        df = pd.merge(df, df_z[['id', 'name']], left_on='zone_id', right_on='id', how='left')
        df['Zona'] = df['name'].fillna("Sin Zona")
    else:
        df['Zona'] = df['zone_id']

    # 2. LIMPIEZA DE DATOS
    # El campo 'onu' suele traer el ID o Nombre que buscas
    df['Cliente_ID'] = df['onu'].fillna(df['sn']) 
    df['Estado'] = df['status'].apply(lambda x: "🟢 ONLINE" if str(x).lower() == 'online' else "🔴 OFFLINE")

    # --- BUSCADOR Y FILTROS ---
    st.markdown("### 🔍 Buscador de Clientes")
    col_bus, col_zon = st.columns([2, 1])
    
    with col_bus:
        busqueda = st.text_input("Buscar por SN o Nombre de Cliente", placeholder="Ej: HWTC78F5... o 20260397")
    
    with col_zon:
        lista_zonas = ["Todas"] + sorted(df['Zona'].unique().tolist())
        zona_sel = st.selectbox("Filtrar por Zona", lista_zonas)

    # Aplicar Filtros
    df_filtrado = df.copy()
    if busqueda:
        df_filtrado = df_filtrado[
            (df_filtrado['sn'].str.contains(busqueda, case=False)) | 
            (df_filtrado['Cliente_ID'].str.contains(busqueda, case=False))
        ]
    if zona_sel != "Todas":
        df_filtrado = df_filtrado[df_filtrado['Zona'] == zona_sel]

    # --- TABLA MAESTRA ---
    st.markdown("---")
    st.subheader(f"📋 Listado de Clientes ({len(df_filtrado)})")
    
    # Preparamos la tabla final
    tabla_display = df_filtrado[['Cliente_ID', 'sn', 'Estado', 'Zona', 'last_status_change']].copy()
    tabla_display.columns = ['Nombre / ONU', 'Número de Serie (SN)', 'Estado Actual', 'Zona / Sector', 'Último Cambio']
    
    st.dataframe(
        tabla_display, 
        use_container_width=True, 
        hide_index=True,
        column_config={
            "Estado Actual": st.column_config.TextColumn("Estado Actual", help="🟢 Activo | 🔴 Inactivo")
        }
    )

    # --- RESUMEN RÁPIDO ---
    st.markdown("---")
    res1, res2, res3 = st.columns(3)
    res1.metric("Total en Red", len(df))
    res2.metric("Activos (Online)", len(df[df['status'].str.lower() == 'online']))
    res3.metric("Caídos (Offline)", len(df[df['status'].str.lower() != 'online']), delta_color="inverse")

else:
    st.error("❌ No se pudo conectar con SmartOLT. Revisa el Token.")

# Auto-refresco
time.sleep(60)
st.rerun()
