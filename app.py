import streamlit as st
import pandas as pd
import requests
import time

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Multinet NOC - Alertas Masivas", page_icon="📡", layout="wide")

# 1. Credenciales
try:
    URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
    SMART_TOKEN = st.secrets["smartolt"]["token"].strip()
    TG_TOKEN = st.secrets["telegram"]["token"]
    TG_CHAT = st.secrets["telegram"]["chat_id"]
except Exception as e:
    st.error(f"❌ Error en Secrets: {e}")
    st.stop()

# --- MEMORIA DE ALERTAS (Para no repetir mensajes) ---
if 'alertas_enviadas' not in st.session_state:
    st.session_state.alertas_enviadas = {"puertos": set(), "zonas": set()}

st.title("🛰️ Multinet NOC: Monitor de Fallas por Zona y Puerto")

# --- FUNCIONES DE APOYO ---
def enviar_tg(mensaje):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT, "text": mensaje, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def llamar_api(endpoint):
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': SMART_TOKEN}
    try:
        r = requests.post(url, headers=headers, timeout=20)
        if r.status_code == 405: r = requests.get(url, headers=headers, timeout=20)
        return r.json().get('response') if r.status_code == 200 else None
    except: return None

# --- PROCESO PRINCIPAL ---
with st.spinner('Analizando integridad de la red...'):
    onus = llamar_api("onu/get_onus_statuses")
    zonas_info = llamar_api("system/get_zones")

if onus is not None:
    df = pd.DataFrame(onus)
    
    # 1. TRADUCCIÓN DE ZONAS Y CLIENTES
    df_z = pd.DataFrame(zonas_info) if zonas_info else pd.DataFrame(columns=['id', 'name'])
    df['zone_id'] = df['zone_id'].astype(str)
    df_z['id'] = df_z['id'].astype(str)
    df = pd.merge(df, df_z[['id', 'name']], left_on='zone_id', right_on='id', how='left')
    
    # El campo NAME del cliente (Código)
    df['CLIENTE_NAME'] = df['onu'].fillna(df['sn'])
    df['PUERTO'] = "B" + df['board'].astype(str) + "/P" + df['port'].astype(str)
    df['ZONA_NOMBRE'] = df['name'].fillna("Zona " + df['zone_id'])

    # --- LÓGICA DE DETECCIÓN MASIVA ---
    df_offline = df[df['status'].str.lower() != 'online']
    
    # A. AGRUPAR POR PUERTO
    fallas_puerto = df_offline.groupby(['olt_id', 'PUERTO']).size().reset_index(name='caidos')
    # B. AGRUPAR POR ZONA
    fallas_zona = df_offline.groupby(['ZONA_NOMBRE']).size().reset_index(name='caidos')

    # --- ENVÍO DE ALERTAS INTELIGENTES ---
    
    # 🚨 Alerta por Puerto (Si hay más de 2 clientes caídos en el mismo puerto)
    for _, f in fallas_puerto.iterrows():
        id_p = f"{f['olt_id']}_{f['PUERTO']}"
        if f['caidos'] >= 3: # Umbral: 3 o más clientes es falla de puerto
            if id_p not in st.session_state.alertas_enviadas["puertos"]:
                msg = f"💥 *FALLA DE PUERTO DETECTADA*\n\n🏗️ *OLT:* {f['olt_id']}\n🔌 *Puerto:* {f['PUERTO']}\n📉 *Impacto:* {f['caidos']} clientes Offline\n⚠️ *Posible:* Corte de fibra o falla en puerto PON."
                enviar_tg(msg)
                st.session_state.alertas_enviadas["puertos"].add(id_p)
        elif f['caidos'] == 0 and id_p in st.session_state.alertas_enviadas["puertos"]:
            enviar_tg(f"✅ *PUERTO RECUPERADO*\n\n🔌 Puerto: {f['PUERTO']} (OLT {f['olt_id']}) vuelve a estar estable.")
            st.session_state.alertas_enviadas["puertos"].remove(id_p)

    # 🚨 Alerta por Zona
    for _, z in fallas_zona.iterrows():
        nombre_z = z['ZONA_NOMBRE']
        if z['caidos'] >= 5: # Umbral: 5 o más clientes es falla de zona/sector
            if nombre_z not in st.session_state.alertas_enviadas["zonas"]:
                msg = f"🚩 *FALLA GENERAL EN ZONA*\n\n📍 *Sector:* {nombre_z}\n👥 *Afectados:* {z['caidos']} clientes\n📡 *Estado:* Interrupción masiva detectada."
                enviar_tg(msg)
                st.session_state.alertas_enviadas["zonas"].add(nombre_z)
        elif z['caidos'] == 0 and nombre_z in st.session_state.alertas_enviadas["zonas"]:
            enviar_tg(f"✅ *ZONA RESTABLECIDA*\n\n📍 Sector: {nombre_z} ya no presenta fallas masivas.")
            st.session_state.alertas_enviadas["zonas"].remove(nombre_z)

    # --- INTERFAZ DEL DASHBOARD ---
    st.subheader("📋 Monitor de Red (Vista Técnica)")
    
    # Columnas que querías: Name, SN, Status, etc.
    df['Icono'] = df['status'].apply(lambda x: "🟢" if str(x).lower() == 'online' else "🔴")
    
    st.dataframe(
        df[['Icono', 'CLIENTE_NAME', 'sn', 'ZONA_NOMBRE', 'PUERTO', 'status', 'last_status_change']].rename(
            columns={'CLIENTE_NAME': 'NAME (Código)', 'sn': 'Serie (SN)', 'status': 'Estado'}
        ),
        use_container_width=True, hide_index=True
    )

    # Resumen de Fallas Actuales
    col1, col2 = st.columns(2)
    with col1:
        st.write("🔴 **Puertos en Alerta:**")
        st.write(list(st.session_state.alertas_enviadas["puertos"]))
    with col2:
        st.write("🚩 **Zonas con Falla General:**")
        st.write(list(st.session_state.alertas_enviadas["zonas"]))

else:
    st.error("❌ No se pudo conectar con SmartOLT.")

# Auto-refresco
time.sleep(60)
st.rerun()
