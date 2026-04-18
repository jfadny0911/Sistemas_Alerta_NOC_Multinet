import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Multinet NOC - SmartView Pro", page_icon="📡", layout="wide")

# 1. Credenciales
try:
    URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
    SMART_TOKEN = st.secrets["smartolt"]["token"].strip()
    TG_TOKEN = st.secrets["telegram"]["token"]
    TG_CHAT = st.secrets["telegram"]["chat_id"]
except:
    st.error("❌ Revisa los Secrets.")
    st.stop()

# --- MEMORIA TÉCNICA ---
if 'db_clientes' not in st.session_state: st.session_state.db_clientes = {}
if 'registro_caidas' not in st.session_state: st.session_state.registro_caidas = {}

st.title("🛡️ Multinet NOC: Gestión Masiva Inteligente")

# --- FUNCIONES CORE ---
def llamar_api(endpoint, payload=None, timeout=20):
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': SMART_TOKEN}
    try:
        # Si hay payload, enviamos los parámetros (ej: olt_id)
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if r.status_code == 405: 
            r = requests.get(url, headers=headers, params=payload, timeout=timeout)
        return r.json().get('response') if r.status_code == 200 else None
    except: return None

# --- SIDEBAR: SINCRONIZACIÓN POR BLOQUES ---
with st.sidebar:
    st.header("⚙️ Panel de Control")
    st.info(f"💾 Clientes en memoria: {len(st.session_state.db_clientes)}")
    
    if st.button("♻️ Sincronización Inteligente (OLT por OLT)"):
        # 1. Traemos la lista de OLTs primero
        lista_olts = llamar_api("system/get_olts")
        
        if lista_olts:
            progress_bar = st.progress(0)
            status_text = st.empty()
            temp_db = {}
            total_olts = len(lista_olts)
            
            for i, olt in enumerate(lista_olts):
                olt_id = olt.get('id')
                nombre_olt = olt.get('name', f"ID: {olt_id}")
                status_text.text(f"⏳ Procesando OLT: {nombre_olt}...")
                
                # Pedimos las ONUs solo de esta OLT (mucho más rápido)
                # Nota: Algunos SmartOLT requieren el filtro en el body o param
                onus_olt = llamar_api("onu/get_all", payload={"olt_id": olt_id}, timeout=40)
                
                if onus_olt:
                    for r in onus_olt:
                        temp_db[str(r['sn']).strip()] = {
                            'name_id': str(r.get('name', 'N/A')),
                            'address': str(r.get('address_or_comment', 'N/A')),
                            'zona': str(r.get('zone_name', 'N/A'))
                        }
                
                # Actualizar progreso
                progress_bar.progress((i + 1) / total_olts)
            
            st.session_state.db_clientes = temp_db
            status_text.text("✅ ¡Sincronización Completa!")
            st.success(f"Se cargaron {len(temp_db)} clientes con éxito.")
            time.sleep(1)
            st.rerun()
        else:
            st.error("No se pudo obtener la lista de OLTs para iniciar.")

# --- PROCESO DE MONITOREO ---
onus_status = llamar_api("onu/get_onus_statuses")

if onus_status is not None:
    df = pd.DataFrame(onus_status)
    df['sn'] = df['sn'].astype(str).str.strip()
    
    # Cruce de datos
    def get_info(sn, campo):
        return st.session_state.db_clientes.get(sn, {}).get(campo, "No Sincronizado")

    df['NAME_ID'] = df['sn'].apply(lambda x: get_info(x, 'name_id'))
    df['DIRECCION'] = df['sn'].apply(lambda x: get_info(x, 'address'))
    df['ZONA_TXT'] = df['sn'].apply(lambda x: get_info(x, 'zona'))
    df['PUERTO'] = "B" + df['board'].astype(str) + "/P" + df['port'].astype(str)
    
    df_off = df[df['status'].str.lower() != 'online'].copy()

    # INDICADORES
    c1, c2, c3 = st.columns(3)
    c1.metric("Online ✅", len(df) - len(df_off))
    c2.metric("Offline ❌", len(df_off), delta_color="inverse")
    c3.metric("Puertos Afectados", len(df_off['PUERTO'].unique()) if not df_off.empty else 0)

    st.markdown("---")
    
    # BUSCADOR
    busc = st.text_input("🔍 Buscar por Código (Name), Nombre o SN")
    if busc:
        mask = (df['sn'].str.contains(busc, case=False, na=False) | 
                df['NAME_ID'].str.contains(busc, case=False, na=False) |
                df['DIRECCION'].str.contains(busc, case=False, na=False))
        df = df[mask]

    # TABLA
    st.subheader("📋 Monitor Maestro")
    df['Icon'] = df['status'].apply(lambda x: "🟢" if str(x).lower() == 'online' else "🔴")
    
    cols_v = ['Icon', 'NAME_ID', 'DIRECCION', 'sn', 'ZONA_TXT', 'PUERTO', 'status', 'last_status_change']
    st.dataframe(df[cols_v], use_container_width=True, hide_index=True)

else:
    st.error("❌ El servidor SmartOLT no responde. Verifica si la IP está bloqueada.")

time.sleep(60)
st.rerun()
