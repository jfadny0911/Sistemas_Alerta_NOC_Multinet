import streamlit as st
import pandas as pd
import requests
import time
from urllib.parse import urlparse

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Multinet NOC Intelligence", page_icon="📡", layout="wide")

# 1. Credenciales
URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
TOKEN = st.secrets["smartolt"]["token"].strip()

# 2. MAPA DE COORDINADAS POR ZONE_ID
# Reemplaza los números (1, 2, 3) por los IDs de zona que veas en tu SmartOLT
ZONAS_GPS = {
    "1": [13.69, -89.21], # Ejemplo: Zona San Salvador
    "2": [13.71, -89.20], # Ejemplo: Zona Norte
    "default": [13.68, -89.18]
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

if onus:
    df = pd.DataFrame(onus)
    
    # --- PROCESAMIENTO DE SATURACIÓN ---
    # Creamos una columna única de Puerto PON combinando Board y Port
    df['pon_completo'] = "B-" + df['board'].astype(str) + "/P-" + df['port'].astype(str)
    
    # Agrupamos para ver cuántos clientes hay por puerto
    sat = df.groupby(['olt_id', 'pon_completo']).size().reset_index(name='clientes')
    sat['estado'] = sat['clientes'].apply(lambda x: "🔴 CRÍTICO" if x >= 60 else ("🟡 ALTA" if x >= 45 else "🟢 OK"))

    # --- MÉTRICAS PRINCIPALES ---
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Clientes", len(df))
    online = len(df[df['status'].str.lower() == 'online'])
    c2.metric("Online ✅", online)
    c3.metric("Fallas ❌", len(df) - online, delta_color="inverse")
    c4.metric("Puertos Saturados", len(sat[sat['clientes'] >= 60]))

    st.markdown("---")

    # --- SECCIÓN DE MAPA ---
    st.subheader("📍 Mapa de Estado por Zonas")
    
    # Preparamos datos del mapa basados en zone_id
    map_list = []
    for zone, coords in ZONAS_GPS.items():
        count = len(df[df['zone_id'].astype(str) == zone])
        if count > 0:
            map_list.append({
                'lat': coords[0], 'lon': coords[1], 
                'clientes': count, 'zona': f"Zona ID: {zone}"
            })
    
    if map_list:
        st.map(pd.DataFrame(map_list), latitude='lat', longitude='lon', size='clientes')
    else:
        st.info("Configura los IDs de tus zonas en el código para ver el mapa.")

    # --- SECCIÓN DE TRÁFICO Y PUERTOS ---
    st.markdown("---")
    col_izq, col_der = st.columns([1, 1])

    with col_izq:
        st.subheader("📊 Carga por Puerto (Saturación)")
        # Gráfico de carga
        st.bar_chart(sat.set_index('pon_completo')['clientes'])
        st.dataframe(sat.sort_values(by='clientes', ascending=False), use_container_width=True, hide_index=True)

    with col_der:
        st.subheader("📉 Tráfico Estimado")
        st.info("Nota: La API `get_onus_statuses` no devuelve Mbps reales por puerto.")
        st.write("Carga estimada según densidad de clientes:")
        # Simulación de carga (Mbps estimados: clientes * 5Mbps de promedio)
        sat['Mbps_Estimados'] = sat['clientes'] * 5 
        st.line_chart(sat.set_index('pon_completo')['Mbps_Estimados'])

    # --- TABLA DE FALLAS ---
    with st.expander("🔍 Ver Detalle de Clientes Offline"):
        df_off = df[df['status'].str.lower() != 'online']
        st.dataframe(df_off[['sn', 'olt_id', 'board', 'port', 'last_status_change']], use_container_width=True)

else:
    st.error("No se recibieron datos. Verifica el Token.")

# Refresh
time.sleep(60)
st.rerun()
