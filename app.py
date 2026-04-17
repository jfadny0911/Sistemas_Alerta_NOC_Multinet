import streamlit as st
import pandas as pd
import requests
import time

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Multinet NOC", page_icon="📡", layout="wide")

# Limpieza de datos de entrada
URL_BASE = str(st.secrets['smartolt']['url']).strip().rstrip('/')
TOKEN = str(st.secrets['smartolt']['token']).strip()

st.title("📡 Monitor de Red Multinet (SmartOLT)")

def peticion_smartolt(endpoint):
    """Función centralizada para hablar con SmartOLT"""
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': TOKEN}
    try:
        # SmartOLT suele requerir POST para obtener datos
        r = requests.post(url, headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if data.get('status'):
                return data.get('response')
        return None
    except:
        return None

# --- OBTENER DATOS ---
with st.spinner('Sincronizando con SmartOLT...'):
    onus = peticion_smartolt("onu/get_all")
    olts = peticion_smartolt("system/get_olts")

if onus is not None:
    # --- MÉTRICAS ---
    total = len(onus)
    online = len([o for o in onus if str(o.get('status')).lower() == 'online'])
    offline = total - online
    
    m1, m2, m3 = st.columns(3)
    m1.metric("Clientes Totales", total)
    m2.metric("Online ✅", online)
    m3.metric("Fallas ❌", offline, delta_color="inverse")

    # --- PESTAÑAS ---
    tab_clientes, tab_olts = st.tabs(["🔴 Clientes Offline", "🏢 Estado de OLTs"])

    with tab_clientes:
        df_onus = pd.DataFrame(onus)
        # Filtramos solo los que no están online
        df_falla = df_onus[df_onus['status'].str.lower() != 'online'].copy()
        
        if not df_falla.empty:
            # Seleccionamos columnas útiles para el técnico
            columnas = ['name', 'sn', 'olt_name', 'pon_port', 'signal', 'last_online_at']
            existentes = [c for c in columnas if c in df_falla.columns]
            
            st.dataframe(
                df_falla[existentes].rename(columns={
                    'name': 'Cliente', 'sn': 'Serie', 'olt_name': 'OLT', 
                    'pon_port': 'Puerto', 'signal': 'Señal', 'last_online_at': 'Caída'
                }),
                use_container_width=True, hide_index=True
            )
        else:
            st.success("✅ No hay clientes offline en este momento.")

    with tab_olts:
        if olts:
            for o in olts:
                status = str(o.get('status')).upper()
                color = "green" if status == "ONLINE" else "red"
                st.markdown(f"**{o.get('name')}** | IP: `{o.get('ip')}` | Estado: :{color}[{status}]")
        else:
            st.info("No se pudo cargar el detalle de las OLTs.")

else:
    st.error("❌ Error de conexión.")
    st.info(f"Verifica que la URL en Secrets sea: {URL_BASE}")
    st.write("Si el problema sigue, intenta generar un nuevo API Key en tu panel de SmartOLT.")

# --- REFRESCO AUTOMÁTICO ---
time.sleep(60)
st.rerun()
