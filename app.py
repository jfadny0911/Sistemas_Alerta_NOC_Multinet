import streamlit as st
import pandas as pd
import requests
import time
from urllib.parse import urlparse

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Multinet NOC Intelligence", page_icon="📡", layout="wide")

# Credenciales
URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
TOKEN = st.secrets["smartolt"]["token"].strip()

# --- CONFIGURACIÓN DE COORDENADAS (PON AQUÍ EL GPS REAL) ---
# He sacado estos nombres de tu captura de pantalla
MAPA_ZONAS = {
    "Conchalio": [13.4912, -89.3789],
    "Conchalito": [13.4890, -89.3820],
    "Islas de San Blas": [13.4850, -89.3500],
    "Islas El Encanto": [13.4820, -89.3400],
    "Julupe": [13.5000, -89.4000],
    "La Puntilla": [13.3000, -88.9000],
    "Laguna Sur": [13.4000, -89.1000],
    "Default": [13.5000, -89.3000] # Punto medio por si no hay match
}

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
with st.spinner('Sincronizando con SmartOLT...'):
    onus = llamar_api("onu/get_onus_statuses")
    olts = llamar_api("system/get_olts")
    zonas_lista = llamar_api("system/get_zones") # Traemos los nombres de las zonas

if onus and zonas_lista:
    df_onus = pd.DataFrame(onus)
    df_zonas = pd.DataFrame(zonas_lista) # Contiene 'id' y 'name'

    # 1. Unimos ONUs con Nombres de Zonas
    # Convertimos zone_id a string para asegurar el match
    df_onus['zone_id'] = df_onus['zone_id'].astype(str)
    df_zonas['id'] = df_zonas['id'].astype(str)
    
    # Cruzamos datos para tener el nombre de la zona en el dataframe de clientes
    df = pd.merge(df_onus, df_zonas[['id', 'name']], left_on='zone_id', right_on='id', how='left')
    
    # 2. Preparar datos para el Mapa
    stats_zonas = df.groupby('name').size().reset_index(name='total_clientes')
    
    map_data = []
    for index, row in stats_zonas.iterrows():
        nombre = row['name']
        coords = MAPA_ZONAS.get(nombre, MAPA_ZONAS["Default"])
        map_data.append({
            'name': nombre,
            'lat': coords[0],
            'lon': coords[1],
            'clientes': row['total_clientes']
        })
    df_mapa = pd.DataFrame(map_data)

    # --- MÉTRICAS ---
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total ONUs", len(df))
    online = len(df[df['status'].str.lower() == 'online'])
    c2.metric("Online ✅", online)
    c3.metric("Fallas ❌", len(df) - online, delta_color="inverse")
    
    # Saturación
    df['pon'] = "B" + df['board'].astype(str) + "/P" + df['port'].astype(str)
    sat = df.groupby(['olt_id', 'pon']).size().reset_index(name='cnt')
    c4.metric("Puertos >60", len(sat[sat['cnt'] >= 60]))

    # --- MAPA REAL ---
    st.subheader("📍 Mapa de Distribución por Zonas")
    st.map(df_mapa, latitude='lat', longitude='lon', size='clientes', color="#29b5e8")

    # --- DETALLE DE PUERTOS Y SATURACIÓN ---
    st.markdown("---")
    col_izq, col_der = st.columns(2)
    
    with col_izq:
        st.subheader("📊 Carga de Clientes por Puerto PON")
        st.bar_chart(sat.set_index('pon')['cnt'])
    
    with col_der:
        st.subheader("⚠️ Top Puertos Saturados")
        st.dataframe(sat.sort_values(by='cnt', ascending=False).head(10), use_container_width=True, hide_index=True)

    # --- TABLA DE FALLAS ---
    with st.expander("🔍 Detalle de Clientes Offline"):
        df_off = df[df['status'].str.lower() != 'online']
        st.dataframe(df_off[['sn', 'name', 'pon', 'last_status_change']], use_container_width=True)

else:
    st.error("No se pudo obtener la lista de zonas o clientes.")

time.sleep(60)
st.rerun()
