import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Multinet NOC - SmartView", page_icon="📡", layout="wide")

# 1. Credenciales
try:
    URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
    SMART_TOKEN = st.secrets["smartolt"]["token"].strip()
    TG_TOKEN = st.secrets["telegram"]["token"]
    TG_CHAT = st.secrets["telegram"]["chat_id"]
except:
    st.error("❌ Revisa los Secrets.")
    st.stop()

# --- MEMORIA TÉCNICA (Persistencia) ---
if 'db_clientes' not in st.session_state: st.session_state.db_clientes = {}
if 'registro_caidas' not in st.session_state: st.session_state.registro_caidas = {}

st.title("🛰️ Multinet NOC: SmartView Intelligence")

# --- FUNCIONES CORE ---
def enviar_tg(mensaje):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT, "text": mensaje, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def llamar_api(endpoint, timeout=25):
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': SMART_TOKEN}
    try:
        r = requests.post(url, headers=headers, timeout=timeout)
        if r.status_code == 405: r = requests.get(url, headers=headers, timeout=timeout)
        return r.json().get('response') if r.status_code == 200 else None
    except: return None

# --- SIDEBAR: SINCRONIZACIÓN PROFUNDA ---
with st.sidebar:
    st.header("⚙️ Herramientas")
    if st.button("♻️ Sincronizar Datos de Clientes"):
        with st.spinner("Leyendo Name y Address de SmartOLT..."):
            # Obtenemos TODOS los detalles (incluyendo address_or_comment)
            data_full = llamar_api("onu/get_all", timeout=60)
            if data_full:
                # Guardamos Name, Address y Zona por cada SN
                st.session_state.db_clientes = {
                    str(r['sn']): {
                        'name_id': r.get('name', 'N/A'),
                        'address': r.get('address_or_comment', 'N/A'),
                        'zona': r.get('zone_name', 'N/A')
                    } for r in data_full
                }
                st.success(f"✅ {len(st.session_state.db_clientes)} Clientes sincronizados.")
            else: st.error("Error al obtener datos detallados.")

# --- PROCESO DE MONITOREO ---
with st.spinner('Analizando red...'):
    onus_status = llamar_api("onu/get_onus_statuses")
    olts = llamar_api("system/get_olts")

if onus_status is not None:
    df = pd.DataFrame(onus_status)
    df['sn'] = df['sn'].astype(str)
    
    # 1. MAPEAMOS LOS DATOS DE LA IMAGEN
    def get_info(sn, campo):
        return st.session_state.db_clientes.get(sn, {}).get(campo, "No Sincronizado")

    df['NAME_ID'] = df['sn'].apply(lambda x: get_info(x, 'name_id'))
    df['DIRECCION'] = df['sn'].apply(lambda x: get_info(x, 'address'))
    df['ZONA'] = df['sn'].apply(lambda x: get_info(x, 'zona'))
    df['PUERTO'] = "B" + df['board'].astype(str) + "/P" + df['port'].astype(str)
    
    ahora_dt = datetime.now()
    df_off = df[df['status'].str.lower() != 'online'].copy()

    # 2. LÓGICA DE ALERTAS DETALLADAS
    for _, row in df.iterrows():
        sn, nombre, address, status = row['sn'], row['NAME_ID'], row['DIRECCION'], str(row['status']).lower()
        
        if status != 'online' and sn not in st.session_state.registro_caidas:
            st.session_state.registro_caidas[sn] = ahora_dt
            causa = "🔌 Corte de Energía" if "pwfail" in status else "✂️ Corte de Fibra (LOS)"
            
            # Mensaje detallado para Telegram como querías
            msg = f"🔴 *FALLA DE SERVICIO*\n"
            msg += f"👤 *Cliente:* {address}\n"
            msg += f"🆔 *Código (Name):* `{nombre}`\n"
            msg += f"📍 *Zona:* {row['ZONA']}\n"
            msg += f"🔌 *Puerto:* {row['PUERTO']}\n"
            msg += f"❓ *Causa:* {causa}"
            enviar_tg(msg)
            
        elif status == 'online' and sn in st.session_state.registro_caidas:
            inicio = st.session_state.registro_caidas[sn]
            duracion = str(ahora_dt - inicio).split('.')[0]
            enviar_tg(f"✅ *RECUPERADO:* {nombre}\n👤 {address}\n⏳ Tiempo fuera: {duracion}")
            del st.session_state.registro_caidas[sn]

    # --- INTERFAZ VISUAL ---
    # KPIs Estilo SmartOLT
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Clientes Totales", len(df))
    c2.metric("Online ✅", len(df) - len(df_off))
    c3.metric("Offline ❌", len(df_off), delta_color="inverse")
    c4.metric("Fallas de Puerto", len(df_off['PUERTO'].unique()) if not df_off.empty else 0)

    st.markdown("---")
    
    # BUSCADOR
    busc = st.text_input("🔍 Buscar cliente por Name (Código), Dirección o SN")
    df_v = df.copy()
    if busc:
        mask = (df_v['sn'].str.contains(busc, case=False, na=False) | 
                df_v['NAME_ID'].str.contains(busc, case=False, na=False) |
                df_v['DIRECCION'].str.contains(busc, case=False, na=False))
        df_v = df_v[mask]

    # TABLA MAESTRA
    st.subheader("📋 Monitor Maestro de Red")
    
    # Función para icono de señal (Simulado según dBm si estuvieran disponibles)
    df_v['Status_Punto'] = df_v['status'].apply(lambda x: "🟢" if str(x).lower() == 'online' else "🔴")
    
    # Reordenamos las columnas para que se parezcan a tu imagen
    cols_final = ['Status_Punto', 'NAME_ID', 'DIRECCION', 'sn', 'ZONA', 'PUERTO', 'status', 'last_status_change']
    st.dataframe(
        df_v[cols_final].rename(columns={
            'NAME_ID': 'NAME (Código)', 
            'DIRECCION': 'Address or Comment', 
            'status': 'Status',
            'last_status_change': 'Since'
        }), 
        use_container_width=True, hide_index=True
    )

else:
    st.error("❌ No hay comunicación con SmartOLT.")

time.sleep(60)
st.rerun()
