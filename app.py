import streamlit as st
import pandas as pd
import requests
import time
from concurrent.futures import ThreadPoolExecutor

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="NOC Multinet", page_icon="📡", layout="wide")

# --- CONSTANTES ---
COLS_FALLA = ['onu_id', 'olt_id', 'status', 'pon_port', 'name', 'sn']
REFRESH_INTERVAL_SEC = 60

# --- SECRETS ---
try:
    URL_BASE = str(st.secrets['smartolt']['url']).strip().rstrip('/')
    TOKEN = str(st.secrets['smartolt']['token']).strip()
except KeyError:
    st.error("⚠️ Secrets no configurados. Agrega [smartolt] con 'url' y 'token' en tus secrets.")
    st.stop()

st.title("📡 Monitor de Red Multinet")

# --- FUNCIÓN PRINCIPAL DE CONSULTA ---
@st.cache_data(ttl=REFRESH_INTERVAL_SEC)
def consulta_inteligente(endpoint):
    """Prueba GET y POST para encontrar el método correcto del servidor."""
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': TOKEN}

    # 1. Intentamos con GET
    try:
        r_get = requests.get(url, headers=headers, timeout=10)
        if r_get.status_code == 200:
            data = r_get.json()
            if data.get('status') == True:
                return data.get('response')
    except (requests.RequestException, ValueError) as e:
        st.warning(f"GET falló en '{endpoint}': {e}")

    # 2. Si falló el anterior, intentamos con POST
    try:
        r_post = requests.post(url, headers=headers, timeout=10)
        if r_post.status_code == 200:
            data = r_post.json()
            if data.get('status') == True:
                return data.get('response')
    except (requests.RequestException, ValueError) as e:
        st.warning(f"POST falló en '{endpoint}': {e}")

    return None

# --- OBTENER DATOS EN PARALELO ---
with st.spinner('Conectando con la OLT...'):
    with ThreadPoolExecutor() as executor:
        f_onus = executor.submit(consulta_inteligente, "onu/get_onus_statuses")
        f_olts = executor.submit(consulta_inteligente, "olt/get_olts")
    onus = f_onus.result()
    olts = f_olts.result()

# --- MOSTRAR RESULTADOS ---
if onus is not None and isinstance(onus, list) and len(onus) > 0:
    # Métricas
    total = len(onus)
    online = len([o for o in onus if str(o.get('status', '')).lower() == 'online'])
    offline = total - online

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Clientes", total)
    c2.metric("Online ✅", online)
    c3.metric("Fallas ❌", offline, delta_color="inverse")
    st.markdown("---")

    # Tabla de fallas
    st.subheader("🔴 Detalle de Clientes Offline")
    df = pd.DataFrame(onus)

    if 'status' in df.columns:
        df_falla = df[df['status'].str.lower() != 'online'].copy()

        if not df_falla.empty:
            existentes = [c for c in COLS_FALLA if c in df_falla.columns]
            st.dataframe(df_falla[existentes], use_container_width=True, hide_index=True)
        else:
            st.success("✅ No hay fallas reportadas.")
    else:
        st.warning("⚠️ La respuesta de la API no contiene el campo 'status'. Columnas disponibles: " + str(list(df.columns)))

    # Estado de OLTs
    if olts and isinstance(olts, list):
        with st.expander("🏢 Estado de Cabeceras (OLTs)"):
            for o in olts:
                status = (o.get('status') or 'DESCONOCIDO').upper()
                st.write(f"🖥️ **{o.get('name', 'Sin nombre')}** — {status}")

elif onus is not None and isinstance(onus, list) and len(onus) == 0:
    st.warning("⚠️ La API respondió correctamente pero no devolvió ONUs.")

else:
    # --- MENSAJE DE DIAGNÓSTICO ---
    st.error("❌ No se pudo conectar con la API.")
    st.warning("⚠️ Posibles causas:")
    st.write("1. **URL en Secrets:** Debe ser exactamente `https://multinet.smartolt.com` (sin barra al final).")
    st.write("2. **Token:** Verifica que no tenga espacios al principio o al final.")
    st.write("3. **Permisos:** En tu panel de SmartOLT, la API Key debe ser 'Read & Write' o 'Read-only'.")
    st.write("4. **IP Whitelisting:** SmartOLT puede requerir que la IP de tu servidor esté en la lista blanca.")

# --- REFRESCO AUTOMÁTICO ---
time.sleep(REFRESH_INTERVAL_SEC)
st.rerun()
