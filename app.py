import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Multinet NOC - Sistema de Alertas", page_icon="🚨", layout="wide")

# 1. Carga de Credenciales desde Secrets
try:
    URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
    SMART_TOKEN = st.secrets["smartolt"]["token"].strip()
    # Usamos tus nombres exactos de Secrets
    TG_TOKEN = st.secrets["telegram"]["token"] 
    TG_CHAT = st.secrets["telegram"]["chat_id"]
except Exception as e:
    st.error(f"❌ Error en Secrets: Falta la configuración de {e}")
    st.stop()

# --- MEMORIA DE ALERTAS ---
if 'ultimo_hash_fallas' not in st.session_state:
    st.session_state.ultimo_hash_fallas = ""

st.title("🛰️ Multinet NOC: Monitor de Fallas e Incidencias")

# --- FUNCIONES DE COMUNICACIÓN ---
def enviar_tg(mensaje):
    """Envía un mensaje a Telegram"""
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT, "text": mensaje, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200, r.text
    except Exception as e:
        return False, str(e)

def llamar_api(endpoint):
    """Consulta la API de SmartOLT"""
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': SMART_TOKEN}
    try:
        r = requests.post(url, headers=headers, timeout=20)
        if r.status_code == 405: 
            r = requests.get(url, headers=headers, timeout=20)
        return r.json().get('response') if r.status_code == 200 else None
    except:
        return None

# --- BARRA LATERAL (SIDEBAR): BOTÓN DE TEST ---
with st.sidebar:
    st.header("🛠️ Panel de Control")
    st.write("Usa este botón para verificar que Telegram recibe mensajes.")
    if st.button("📤 Enviar Mensaje de Test"):
        fecha_test = datetime.now().strftime('%H:%M:%S')
        exito, error_msg = enviar_tg(f"🔔 *MENSAJE DE PRUEBA*\nEl sistema de alertas Multinet está activo.\nHora de prueba: {fecha_test}")
        if exito:
            st.success("¡Mensaje de prueba enviado!")
        else:
            st.error(f"Error al enviar: {error_msg}")

# --- PROCESO DE MONITOREO ---
with st.spinner('Analizando estado de la red...'):
    onus = llamar_api("onu/get_onus_statuses")
    olts = llamar_api("system/get_olts")
    unconfigured = llamar_api("onu/get_unconfigured")
    zonas_raw = llamar_api("system/get_zones")

if onus is not None:
    df = pd.DataFrame(onus)
    df['NAME_ID'] = df['onu'].fillna(df['sn'])
    df['PUERTO'] = "B" + df['board'].astype(str) + "/P" + df['port'].astype(str)
    
    # Unir con nombres de zonas
    if zonas_raw:
        df_z = pd.DataFrame(zonas_raw)
        df_z['id'] = df_z['id'].astype(str)
        df['zone_id'] = df['zone_id'].astype(str)
        df = pd.merge(df, df_z[['id', 'name']], left_on='zone_id', right_on='id', how='left')
        df['ZONA_TXT'] = df['name'].fillna("Sin Zona")
    else:
        df['ZONA_TXT'] = "ID: " + df['zone_id'].astype(str)

    # DETECCÓN DE OFFLINE
    df_off = df[df['status'].str.lower() != 'online'].copy()
    
    # --- LÓGICA DE REPORTE AUTOMÁTICO ---
    # Solo manda mensaje si el grupo de SN caídos cambió
    hash_actual = "-".join(sorted(df_off['sn'].astype(str).tolist()))
    
    if hash_actual != st.session_state.ultimo_hash_fallas:
        if not df_off.empty:
            ahora = datetime.now().strftime('%d/%m/%Y %H:%M')
            reporte = f"🚨 *INFORME GLOBAL DE INCIDENCIAS*\n📅 _{ahora}_\n"
            reporte += "------------------------------------------\n\n"
            
            for olt_id in df_off['olt_id'].unique():
                nombre_olt = olt_id
                if olts:
                    for o in olts:
                        if str(o.get('id')) == str(olt_id):
                            nombre_olt = o.get('name')
                
                reporte += f"🏢 *OLT:* {nombre_olt}\n"
                df_olt_off = df_off[df_off['olt_id'] == olt_id]
                
                for p in df_olt_off['PUERTO'].unique():
                    df_p = df_olt_off[df_olt_off['PUERTO'] == p]
                    nombres = ", ".join(df_p['NAME_ID'].astype(str).tolist())
                    reporte += f"  🔌 *Puerto:* {p} ({len(df_p)} caídos)\n"
                    reporte += f"  👤 _Clientes:_ {nombres}\n"
                reporte += "\n"
            
            reporte += "------------------------------------------\n"
            reporte += f"📉 *TOTAL OFFLINE:* {len(df_off)}"
            enviar_tg(reporte)
        elif st.session_state.ultimo_hash_fallas != "":
            # Si ya no hay caídos pero antes había
            enviar_tg("✅ *RED ESTABLE:* Todos los servicios se han restablecido correctamente.")
            
        st.session_state.ultimo_hash_fallas = hash_actual

    # --- DISEÑO DEL DASHBOARD ---
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Base Total", len(df))
    m2.metric("Online ✅", len(df[df['status'].str.lower() == 'online']))
    m3.metric("Offline ❌", len(df_off), delta_color="inverse")
    m4.metric("Nuevas ONUs 🆕", len(unconfigured) if unconfigured else 0)

    st.markdown("---")

    tab1, tab2, tab3 = st.tabs(["🖥️ Monitor de Clientes", "🆕 Por Autorizar", "🏢 Estado OLTS"])

    with tab1:
        st.subheader("Lista Detallada de Clientes")
        df['Icon'] = df['status'].apply(lambda x: "🟢" if str(x).lower() == 'online' else "🔴")
        st.dataframe(
            df[['Icon', 'NAME_ID', 'sn', 'ZONA_TXT', 'PUERTO', 'status', 'last_status_change']].rename(
                columns={'NAME_ID': 'NAME (Código)', 'sn': 'Serie SN', 'status': 'Estado'}
            ), 
            use_container_width=True, hide_index=True
        )

    with tab2:
        st.subheader("Equipos detectados esperando autorización")
        if unconfigured:
            st.warning(f"Se han detectado {len(unconfigured)} ONUs nuevas.")
            st.dataframe(pd.DataFrame(unconfigured), use_container_width=True)
        else:
            st.info("No hay equipos nuevos en espera.")

    with tab3:
        st.subheader("Salud de las Cabeceras (OLTs)")
        if olts:
            for o in olts:
                # Lógica flexible de estado (online, 1, up, etc.)
                st_raw = str(o.get('status', '')).lower()
                is_up = st_raw in ['online', '1', 'true', 'up', 'active']
                
                color = "green" if is_up else "red"
                txt = "ONLINE" if is_up else f"OFFLINE ({st_raw})"
                st.markdown(f"🖥️ **{o.get('name')}** | IP: `{o.get('ip')}` | Estado: :{color}[{txt}]")
        else:
            st.error("No se pudo cargar la información de las OLTs.")

else:
    st.error("❌ No se pudo conectar a la API de SmartOLT.")

# Auto-refresco cada 60 segundos
time.sleep(60)
st.rerun()
