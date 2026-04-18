import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Multinet NOC - Inteligencia Total", page_icon="📡", layout="wide")

# 1. Carga de Credenciales
try:
    URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
    SMART_TOKEN = st.secrets["smartolt"]["token"].strip()
    TG_TOKEN = st.secrets["telegram"]["token"]
    TG_CHAT = st.secrets["telegram"]["chat_id"]
except Exception as e:
    st.error(f"❌ Error en Secrets: Falta la configuración de {e}")
    st.stop()

# --- MEMORIA DEL SISTEMA (Persistencia) ---
if 'registro_caidas' not in st.session_state: st.session_state.registro_caidas = {}
if 'nombres_cache' not in st.session_state: st.session_state.nombres_cache = {}
if 'alertas_masivas' not in st.session_state: st.session_state.alertas_masivas = set()

st.title("🛰️ Multinet NOC: Centro de Mando Enterprise")

# --- FUNCIONES CORE ---
def enviar_tg(mensaje):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT, "text": mensaje, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def llamar_api(endpoint, timeout=20):
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': SMART_TOKEN}
    try:
        r = requests.post(url, headers=headers, timeout=timeout)
        if r.status_code == 405: r = requests.get(url, headers=headers, timeout=timeout)
        return r.json().get('response') if r.status_code == 200 else None
    except: return None

def calcular_duracion(inicio, fin):
    diff = fin - inicio
    h, rem = divmod(diff.total_seconds(), 3600)
    m, _ = divmod(rem, 60)
    return f"{int(h)}h {int(m)}m" if h > 0 else f"{int(m)}m"

# --- SIDEBAR: GESTIÓN DE DATOS ---
with st.sidebar:
    st.header("⚙️ Herramientas de Soporte")
    if st.button("♻️ Sincronizar 'NAME' de Clientes"):
        with st.spinner("Extrayendo códigos reales (NAME) de SmartOLT..."):
            # Este endpoint trae el 'name' real del cliente
            data_full = llamar_api("onu/get_all", timeout=60)
            if data_full:
                st.session_state.nombres_cache = {str(r['sn']): r.get('name', r.get('onu', r['sn'])) for r in data_full}
                st.success(f"Sincronizados {len(st.session_state.nombres_cache)} clientes.")
            else: st.error("No se pudo obtener la base de datos avanzada.")
    
    if st.button("📤 Enviar Reporte de Prueba"):
        enviar_tg("🔔 *SISTEMA ACTIVO:* El bot de Multinet está monitoreando la red.")

# --- PROCESO DE MONITOREO ---
with st.spinner('Analizando integridad de red...'):
    onus_raw = llamar_api("onu/get_onus_statuses")
    olts = llamar_api("system/get_olts")
    unconfigured = llamar_api("onu/get_unconfigured")

if onus_raw:
    df = pd.DataFrame(onus_raw)
    df['sn'] = df['sn'].astype(str)
    df['PUERTO'] = "B" + df['board'].astype(str) + "/P" + df['port'].astype(str)
    # Aquí asignamos el NAME real desde el caché o el campo ONU
    df['CLIENTE_NAME'] = df['sn'].apply(lambda x: st.session_state.nombres_cache.get(x, "Sincronice en Sidebar"))
    
    ahora_dt = datetime.now()
    df_off = df[df['status'].str.lower() != 'online'].copy()

    # --- LÓGICA DE ALERTAS INTELIGENTES ---
    # 1. Detección Masiva (Cortes de Fibra / Energía)
    fallas_p = df_off.groupby(['olt_id', 'PUERTO']).size().reset_index(name='caidos')
    puertos_en_falla = fallas_p[fallas_p['caidos'] >= 3] # Umbral de 3 clientes

    for _, f in puertos_en_falla.iterrows():
        id_falla = f"FALLA_{f['olt_id']}_{f['PUERTO']}"
        if id_falla not in st.session_state.alertas_masivas:
            df_afectados = df_off[(df_off['olt_id'] == f['olt_id']) & (df_off['PUERTO'] == f['PUERTO'])]
            nombres = ", ".join(df_afectados['CLIENTE_NAME'].astype(str).tolist())
            
            msg = f"💥 *FALLA MASIVA DETECTADA*\n\n🏢 *OLT:* {f['olt_id']}\n🔌 *Puerto:* {f['PUERTO']}\n📉 *Afectados:* {f['caidos']} clientes\n👤 *Nombres:* {nombres}\n⚠️ *Posible:* Corte de fibra o falta de energía."
            enviar_tg(msg)
            st.session_state.alertas_masivas.add(id_falla)

    # 2. Detección Individual y Desconexión Manual
    for _, row in df.iterrows():
        sn, nombre, status = row['sn'], row['CLIENTE_NAME'], str(row['status']).lower()
        id_p = f"FALLA_{row['olt_id']}_{row['PUERTO']}"
        
        # Si NO es falla masiva, reportamos individual
        if status != 'online' and id_p not in st.session_state.alertas_masivas:
            if sn not in st.session_state.registro_caidas:
                st.session_state.registro_caidas[sn] = ahora_dt
                causa = "🔌 Desconexión Manual / Energía" if "pwfail" in status else "✂️ Falla de Fibra (LOS)"
                enviar_tg(f"🔴 *FALLA INDIVIDUAL*\n👤 {nombre}\n🆔 SN: `{sn}`\n❓ Causa: {causa}")
        
        # Recuperación con cálculo de tiempo (SLA)
        elif status == 'online' and sn in st.session_state.registro_caidas:
            inicio = st.session_state.registro_caidas[sn]
            tiempo_total = calcular_duracion(inicio, ahora_dt)
            enviar_tg(f"✅ *SERVICIO RECUPERADO*\n👤 {nombre}\n⏳ Estuvo fuera: {tiempo_total}")
            del st.session_state.registro_caidas[sn]

    # Limpiar alertas masivas cuando se recuperan
    for alerta in list(st.session_state.alertas_masivas):
        _, olt, port = alerta.split("_")
        if len(df_off[(df_off['olt_id'] == olt) & (df_off['PUERTO'] == port)]) < 2:
            enviar_tg(f"✅ *PUERTO RESTABLECIDO:* {port} en OLT {olt} ya está estable.")
            st.session_state.alertas_masivas.remove(alerta)

    # --- INTERFAZ DEL DASHBOARD ---
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Online ✅", len(df) - len(df_off))
    k2.metric("Offline ❌", len(df_off), delta_color="inverse")
    k3.metric("Fallas de Puerto", len(puertos_en_falla))
    k4.metric("Nuevas ONUs 🆕", len(unconfigured) if unconfigured else 0)

    st.markdown("---")
    t1, t2, t3 = st.tabs(["🖥️ Monitor Soporte", "🆕 Por Autorizar", "🏢 Estado Hardware"])

    with t1:
        st.subheader("🔍 Buscador de Clientes")
        busc = st.text_input("Escribe SN o NAME del cliente")
        df_view = df.copy()
        if busc:
            df_view = df_view[
                df_view['sn'].str.contains(busc, case=False, na=False) | 
                df_view['CLIENTE_NAME'].str.contains(busc, case=False, na=False)
            ]
        
        df_view['Estado'] = df_view['status'].apply(lambda x: "🟢 Online" if x=='online' else "🔴 Offline")
        st.dataframe(df_view[['Estado', 'CLIENTE_NAME', 'sn', 'PUERTO', 'last_status_change']], use_container_width=True, hide_index=True)

    with t2:
        st.subheader("Nuevas ONUs detectadas")
        if unconfigured:
            st.dataframe(pd.DataFrame(unconfigured), use_container_width=True)
        else: st.write("No hay equipos pendientes.")

    with t3:
        st.subheader("Estado de Cabeceras (OLTs)")
        if olts:
            for o in olts:
                st_olt = str(o.get('status')).lower()
                is_up = st_olt in ['online', '1', 'up', 'active']
                color = "green" if is_up else "red"
                st.markdown(f"🏢 **{o.get('name')}** | IP: `{o.get('ip')}` | Estado: :{color}[{st_olt.upper()}]")

else:
    st.error("❌ Sin conexión a SmartOLT.")

time.sleep(60)
st.rerun()
