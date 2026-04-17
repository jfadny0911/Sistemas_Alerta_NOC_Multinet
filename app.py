import streamlit as st
import pandas as pd
import requests
import time
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict

# ═══════════════════════════════════════════════════════
# CONFIGURACIÓN GENERAL
# ═══════════════════════════════════════════════════════
st.set_page_config(page_title="NOC Multinet", page_icon="📡", layout="wide")

COLS_FALLA         = ['onu_id', 'name', 'sn', 'olt_id', 'pon_port', 'status']
REFRESH_SEC        = 60
OFFLINE_UMBRAL_PCT = 0.10    # Alerta si > 10% de ONUs están offline
SIGNAL_UMBRAL_DBM  = -27.0   # Alerta si señal RX promedio cae por debajo de este valor (dBm)
COOLDOWN_SEC       = 600     # No re-enviar alertas antes de 10 minutos

# ═══════════════════════════════════════════════════════
# SECRETS
# ═══════════════════════════════════════════════════════
try:
    URL_BASE     = str(st.secrets['smartolt']['url']).strip().rstrip('/')
    TOKEN        = str(st.secrets['smartolt']['token']).strip()
    TG_BOT_TOKEN = str(st.secrets['telegram']['token']).strip()
    TG_CHAT_ID   = str(st.secrets['telegram']['chat_id']).strip()
except KeyError as e:
    st.error(f"⚠️ Secret faltante: {e}")
    st.code("""
# secrets.toml — agrega esto en Streamlit Cloud → Settings → Secrets

[smartolt]
url   = "https://multinet.smartolt.com"
token = "TU_TOKEN_AQUI"

[telegram]
token = "123456789:AABBccDDeEFfGgHhIiJj..."
chat_id   = "-100123456789"
    """)
    st.stop()

# ═══════════════════════════════════════════════════════
# API SMARTOLT
# ═══════════════════════════════════════════════════════
@st.cache_data(ttl=REFRESH_SEC)
def consulta(endpoint: str):
    """Intenta GET y luego POST. Devuelve response o None."""
    url     = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': TOKEN}
    for method in ('GET', 'POST'):
        try:
            r = requests.request(method, url, headers=headers, timeout=15)
            if r.status_code == 200:
                data = r.json()
                if data.get('status') is True:
                    return data.get('response')
        except (requests.RequestException, ValueError):
            pass
    return None

# ═══════════════════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════════════════
def enviar_telegram(mensaje: str, tipo: str = "info") -> bool:
    """Envía un mensaje HTML formateado al chat de Telegram."""
    try:
        url  = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        resp = requests.post(
            url,
            json={"chat_id": TG_CHAT_ID, "text": mensaje, "parse_mode": "HTML"},
            timeout=10
        )
        return resp.status_code == 200
    except Exception:
        return False

def puede_enviar(key: str) -> bool:
    """Verifica si pasó el cooldown desde la última alerta de ese tipo."""
    ultima = st.session_state.get(key, 0)
    return (time.time() - ultima) > COOLDOWN_SEC

def registrar_envio(key: str):
    st.session_state[key] = time.time()

def tiempo_restante(key: str) -> str:
    resta = int(COOLDOWN_SEC - (time.time() - st.session_state.get(key, 0)))
    return f"{resta // 60}m {resta % 60}s"

# ═══════════════════════════════════════════════════════
# OBTENER DATOS EN PARALELO
# ═══════════════════════════════════════════════════════
st.title("📡 Monitor de Red Multinet")

with st.spinner("Conectando con SmartOLT..."):
    with ThreadPoolExecutor() as ex:
        f_onus    = ex.submit(consulta, "onu/get_onus_statuses")
        f_olts    = ex.submit(consulta, "olt/get_olts")
        f_traffic = ex.submit(consulta, "olt/get_olt_port_traffic")
    onus    = f_onus.result()
    olts    = f_olts.result()
    traffic = f_traffic.result()

# ═══════════════════════════════════════════════════════
# PROCESAMIENTO PRINCIPAL
# ═══════════════════════════════════════════════════════
if not (onus and isinstance(onus, list)):
    st.error("❌ No se pudieron obtener datos de la API.")
    with st.expander("🔍 Diagnóstico"):
        st.write(f"**URL:** `{URL_BASE}/api/onu/get_onus_statuses`")
        st.write("1. Quita la `/` al final de la URL en secrets.")
        st.write("2. Verifica el token (sin espacios).")
        st.write("3. Confirma que la IP esté permitida en Settings → API KEY.")
    time.sleep(REFRESH_SEC)
    st.rerun()

df = pd.DataFrame(onus)

if 'status' not in df.columns:
    st.warning("La API no devolvió campo 'status'. Columnas: " + str(list(df.columns)))
    st.stop()

df['status_lower'] = df['status'].fillna('').str.lower()
df['es_offline']   = (df['status_lower'] != 'online').astype(int)

# Detectar campos de señal
rx_field = next((c for c in df.columns if c.lower() in ('rx_power', 'rx', 'signal_rx', 'downstream', 'signal')), None)
tx_field = next((c for c in df.columns if c.lower() in ('tx_power', 'tx', 'signal_tx', 'upstream')), None)
if rx_field: df[rx_field] = pd.to_numeric(df[rx_field], errors='coerce')
if tx_field: df[tx_field] = pd.to_numeric(df[tx_field], errors='coerce')

# Mapa olt_id → nombre
olt_names = {}
if olts and isinstance(olts, list):
    for o in olts:
        oid = str(o.get('id', o.get('olt_id', '')))
        olt_names[oid] = o.get('name', f"OLT {oid}")

# Métricas globales
total   = len(df)
online  = int((df['status_lower'] == 'online').sum())
offline = total - online
pct_off = offline / total if total > 0 else 0
rx_prom_global = df[rx_field].mean() if rx_field else None

# ═══════════════════════════════════════════════════════
# SECCIÓN 1 — MÉTRICAS GLOBALES
# ═══════════════════════════════════════════════════════
c1, c2, c3, c4 = st.columns(4)
c1.metric("📶 Total ONUs",     total)
c2.metric("✅ Online",         online)
c3.metric("❌ Offline",        offline, delta=f"-{pct_off:.1%}", delta_color="inverse")
c4.metric("📊 Disponibilidad", f"{online / total * 100:.1f}%")

# Indicadores de alerta activa
alert_cols = st.columns(2)
with alert_cols[0]:
    if pct_off > OFFLINE_UMBRAL_PCT:
        st.error(f"🚨 ONUs offline ({pct_off:.1%}) supera umbral del {OFFLINE_UMBRAL_PCT:.0%}")
    else:
        st.success(f"✅ ONUs offline ({pct_off:.1%}) dentro del umbral")

with alert_cols[1]:
    if rx_field and rx_prom_global is not None:
        if rx_prom_global < SIGNAL_UMBRAL_DBM:
            st.error(f"🚨 Señal RX global ({rx_prom_global:.2f} dBm) por debajo de {SIGNAL_UMBRAL_DBM} dBm")
        else:
            st.success(f"✅ Señal RX global ({rx_prom_global:.2f} dBm) dentro del umbral")
    else:
        st.info("ℹ️ Señal RX no disponible en esta respuesta de API")

st.markdown("---")

# ═══════════════════════════════════════════════════════
# SECCIÓN 2 — TABLA DE FALLAS
# ═══════════════════════════════════════════════════════
st.subheader("🔴 Clientes Offline")
df_falla = df[df['es_offline'] == 1].copy()
if not df_falla.empty:
    cols_ex = [c for c in COLS_FALLA if c in df_falla.columns]
    st.dataframe(df_falla[cols_ex], use_container_width=True, hide_index=True)
else:
    st.success("✅ Sin fallas reportadas.")

st.markdown("---")

# ═══════════════════════════════════════════════════════
# SECCIÓN 3 — TRÁFICO / SEÑAL POR PUERTO PON
# ═══════════════════════════════════════════════════════
st.subheader("📊 Tráfico por Puerto PON / OLT")

if traffic and isinstance(traffic, list):
    # Caso A: endpoint nativo de tráfico disponible
    st.success("✅ Datos desde `olt/get_olt_port_traffic`")
    df_traffic = pd.DataFrame(traffic)
    st.dataframe(df_traffic, use_container_width=True, hide_index=True)

else:
    # Caso B: agregar desde campos de ONUs
    group_cols = [c for c in ['olt_id', 'pon_port'] if c in df.columns]

    if group_cols:
        agg = {'es_offline': 'sum', 'status_lower': 'count'}
        rename_map = {'status_lower': 'total_onus', 'es_offline': 'offline'}
        if rx_field:
            agg[rx_field]        = 'mean'
            rename_map[rx_field] = 'rx_prom_dBm'
        if tx_field:
            agg[tx_field]        = 'mean'
            rename_map[tx_field] = 'tx_prom_dBm'

        df_port = (
            df.groupby(group_cols)
              .agg(agg)
              .rename(columns=rename_map)
              .reset_index()
        )
        if 'olt_id' in df_port.columns:
            df_port['olt_nombre'] = df_port['olt_id'].astype(str).map(olt_names).fillna('Desconocida')

        for olt_id in (df_port['olt_id'].unique() if 'olt_id' in df_port.columns else [None]):
            nombre = olt_names.get(str(olt_id), f"OLT {olt_id}")
            sub    = df_port[df_port['olt_id'] == olt_id].drop(columns=['olt_id'], errors='ignore')

            with st.expander(f"🖥️ {nombre}", expanded=True):
                st.dataframe(sub, use_container_width=True, hide_index=True)

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("ONUs totales", int(sub['total_onus'].sum()))
                m2.metric("Offline",      int(sub['offline'].sum()))
                if 'rx_prom_dBm' in sub.columns:
                    m3.metric("RX prom (dBm)", f"{sub['rx_prom_dBm'].mean():.2f}")
                if 'tx_prom_dBm' in sub.columns:
                    m4.metric("TX prom (dBm)", f"{sub['tx_prom_dBm'].mean():.2f}")

        st.caption(
            "ℹ️ `olt/get_olt_port_traffic` no respondió — se muestran promedios de señal por puerto desde las ONUs. "
            "Para tráfico en Mbps consulta a SmartOLT si tu plan lo incluye."
        )
    else:
        st.warning("⚠️ Los datos de ONUs no incluyen `olt_id` o `pon_port` para agrupar.")

st.markdown("---")

# Estado de OLTs
if olts and isinstance(olts, list):
    with st.expander("🏢 Estado de Cabeceras (OLTs)"):
        for o in olts:
            status = (o.get('status') or 'DESCONOCIDO').upper()
            icon   = "🟢" if status == "ONLINE" else "🔴"
            st.write(f"{icon} **{o.get('name', 'Sin nombre')}** — {status}")

st.markdown("---")

# ═══════════════════════════════════════════════════════
# SECCIÓN 4 — TELEGRAM AUTOMÁTICO + HISTORIAL
# ═══════════════════════════════════════════════════════
st.subheader("📬 Telegram")

# Inicializar historial en session_state
if 'historial_telegram' not in st.session_state:
    st.session_state['historial_telegram'] = []

def resumen_por_olt() -> str:
    resumen = defaultdict(lambda: {'total': 0, 'offline': 0, 'rx': []})
    for _, row in df.iterrows():
        oid = str(row.get('olt_id', 'N/A'))
        resumen[oid]['total']   += 1
        resumen[oid]['offline'] += int(row['es_offline'])
        if rx_field and pd.notna(row.get(rx_field)):
            resumen[oid]['rx'].append(float(row[rx_field]))
    lineas = ""
    for oid, v in resumen.items():
        nombre = olt_names.get(oid, f"OLT {oid}")
        rx_str = f" | RX: {sum(v['rx'])/len(v['rx']):.1f} dBm" if v['rx'] else ""
        lineas += f"  • <b>{nombre}</b>: {v['offline']}/{v['total']} offline{rx_str}\n"
    return lineas

def registrar_historial(tipo: str, estado: str, detalle: str = ""):
    st.session_state['historial_telegram'].insert(0, {
        'hora':    time.strftime('%H:%M:%S'),
        'fecha':   time.strftime('%Y-%m-%d'),
        'tipo':    tipo,
        'estado':  estado,
        'detalle': detalle,
    })
    st.session_state['historial_telegram'] = st.session_state['historial_telegram'][:50]

rx_str_global = f"{rx_prom_global:.2f} dBm" if rx_prom_global is not None else "N/D"

# ── ENVÍO AUTOMÁTICO COMPLETO CADA REFRESH ───────────────────
if puede_enviar('auto_resumen'):
    msg_auto = (
        f"📊 <b>Resumen NOC — Multinet</b>\n\n"
        f"Total: {total} | Online: {online} | Offline: {offline}\n"
        f"Disponibilidad: {online / total * 100:.1f}%\n"
        f"Señal RX prom: {rx_str_global}\n\n"
        f"<b>Por OLT:</b>\n{resumen_por_olt()}\n"
        f"🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    ok = enviar_telegram(msg_auto)
    registrar_envio('auto_resumen')
    registrar_historial("📊 Resumen automático", "✅ Enviado" if ok else "❌ Falló")

# ── ALERTA AUTOMÁTICA: ONUs offline ──────────────────────────
umbral_off_val = st.session_state.get('umbral_off_val', int(OFFLINE_UMBRAL_PCT * 100))
if pct_off > (umbral_off_val / 100) and puede_enviar('alerta_offline'):
    msg_off = (
        f"🚨 <b>ALERTA NOC — ONUs Offline</b>\n\n"
        f"❌ <b>{offline} ONUs offline</b> ({pct_off:.1%})\n"
        f"✅ Online: {online} / {total}\n\n"
        f"<b>Por OLT:</b>\n{resumen_por_olt()}\n"
        f"🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    ok = enviar_telegram(msg_off)
    registrar_envio('alerta_offline')
    registrar_historial("🔴 Alerta ONUs offline", "✅ Enviado" if ok else "❌ Falló",
                        f"{offline} offline ({pct_off:.1%})")

# ── ALERTA AUTOMÁTICA: Señal RX baja ─────────────────────────
umbral_rx_val = st.session_state.get('umbral_rx_val', int(SIGNAL_UMBRAL_DBM))
if rx_field and rx_prom_global is not None and rx_prom_global < umbral_rx_val and puede_enviar('alerta_signal'):
    msg_rx = (
        f"⚠️ <b>ALERTA NOC — Señal Baja</b>\n\n"
        f"📶 Señal RX promedio: <b>{rx_prom_global:.2f} dBm</b>\n"
        f"🔻 Umbral: {umbral_rx_val} dBm\n\n"
        f"<b>Por OLT:</b>\n{resumen_por_olt()}\n"
        f"🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    ok = enviar_telegram(msg_rx)
    registrar_envio('alerta_signal')
    registrar_historial("📶 Alerta señal RX", "✅ Enviado" if ok else "❌ Falló",
                        f"RX: {rx_prom_global:.2f} dBm")

# ── PANEL DE CONTROL ─────────────────────────────────────────
col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("**⚙️ Umbrales**")
    nuevo_off = st.slider("Umbral offline (%)", 1, 50, umbral_off_val, key="sl_off")
    st.session_state['umbral_off_val'] = nuevo_off
    nuevo_rx  = st.slider("Umbral señal RX (dBm)", -35, -15, umbral_rx_val, key="sl_rx")
    st.session_state['umbral_rx_val']  = nuevo_rx

with col2:
    st.markdown("**📡 Estado de condiciones**")
    if pct_off > (nuevo_off / 100):
        st.error(f"🔴 ONUs offline: {pct_off:.1%} (supera {nuevo_off}%)")
    else:
        st.success(f"✅ ONUs offline: {pct_off:.1%} (bajo {nuevo_off}%)")

    if rx_field and rx_prom_global is not None:
        if rx_prom_global < nuevo_rx:
            st.error(f"📶 Señal RX: {rx_prom_global:.2f} dBm (bajo {nuevo_rx} dBm)")
        else:
            st.success(f"📶 Señal RX: {rx_prom_global:.2f} dBm (OK)")
    else:
        st.info("📶 Señal RX: sin datos")

    resta_auto = int(COOLDOWN_SEC - (time.time() - st.session_state.get('auto_resumen', 0)))
    if resta_auto > 0:
        st.info(f"🔄 Próximo envío automático en {resta_auto // 60}m {resta_auto % 60}s")
    else:
        st.info("🔄 Envío automático: activo en este refresh")

with col3:
    st.markdown("**📤 Envío manual**")
    if st.button("Enviar resumen ahora", use_container_width=True):
        msg_m = (
            f"📊 <b>Resumen Manual — Multinet</b>\n\n"
            f"Total: {total} | Online: {online} | Offline: {offline}\n"
            f"Disponibilidad: {online / total * 100:.1f}%\n"
            f"Señal RX prom: {rx_str_global}\n\n"
            f"<b>Por OLT:</b>\n{resumen_por_olt()}\n"
            f"🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        ok = enviar_telegram(msg_m)
        registrar_historial("📤 Resumen manual", "✅ Enviado" if ok else "❌ Falló")
        st.success("✅ Enviado." if ok else "❌ Falló. Verifica token y chat_id.")

    if st.button("🧪 Probar conexión", use_container_width=True):
        ok = enviar_telegram("✅ <b>Test NOC Multinet</b>\nConexión con Telegram OK.")
        registrar_historial("🧪 Test conexión", "✅ OK" if ok else "❌ Falló")
        st.success("✅ Bot responde OK." if ok else "❌ No conecta.")

st.markdown("---")

# ── HISTORIAL DE MENSAJES ENVIADOS ───────────────────────────
st.subheader("🗒️ Historial de mensajes Telegram")

historial = st.session_state.get('historial_telegram', [])
if historial:
    df_hist = pd.DataFrame(historial)[['fecha', 'hora', 'tipo', 'estado', 'detalle']]
    df_hist.columns = ['Fecha', 'Hora', 'Tipo', 'Estado', 'Detalle']
    st.dataframe(df_hist, use_container_width=True, hide_index=True)
    if st.button("🗑️ Limpiar historial"):
        st.session_state['historial_telegram'] = []
        st.rerun()
else:
    st.info("Aún no se ha enviado ningún mensaje en esta sesión.")

# ═══════════════════════════════════════════════════════
# REFRESCO AUTOMÁTICO
# ═══════════════════════════════════════════════════════
time.sleep(REFRESH_SEC)
st.rerun()
