import streamlit as st
import pandas as pd
import requests
import time
import numpy as np

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Multinet NOC Intelligence", page_icon="📡", layout="wide")

# 1. Credenciales (Asegúrate de que en tus Secrets la URL sea solo el dominio)
URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
TOKEN = st.secrets["smartolt"]["token"].strip()

# 2. CONFIGURACIÓN DE MAPA (Edita las coordenadas de tus zonas aquí)
# Nombre de la Zona en SmartOLT -> [Latitud, Longitud]
COORDENADAS_ZONAS = {
    "Norte": [13.70, -89.20],
    "Sur": [13.65, -89.15],
    "Centro": [13.69, -89.21],
    "Default": [13.68, -89.18] # Coordenada base si no encuentra la zona
}

st.title("🛰️ Multinet NOC: Inteligencia de Red y Tráfico")

# --- FUNCIÓN DE CONEXIÓN ---
def llamar_smartolt(endpoint, params=None):
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': TOKEN}
    try:
        # Intentamos con POST
        r = requests.post(url, headers=headers, json=params, timeout=15)
        if r.status_code == 405:
            r = requests.get(url, headers=headers, params=params, timeout=15)
            
        if r.status_code == 200:
            res = r.json()
            return res.get('response') if res.get('status') else None
    except:
        return None
    return None

# --- OBTENCIÓN DE DATOS ---
with st.spinner('Sincronizando datos masivos...'):
    onus = llamar_smartolt("onu/get_onus_statuses")
    olts = llamar_smartolt("system/get_olts")

if onus and olts:
    # --- PROCESAMIENTO DE DATOS ---
    df_onus = pd.DataFrame(onus)
    
    # A. Cálculo de Saturación por Puerto
    # Agrupamos por OLT y Puerto para contar clientes
    saturacion = df_onus.groupby(['olt_name', 'pon_port']).size().reset_index(name='clientes')
    # Definimos 60 como límite de saturación (puedes cambiarlo)
    LIMITE_PON = 60
    puertos_saturados = saturacion[saturacion['clientes'] >= LIMITE_PON]

    # B. Preparación de Datos para el Mapa
    map_data = []
    for o in olts:
        nombre_olt = o.get('name', 'Desconocida')
        # Buscamos si el nombre de la OLT contiene alguna de nuestras zonas
        lat, lon = COORDENADAS_ZONAS["Default"]
        for zona, coords in COORDENADAS_ZONAS.items():
            if zona.lower() in nombre_olt.lower():
                lat, lon = coords
                break
        
        map_data.append({
            "name": nombre_olt,
            "latitude": lat,
            "longitude": lon,
            "status": o.get('status')
        })
    df_mapa = pd.DataFrame(map_data)

    # --- DISEÑO DEL DASHBOARD ---
    
    # Fila 1: Métricas de Tráfico y Saturación
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total ONUs", len(df_onus))
    with col2:
        online = len(df_onus[df_onus['status'].lower() == 'online'])
        st.metric("Clientes Online", online)
    with col3:
        st.metric("Puertos Críticos", len(puertos_saturados), delta="Saturación >60", delta_color="inverse")
    with col4:
        # Nota: El tráfico total real requiere sumar los puertos, aquí mostramos un estimado o estado
        st.metric("OLTs Activas", len([o for o in olts if o.get('status') == 'online']))

    # Fila 2: Mapa y Saturación
    c_mapa, c_sat = st.columns([2, 1])
    
    with c_mapa:
        st.subheader("📍 Ubicación Real de OLTs")
        st.map(df_mapa, latitude="latitude", longitude="longitude", color="#FF0000" if "offline" in str(df_mapa['status']) else "#00FF00")

    with c_sat:
        st.subheader("⚠️ Puertos Saturados")
        if not puertos_saturados.empty:
            st.warning("Los siguientes puertos están al límite:")
            st.table(puertos_saturados.rename(columns={'olt_name': 'OLT', 'pon_port': 'Puerto', 'clientes': 'ONUs'}))
        else:
            st.success("Carga de puertos balanceada.")

    # Fila 3: Detalle de Tráfico y Fallas
    tab1, tab2 = st.tabs(["📊 Tráfico por OLT", "🔴 Clientes Offline"])
    
    with tab1:
        st.subheader("Consumo de Megas por Puerto (Estimado por Clientes)")
        # Gráfico de barras de clientes por puerto como indicador de carga
        st.bar_chart(saturacion.set_index('pon_port')['clientes'])
        st.info("💡 Tip: Para ver Megas reales (Mbps), SmartOLT requiere consultar el tráfico puerto por puerto vía SNMP o API de Tráfico Individual.")

    with tab2:
        df_off = df_onus[df_onus['status'].lower() != 'online']
        st.dataframe(df_off[['name', 'sn', 'olt_name', 'pon_port', 'signal', 'last_online_at']], use_container_width=True)

else:
    st.error("No se pudo obtener la información. Verifica la API y el Token.")

# Auto-refresco
time.sleep(60)
st.rerun()
