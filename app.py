import streamlit as st
import pandas as pd
import requests
import time

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="NOC Multinet", page_icon="📡", layout="wide")

# 1. Limpieza de URL y Token desde los Secrets
URL_BASE = str(st.secrets['smartolt']['url']).strip().rstrip('/')
TOKEN = str(st.secrets['smartolt']['token']).strip()

st.title("📡 Dashboard NOC Multinet")

def llamar_api(endpoint):
    """Prueba la conexión de forma agresiva"""
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': TOKEN}
    
    # Intentamos primero con POST (Estándar de SmartOLT)
    try:
        r = requests.post(url, headers=headers, timeout=12)
        if r.status_code == 200:
            res = r.json()
            if res.get('status'): return res.get('response')
        
        # Si da 405, intentamos con GET
        if r.status_code == 405:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code == 200:
                res = r.json()
                if res.get('status'): return res.get('response')
                
        # Si llegamos aquí, mostramos el error técnico para debug
        st.sidebar.error(f"Error técnico en {endpoint}: {r.status_code}")
        st.sidebar.write(f"Respuesta: {r.text}")
    except Exception as e:
        st.sidebar.error(f"Falla de red: {e}")
    return None

# --- OBTENER DATOS ---
with st.spinner('Consultando SmartOLT...'):
    onus = llamar_api("onu/get_all")
    olts = llamar_api("system/get_olts")

# --- INTERFAZ DE USUARIO ---
if onus is not None:
    # Métricas
    total = len(onus)
    online = len([o for o in onus if str(o.get('status')).lower() == 'online'])
    offline = total - online
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Clientes", total)
    c2.metric("Online ✅", online)
    c3.metric("Fallas ❌", offline, delta_color="inverse")

    st.markdown("---")

    # Tabla de fallas
    st.subheader("🔴 Clientes fuera de línea")
    df = pd.DataFrame(onus)
    df_off = df[df['status'].str.lower() != 'online'].copy()
    
    if not df_off.empty:
        # Mostramos columnas clave
        cols = [c for c in ['name', 'sn', 'olt_name', 'pon_port', 'signal'] if c in df_off.columns]
        st.dataframe(df_off[cols], use_container_width=True, hide_index=True)
    else:
        st.success("✅ Todos los clientes están navegando correctamente.")

    # OLTs
    if olts:
        with st.expander("🏢 Ver estado de OLTs"):
            for o in olts:
                st.write(f"🖥️ **{o.get('name')}** - Status: {o.get('status')}")

else:
    # ESTO SALDRÁ SI SIGUE EL ERROR
    st.error("❌ No hay conexión con la API.")
    st.info("💡 REVISA ESTO:")
    st.write(f"1. Tu URL actual es: `{URL_BASE}`")
    st.write(f"2. Tu Token termina en: `...{TOKEN[-4:]}`")
    st.write("3. Asegúrate de que en SmartOLT, la API Key no tenga restricciones de IP (debe decir `0.0.0.0`).")

# Refresco cada minuto
time.sleep(60)
st.rerun()
