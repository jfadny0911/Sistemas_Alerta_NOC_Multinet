import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timedelta
import plotly.express as px

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Multinet NOC Enterprise", page_icon="🛡️", layout="wide")

# 1. Credenciales
try:
    URL_BASE = st.secrets["smartolt"]["url"].strip().rstrip('/')
    SMART_TOKEN = st.secrets["smartolt"]["token"].strip()
    TG_TOKEN = st.secrets["telegram"]["token"]
    TG_CHAT = st.secrets["telegram"]["chat_id"]
except:
    st.error("❌ Revisa tus Secrets.")
    st.stop()

# --- MEMORIA DE SESIÓN (PERSISTENCIA) ---
if 'registro_caidas' not in st.session_state: st.session_state.registro_caidas = {}
if 'contador_flapping' not in st.session_state: st.session_state.contador_flapping = {}
if 'historial_senales' not in st.session_state: st.session_state.historial_senales = pd.DataFrame(columns=['Hora', 'SN', 'Signal'])
if 'eventos_dia' not in st.session_state: st.session_state.eventos_dia = []

st.title("🛡️ Multinet NOC: Gestión Proactiva Enterprise")

# --- FUNCIONES DE ACCIÓN ---
def enviar_tg(msg):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "Markdown"})

def llamar_api(endpoint, metodo="POST", params=None):
    url = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': SMART_TOKEN}
    try:
        if metodo == "POST":
            r = requests.post(url, headers=headers, json=params, timeout=20)
        else:
            r = requests.get(url, headers=headers, params=params, timeout=20)
        return r.json().get('response') if r.status_code == 200 else None
    except: return None

def reboot_onu(sn):
    # Endpoint oficial para reiniciar ONU
    res = llamar_api("onu/reboot", params={"sn": sn})
    if res: st.toast(f"Comando de reinicio enviado a {sn}", icon="🔄")
    else: st.error("No se pudo reiniciar la ONU.")

# --- PROCESAMIENTO DE DATOS ---
with st.spinner('Analizando métricas de red...'):
    # Usamos get_all para obtener SEÑAL ÓPTICA (es un poco más pesado pero necesario para Pro)
    onus_data = llamar_api("onu/get_all")
    olts = llamar_api("system/get_olts")

if onus_data:
    df = pd.DataFrame(onus_data)
    ahora = datetime.now()
    
    # Limpieza de datos
    df['PUERTO'] = "B" + df['board'].astype(str) + "/P" + df['port'].astype(str)
    df['CLIENTE'] = df['name'].fillna(df['sn'])
    df['signal_num'] = pd.to_numeric(df['signal'], errors='coerce')
    
    # 1. DETECCIÓN DE FLAPPING (Inestabilidad)
    for _, row in df.iterrows():
        sn = row['sn']
        status = str(row['status']).lower()
        
        # Lógica de Flapping: si cambia de estado, sumamos al contador
        if sn not in st.session_state.contador_flapping:
            st.session_state.contador_flapping[sn] = {'count': 0, 'last_status': status}
        
        if status != st.session_state.contador_flapping[sn]['last_status']:
            st.session_state.contador_flapping[sn]['count'] += 1
            st.session_state.contador_flapping[sn]['last_status'] = status
            
            # Alerta de inestabilidad
            if st.session_state.contador_flapping[sn]['count'] >= 5:
                enviar_tg(f"⚠️ *CLIENTE INESTABLE (FLAPPING)*\n👤 {row['CLIENTE']}\n🆔 SN: `{sn}`\nSe ha desconectado {st.session_state.contador_flapping[sn]['count']} veces recientemente.")

    # --- DISEÑO DE TABS ---
    tab_mon, tab_signal, tab_flapping, tab_report = st.tabs([
        "🖥️ Monitor & Acciones", 
        "📡 Radar de Señal", 
        "🔄 Flapping", 
        "📝 Reporte de Turno"
    ])

    with tab_mon:
        st.subheader("Control Directo de ONUs")
        # Buscador
        busc = st.text_input("Buscar por SN o Nombre")
        df_v = df.copy()
        if busc: df_v = df_v[df_v['sn'].str.contains(busc, case=False) | df_v['CLIENTE'].str.contains(busc, case=False)]
        
        # Tabla con botones (Uso de data_editor para permitir interacción)
        st.write("Selecciona una ONU para realizar acciones:")
        cols_disp = ['status', 'CLIENTE', 'sn', 'PUERTO', 'signal']
        st.dataframe(df_v[cols_disp], use_container_width=True)
        
        sel_sn = st.selectbox("Escribe el SN para REINICIAR:", [""] + df_v['sn'].tolist())
        if st.button("🔄 Reiniciar ONU Seleccionada") and sel_sn:
            reboot_onu(sel_sn)

    with tab_signal:
        st.subheader("Análisis de Salud Óptica (dBm)")
        # Gráfico de distribución de señales
        fig = px.histogram(df, x="signal_num", nbins=30, 
                           title="Distribución de Potencia en la Red",
                           color_discrete_sequence=['#00CC96'])
        st.plotly_chart(fig, use_container_width=True)
        
        # Clientes críticos
        st.warning("Clientes con señal crítica (Peor a -27 dBm):")
        df_critico = df[df['signal_num'] < -27].sort_values(by='signal_num')
        st.dataframe(df_critico[['CLIENTE', 'sn', 'signal', 'PUERTO']], use_container_width=True)

    with tab_flapping:
        st.subheader("Equipos con alta intermitencia")
        flapping_data = [{"SN": k, "Reconexiones": v['count']} for k, v in st.session_state.contador_flapping.items() if v['count'] > 0]
        if flapping_data:
            df_flap = pd.DataFrame(flapping_data).sort_values(by="Reconexiones", ascending=False)
            st.table(df_flap)
            if st.button("Limpiar Contadores"):
                st.session_state.contador_flapping = {}
                st.rerun()
        else:
            st.info("No se detecta inestabilidad en la red.")

    with tab_report:
        st.subheader("Generador de Reporte de Turno")
        resumen = f"""
        📊 REPORTE DE ESTADO - {ahora.strftime('%d/%m/%Y')}
        -------------------------------------------
        ✅ Clientes Online: {len(df[df['status']=='online'])}
        🔴 Clientes Offline: {len(df[df['status']!='online'])}
        📡 Señales Críticas: {len(df[df['signal_num'] < -27])}
        🔄 Alertas Flapping: {len([f for f in flapping_data if f['Reconexiones'] >= 5])}
        -------------------------------------------
        """
        st.text_area("Copia este reporte para el grupo de trabajo:", resumen, height=200)
        
        # Botón para descargar CSV de fallas
        df_fallas = df[df['status'] != 'online']
        csv = df_fallas.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Descargar Tabla de Fallas (CSV)", csv, "fallas_multinet.csv", "text/csv")

else:
    st.error("No se pudo obtener la información avanzada de las ONUs.")

# Refresco
time.sleep(60)
st.rerun()
