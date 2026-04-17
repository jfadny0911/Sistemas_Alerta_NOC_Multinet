import streamlit as st
import pandas as pd
import requests
import time

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="NOC Multinet", page_icon="📡", layout="wide")

# Limpieza radical de URL y Token
URL_BASE = str(st.secrets['smartolt']['url']).strip().rstrip('/')
TOKEN = str(st.secrets['smartolt']['token']).strip()

st.title("📡 Monitor de Red Multinet")

def consulta_inteligente(endpoint):
    """Prueba GET y POST para encontrar el método correcto del servidor"""
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': TOKEN}
    
    # 1. Intentamos con GET
    try:
        r_get = requests.get(url, headers=headers, timeout=10)
        if r_get.status_code == 200:
            data = r_get.json()
            if data.get('status') == True:
                return data.get('response')
    except:
        pass

    # 2. Si falló el anterior, intentamos con POST
    try:
        r_post = requests.post(url, headers=headers, timeout=10)
        if r_post.status_code == 200:
            data = r_post.json()
            if data.get('status') == True:
                return data.get('response')
    except:
        pass
    
    return None

# --- OBTENER DATOS ---
with st.spinner('Conectando con la OLT...'):
    onus = consulta_inteligente("onu/get_all")
    olts = consulta_inteligente("system/get_olts")

# --- MOSTRAR RESULTADOS ---
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
    st.subheader("🔴 Detalle de Clientes Offline")
    df = pd.DataFrame(onus)
    df_falla = df[df['status'].str.lower() != 'online'].copy()
    
    if not df_falla.empty:
        cols = ['name', 'sn', 'olt_name', 'pon_port', 'signal']
        existentes = [c for c in cols if c in df_falla.columns]
        st.dataframe(df_falla[existentes], use_container_width=True, hide_index=True)
    else:
        st.success("No hay fallas reportadas.")

    # Estado de OLTs
    if olts:
        with st.expander("🏢 Estado de Cabeceras (OLTs)"):
            for o in olts:
                st.write(f"🖥️ **{o.get('name')}** - {o.get('status').upper()}")
else:
    # --- MENSAJE DE DIAGNÓSTICO SI NADA FUNCIONA ---
    st.error("❌ No se pudo conectar con la API.")
    st.warning("⚠️ Posibles causas:")
    st.write(f"1. **URL en Secrets:** Asegúrate de que sea exactamente `https://multinet.smartolt.com` (sin nada extra al final).")
    st.write("2. **Token:** Verifica que no tenga espacios al principio o al final.")
    st.write("3. **Permisos:** En tu panel de SmartOLT, asegúrate de que la API Key sea 'Read & Write' o 'Read-only'.")

# Refresco
time.sleep(60)
st.rerun()
