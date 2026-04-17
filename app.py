import streamlit as st
import pandas as pd
import requests
import time

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="NOC Multinet - SmartOLT", page_icon="📡", layout="wide")

# 1. Carga de Secretos con Limpieza
try:
    URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
    TOKEN = st.secrets["smartolt"]["token"].strip()
except Exception as e:
    st.error("❌ No se encontraron los secretos [smartolt] en la configuración.")
    st.stop()

st.title("📡 Dashboard NOC Multinet")

def llamar_smartolt(endpoint):
    # Usamos el endpoint que encontraste: onu/get_onus_statuses
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': TOKEN}
    
    try:
        # Probamos con POST (estándar de SmartOLT)
        r = requests.post(url, headers=headers, timeout=15)
        
        # Si el servidor prefiere GET, hacemos el cambio automático
        if r.status_code == 405:
            r = requests.get(url, headers=headers, timeout=15)
            
        if r.status_code == 200:
            res = r.json()
            if res.get('status'):
                return res.get('response')
            else:
                st.sidebar.warning(f"Respuesta SmartOLT: {res.get('error')}")
        else:
            st.sidebar.error(f"Error {r.status_code} en {endpoint}")
    except Exception as e:
        st.sidebar.error(f"Error de red: {e}")
    return None

# --- OBTENCIÓN DE DATOS ---
with st.spinner('Sincronizando estados de ONUs...'):
    # CAMBIO CLAVE: Usando el endpoint correcto
    onus = llamar_smartolt("onu/get_onus_statuses")
    olts = llamar_smartolt("system/get_olts")

# --- INTERFAZ ---
if onus is not None:
    # Procesar datos
    total = len(onus)
    online = len([o for o in onus if str(o.get('status')).lower() == 'online'])
    offline = total - online
    
    # Métricas principales
    c1, c2, c3 = st.columns(3)
    c1.metric("Clientes Totales", total)
    c2.metric("Online ✅", online)
    c3.metric("Fallas ❌", offline, delta_color="inverse")

    st.markdown("---")

    # Tabla de fallas
    st.subheader("🔴 Clientes fuera de línea")
    df = pd.DataFrame(onus)
    
    # En este endpoint, SmartOLT a veces usa nombres de columnas distintos
    # Filtramos por status != online
    df_off = df[df['status'].str.lower() != 'online'].copy()
    
    if not df_off.empty:
        # Intentamos mostrar las columnas más útiles
        columnas_posibles = ['name', 'sn', 'olt_name', 'pon_port', 'signal', 'last_online_at']
        existentes = [c for c in columnas_posibles if c in df_off.columns]
        st.dataframe(df_off[existentes], use_container_width=True, hide_index=True)
    else:
        st.success("✅ No se detectan clientes offline en este momento.")

    # OLTs
    if olts:
        with st.expander("🏢 Estado de Cabeceras (OLTs)"):
            for o in olts:
                st.write(f"🖥️ **{o.get('name')}** - Status: {o.get('status')}")
else:
    st.error("❌ Conexión fallida.")
    st.info(f"Estamos consultando a: `{URL_BASE}/api/onu/get_onus_statuses`")
    st.write("Verifica que el API Key tenga permisos suficientes en el panel de SmartOLT.")

# Refresco automático
time.sleep(60)
st.rerun()
