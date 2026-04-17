import streamlit as st
import pandas as pd
import requests
import time

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="NOC Multinet", page_icon="📡", layout="wide")

# Intentar leer secretos
try:
    URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
    TOKEN = st.secrets["smartolt"]["token"].strip()
except Exception as e:
    st.error(f"❌ Error leyendo Secrets: {e}")
    st.stop()

st.title("📡 Dashboard NOC Multinet")

def test_api():
    # SmartOLT a veces requiere /api/v1/ o solo /api/
    # Vamos a probar la ruta más estándar
    url = f"{URL_BASE}/api/onu/get_all"
    headers = {
        'X-Token': TOKEN,
        'Accept': 'application/json'
    }
    
    informe = []
    
    # Intento 1: POST
    try:
        r = requests.post(url, headers=headers, timeout=10)
        if r.status_code == 200 and r.json().get('status'):
            return r.json().get('response'), None
        informe.append(f"POST {r.status_code}: {r.text[:100]}")
    except Exception as e:
        informe.append(f"Error POST: {str(e)}")

    # Intento 2: GET (por si tu versión de SmartOLT es distinta)
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200 and r.json().get('status'):
            return r.json().get('response'), None
        informe.append(f"GET {r.status_code}: {r.text[:100]}")
    except Exception as e:
        informe.append(f"Error GET: {str(e)}")
        
    return None, informe

# --- EJECUCIÓN ---
with st.spinner('Validando acceso a SmartOLT...'):
    datos, errores = test_api()

if datos:
    # --- SI FUNCIONA, MOSTRAR DASHBOARD ---
    onus = datos
    total = len(onus)
    online = len([o for o in onus if str(o.get('status')).lower() == 'online'])
    offline = total - online
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Clientes Totales", total)
    c2.metric("Online ✅", online)
    c3.metric("Fallas ❌", offline, delta_color="inverse")
    
    st.subheader("🔴 Lista de Clientes Offline")
    df = pd.DataFrame(onus)
    df_off = df[df['status'].str.lower() != 'online'].copy()
    if not df_off.empty:
        st.dataframe(df_off[['name', 'sn', 'olt_name', 'signal']], use_container_width=True)
    else:
        st.success("✅ No hay clientes offline.")
else:
    # --- SI FALLA, MOSTRAR DIAGNÓSTICO ---
    st.error("❌ Fallo total de conexión")
    with st.expander("🔍 Ver Informe Técnico de Errores"):
        st.write("Estamos intentando conectar a:", f"`{URL_BASE}/api/onu/get_all` text")
        for err in errores:
            st.code(err)
    
    st.info("""
    **¿Qué revisar ahora?**
    1. Ve a tu panel de SmartOLT -> Settings -> API Key.
    2. Verifica que el Token sea exactamente el mismo.
    3. Asegúrate de que **Allowed IPs** diga `0.0.0.0`.
    4. Si usas Streamlit Cloud, dale al botón **"Reboot App"** (abajo a la derecha) para asegurar que leyó los nuevos secretos.
    """)

if st.button('🔄 Reintentar'):
    st.rerun()
