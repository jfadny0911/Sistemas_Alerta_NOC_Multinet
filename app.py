import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Multinet NOC - Ultra Intelligence", page_icon="📡", layout="wide")

# 1. Carga de Credenciales Segura
try:
    URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
    SMART_TOKEN = st.secrets["smartolt"]["token"].strip()
    TG_TOKEN = st.secrets["telegram"]["token"] # Tu secreto dice 'token'
    TG_CHAT = st.secrets["telegram"]["chat_id"]
except Exception as e:
    st.error(f"❌ Error crítico en Secrets: Falta la llave {e}")
    st.stop()

# --- MEMORIA DE ESTADO ---
if 'ultimo_estado_red' not in st.session_state:
    st.session_state.ultimo_estado_red = ""

st.title("🛰️ Multinet NOC: Centro de Mando Pro")

# --- FUNCIONES NÚCLEO ---
def enviar_tg(mensaje):
    """Envía mensaje a Telegram y devuelve si fue exitoso"""
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT, "text": mensaje, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200, r.text
    except Exception as e:
        return False, str(e)

def llamar_api(endpoint):
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': SMART_TOKEN}
    try:
        r = requests.post(url, headers=headers, timeout=20)
        if r.status_code == 405: r = requests.get(url, headers=headers, timeout=20)
        return r.json().get('response') if r.status_code == 200 else None
    except: return None

# --- BARRA LATERAL: HERRAMIENTAS DE PRUEBA ---
with st.sidebar:
    st.header("🛠️ Herramientas")
    if st.button("🔌 Probar Conexión Telegram"):
        success, response = enviar_tg("🔔 *Prueba de Conexión:* El Bot de Multinet está vinculado correctamente.")
        if success: st.success("¡Mensaje enviado!")
        else: st.error(f"Error: {response}")

# --- PROCESO DE DATOS ---
with st.spinner('Analizando red en tiempo real...'):
    onus = llamar_api("onu/get_onus_statuses")
    zonas = llamar_api("system/get_zones")

if onus is not None:
    df = pd.DataFrame(onus)
    
    # Unir con nombres de zonas
    if zonas:
        df_z = pd.DataFrame(zonas)
        df_z['id'] = df_z['id'].astype(str)
        df['zone_id'] = df['zone_id'].astype(str)
        df = pd.merge(df, df_z[['id', 'name']], left_on='zone_id', right_on='id', how='left')
    
    df['Puerto'] = "B" + df['board'].astype(str) + "/P" + df['port'].astype(str)
    df['NAME_ID'] = df['onu'].fillna(df['sn'])
    df['Zona_Txt'] = df['name'].fillna("Sin Zona")
    
    # Filtro de caídos
    df_off = df[df['status'].str.lower() != 'online'].copy()
    
    # Lógica de Notificación: Comparamos si el set de SN caídos cambió
    hash_fallas = "-".join(sorted(df_off['sn'].astype(str).tolist()))
    
    if hash_fallas != st.session_state.ultimo_estado_red:
        if not df_off.empty:
            # CONSTRUCCIÓN DEL REPORTE EXTENSO
            fecha_act = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            msg = f"🚨 *REPORTE DE INCIDENCIAS MULTINET*\n"
            msg += f"📅 _Sincronización: {fecha_act}_\n"
            msg += "------------------------------------------\n\n"
            
            # Agrupar por OLT
            for olt in df_off['olt_id'].unique():
                df_olt = df_off[df_off['olt_id'] == olt]
                msg += f"🏢 *OLT:* {olt}\n"
                
                # Agrupar por Puerto dentro de la OLT
                for p in df_olt['Puerto'].unique():
                    df_p = df_olt[df_olt['Puerto'] == p]
                    nombres = ", ".join(df_p['NAME_ID'].astype(str).tolist())
                    msg += f"  🔌 *Puerto:* {p} 📉 *Caídos:* ({len(df_p)})\n"
                    msg += f"  👥 _Clientes:_ {nombres}\n"
                msg += "\n"
            
            msg += "------------------------------------------\n"
            msg += f"📊 *Resumen:* {len(df_off)} clientes fuera de servicio."
            
            # Enviar y guardar estado
            enviar_tg(msg)
            st.session_state.ultimo_estado_red = hash_fallas
        else:
            # Si se recuperaron todos
            if st.session_state.ultimo_estado_red != "":
                enviar_tg("✅ *RED ESTABLE:* Todos los servicios se han restablecido.")
                st.session_state.ultimo_estado_red = ""

    # --- INTERFAZ DEL DASHBOARD (TODA LA INFO) ---
    k1, k2, k3 = st.columns(3)
    k1.metric("Base Total", len(df))
    k2.metric("Online ✅", len(df[df['status'].str.lower() == 'online']))
    k3.metric("Fallas 🚨", len(df_off), delta_color="inverse")

    st.markdown("---")
    
    tab_mon, tab_nuevas = st.tabs(["🖥️ Monitor General", "🆕 ONUs por Autorizar"])
    
    with tab_mon:
        # Buscador
        busc = st.text_input("🔍 Buscar por SN o Name", "")
        df_show = df.copy()
        if busc:
            df_show = df_show[df_show['sn'].str.contains(busc, case=False) | df_show['NAME_ID'].str.contains(busc, case=False)]
        
        df_show['Icon'] = df_show['status'].apply(lambda x: "🟢" if str(x).lower() == 'online' else "🔴")
        st.dataframe(
            df_show[['Icon', 'NAME_ID', 'sn', 'Zona_Txt', 'Puerto', 'status', 'last_status_change']].rename(
                columns={'NAME_ID': 'NAME (Código)', 'sn': 'Serie SN', 'status': 'Estado'}
            ),
            use_container_width=True, hide_index=True
        )

    with tab_nuevas:
        unconf = llamar_api("onu/get_unconfigured")
        if unconf:
            st.success(f"Hay {len(unconf)} ONUs nuevas detectadas.")
            st.dataframe(pd.DataFrame(unconf), use_container_width=True)
        else:
            st.write("No hay equipos pendientes.")

else:
    st.error("❌ No se pudo conectar con la API de SmartOLT.")

# Auto-refresco cada 60 segundos
time.sleep(60)
st.rerun()
