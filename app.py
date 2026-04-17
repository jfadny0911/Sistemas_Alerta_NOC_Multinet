import streamlit as st
import pandas as pd
import requests
import gspread
import time
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="NOC Multinet - SmartOLT", page_icon="📡", layout="wide")

# 1. Limpieza profunda de la URL de tus secretos
# Esto quita espacios, barras finales y asegura el formato correcto
URL_BASE = str(st.secrets['smartolt']['url']).strip().rstrip('/')
TOKEN = str(st.secrets['smartolt']['token']).strip()
HEADERS = {'X-Token': TOKEN}

st.title("🛰️ Sistema NOC Multinet - SmartOLT")

# --- FUNCIÓN DE PRUEBA DE CONEXIÓN ---
def obtener_datos(endpoint):
    # Intentamos con /api/ y sin /api/ por si acaso
    rutas_a_probar = [
        f"{URL_BASE}/api/{endpoint}",
        f"{URL_BASE}/{endpoint}"
    ]
    
    ultimo_error = ""
    for url in rutas_a_probar:
        try:
            # SmartOLT prefiere POST para casi todo
            r = requests.post(url, headers=HEADERS, timeout=15)
            
            # Si da 405 (el error que tienes), intentamos con GET en esa misma URL
            if r.status_code == 405:
                r = requests.get(url, headers=HEADERS, timeout=15)
            
            if r.status_code == 200:
                res = r.json()
                if res.get('status'):
                    return res.get('response', [])
                else:
                    ultimo_error = res.get('error')
            else:
                ultimo_error = f"Error {r.status_code}: {r.text}"
        except Exception as e:
            ultimo_error = str(e)
            
    st.error(f"❌ No se pudo conectar a {endpoint}. Detalle: {ultimo_error}")
    # Mostramos la URL que falló para que sepas qué está pasando
    st.info(f"Probando conexión en: {URL_BASE}")
    return None

# --- LÓGICA DE PANTALLA ---
onus = obtener_datos("onu/get_all")

if onus:
    # Estadísticas
    total = len(onus)
    online = len([o for o in onus if str(o.get('status')).lower() == 'online'])
    offline = total - online
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Clientes", total)
    col2.metric("Online ✅", online)
    col3.metric("Offline ❌", offline, delta_color="inverse")

    st.markdown("---")
    
    # Tabla de Fallas
    st.subheader("🔴 Clientes fuera de línea")
    df_off = pd.DataFrame([o for o in onus if str(o.get('status')).lower() != 'online'])
    
    if not df_off.empty:
        # Solo mostrar columnas que existan
        cols_interes = ['name', 'sn', 'olt_name', 'pon_port', 'signal']
        existentes = [c for c in cols_interes if c in df_off.columns]
        st.dataframe(df_off[existentes], use_container_width=True)
    else:
        st.success("¡Todo en orden! No hay clientes caídos.")

# --- ESTADO DE OLTS ---
with st.expander("🏢 Ver Estado de OLTs"):
    olts = obtener_datos("system/get_olts")
    if olts:
        for o in olts:
            st.write(f"🖥️ **{o.get('name')}** - IP: {o.get('ip')} - Status: {o.get('status')}")

# Auto-refresco cada 60 segundos
time.sleep(60)
st.rerun()
