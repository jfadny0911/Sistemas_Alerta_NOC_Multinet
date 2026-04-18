"""
╔══════════════════════════════════════════════════════════════╗
║         NOC MULTINET — SmartView Monitor v2.0               ║
║   Streamlit + SmartOLT API + Telegram Alerts                ║
╚══════════════════════════════════════════════════════════════╝
secrets.toml:
    [smartolt]
    url   = "https://multinet.smartolt.com"
    token = "TU_TOKEN"

    [telegram]
    token   = "TU_BOT_TOKEN"
    chat_id = "TU_CHAT_ID"
"""

import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

# ══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="NOC Multinet",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

REFRESH_SEC        = 60
OFFLINE_UMBRAL_PCT = 0.10
SIGNAL_UMBRAL_DBM  = -27.0
COOLDOWN_SEC       = 600
FALLA_MASIVA_MIN   = 3      # ONUs en mismo PON para considerar falla masiva
API_TIMEOUT        = 40

# Causa de caída
CAUSAS_LOS    = {'los', 'fiber_cut', 'fibercut', 'signal_lost'}
CAUSAS_PWFAIL = {'pwfail', 'power_fail', 'dying_gasp', 'power fail', 'dyinggasp'}

# ══════════════════════════════════════════════════════════════
# SECRETS
# ══════════════════════════════════════════════════════════════
try:
    URL_BASE     = str(st.secrets['smartolt']['url']).strip().rstrip('/')
    TOKEN        = str(st.secrets['smartolt']['token']).strip()
    TG_TOKEN     = str(st.secrets['telegram']['token']).strip()
    TG_CHAT_ID   = str(st.secrets['telegram']['chat_id']).strip()
except KeyError as e:
    st.error(f"⚠️ Secret faltante: {e}")
    st.code("""
[smartolt]
url   = "https://multinet.smartolt.com"
token = "TU_TOKEN_SMARTOLT"

[telegram]
token   = "TU_BOT_TOKEN"
chat_id = "TU_CHAT_ID"
    """)
    st.stop()

# ══════════════════════════════════════════════════════════════
# SESSION STATE — PERSISTENCIA
# ══════════════════════════════════════════════════════════════
if 'db_clientes'      not in st.session_state: st.session_state['db_clientes']      = {}
if 'registro_caidas'  not in st.session_state: st.session_state['registro_caidas']  = {}
if 'alertas_masivas'  not in st.session_state: st.session_state['alertas_masivas']  = set()
if 'historial_tg'     not in st.session_state: st.session_state['historial_tg']     = []
if 'ultima_sync'      not in st.session_state: st.session_state['ultima_sync']      = 0

db_clientes     = st.session_state['db_clientes']
registro_caidas = st.session_state['registro_caidas']
alertas_masivas = st.session_state['alertas_masivas']

# ══════════════════════════════════════════════════════════════
# HELPERS API
# ══════════════════════════════════════════════════════════════
def api_get(endpoint: str, params: dict = None):
    """GET con fallback a POST. Retorna response o None."""
    url     = f"{URL_BASE}/api/{endpoint}"
    headers = {'X-Token': TOKEN}
    for method in ('GET', 'POST'):
        try:
            r = requests.request(method, url, headers=headers,
                                 params=params, timeout=API_TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                if data.get('status') is True:
                    return data.get('response')
        except (requests.RequestException, ValueError):
            pass
    return None

# ══════════════════════════════════════════════════════════════
# SINCRONIZACIÓN POR BLOQUES (OLT por OLT)
# ══════════════════════════════════════════════════════════════
def sincronizar_clientes(olts: list, progress_bar=None):
    """
    Consulta onu/get_all filtrando por olt_id para evitar timeouts.
    Campos reales SmartOLT: name, address_or_comment, zone_name, sn.
    """
    total = len(olts)
    for i, olt in enumerate(olts):
        olt_id = olt.get('id', olt.get('olt_id'))
        if not olt_id:
            continue
        try:
            resp = api_get("onu/get_all", params={'olt_id': olt_id})
            if resp and isinstance(resp, list):
                for onu in resp:
                    # SN real: "ZXICC5707236"
                    sn = str(onu.get('sn', onu.get('serial_number', ''))).strip()
                    if not sn:
                        continue
                    # name real: "2014236" (código de cliente)
                    # address_or_comment real: "150MB//LOURDES DE MARIA CASTILLO..."
                    # zone_name real: "Tilapa"
                    db_clientes[sn] = {
                        'name':               str(onu.get('name', '')).strip(),
                        'address_or_comment': str(onu.get('address_or_comment',
                                                  onu.get('comment', ''))).strip(),
                        'zona':               str(onu.get('zone_name',
                                                  onu.get('zone', ''))).strip(),
                        'olt_id':             str(olt_id),
                        'onu_type':           str(onu.get('onu_type', '')).strip(),
                    }
        except Exception:
            pass

        if progress_bar:
            progress_bar.progress(
                (i + 1) / total,
                text=f"Sincronizando {i+1}/{total}: {olt.get('name', f'OLT {olt_id}')}"
            )

    st.session_state['db_clientes'] = db_clientes
    st.session_state['ultima_sync'] = time.time()

# ══════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════
def enviar_telegram(mensaje: str) -> bool:
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"},
            timeout=10
        )
        return r.status_code == 200
    except Exception:
        return False

def log_tg(tipo: str, estado: str, detalle: str = ""):
    st.session_state['historial_tg'].insert(0, {
        'hora':    datetime.now().strftime('%H:%M:%S'),
        'fecha':   datetime.now().strftime('%Y-%m-%d'),
        'tipo':    tipo,
        'estado':  estado,
        'detalle': detalle,
    })
    st.session_state['historial_tg'] = st.session_state['historial_tg'][:100]

def puede_enviar(key: str) -> bool:
    return (time.time() - st.session_state.get(key, 0)) > COOLDOWN_SEC

def marcar_enviado(key: str):
    st.session_state[key] = time.time()

def tiempo_restante(key: str) -> str:
    r = int(COOLDOWN_SEC - (time.time() - st.session_state.get(key, 0)))
    return f"{max(r,0)//60}m {max(r,0)%60}s"

# ══════════════════════════════════════════════════════════════
# LÓGICA DE CAÍDAS — SLA y CAUSA
# ══════════════════════════════════════════════════════════════
def detectar_causa(row: dict) -> str:
    """
    Detecta causa basándose en los statuses reales de SmartOLT:
    'Online', 'Offline', 'LOS', 'Power fail', 'Dying Gasp'
    """
    status = str(row.get('status', '')).strip()
    status_l = status.lower().replace(' ', '_').replace('-', '_')

    # LOS = corte de fibra
    if status_l in ('los', 'fiber_cut', 'fibercut', 'los_signal') or 'los' in status_l:
        return '🔴 LOS (Corte de fibra)'

    # Power fail / Dying Gasp = corte de energía o desconexión manual
    if status_l in ('power_fail', 'pwfail', 'dying_gasp', 'dyinggasp') or \
       'power' in status_l or 'dying' in status_l:
        return '⚡ PwFail (Corte de energía)'

    # Offline genérico
    if status_l in ('offline', 'unreachable', 'down'):
        return '🟠 Offline'

    # Cualquier otro estado no-online
    return f'🟠 {status}' if status else '🟠 Offline'

def formato_duracion(segundos: float) -> str:
    s = int(segundos)
    h, m = divmod(s, 3600)
    m, s = divmod(m, 60)
    if h:   return f"{h}h {m}m {s}s"
    if m:   return f"{m}m {s}s"
    return f"{s}s"

def actualizar_registro_caidas(df_offline: pd.DataFrame, df_online_sn: set):
    """
    - Registra hora de caída para SNs nuevos offline.
    - Calcula y retorna SLAs de los que volvieron.
    """
    ahora    = time.time()
    slas     = []   # [{sn, name, duracion}]

    # SNs que volvieron online (estaban en registro pero ya no están offline)
    recuperados = [sn for sn in list(registro_caidas.keys()) if sn in df_online_sn]
    for sn in recuperados:
        inicio    = registro_caidas.pop(sn)
        duracion  = ahora - inicio
        nombre    = db_clientes.get(sn, {}).get('name', sn)
        slas.append({'sn': sn, 'name': nombre, 'duracion': duracion})

    # Registrar nuevas caídas
    for _, row in df_offline.iterrows():
        sn = str(row.get('sn', row.get('serial_number', '')))
        if sn and sn not in registro_caidas:
            registro_caidas[sn] = ahora

    st.session_state['registro_caidas'] = registro_caidas
    return slas

# ══════════════════════════════════════════════════════════════
# DETECCIÓN DE FALLAS MASIVAS
# ══════════════════════════════════════════════════════════════
def detectar_fallas_masivas(df_offline: pd.DataFrame) -> list:
    """
    Agrupa por olt_id + _port (extraído del formato gpon-onu_0/BOARD/PORT:ID).
    Retorna lista de puertos con falla masiva nueva (>= FALLA_MASIVA_MIN).
    """
    nuevas = []

    # Usar _port si existe (parseado de gpon-onu_0/5/8:6), sino pon_port
    port_col = '_port' if '_port' in df_offline.columns else \
               ('pon_port' if 'pon_port' in df_offline.columns else None)

    if 'olt_id' not in df_offline.columns or port_col is None:
        return nuevas

    grupos = df_offline.groupby(['olt_id', port_col])
    for (olt_id, port), grupo in grupos:
        key = f"{olt_id}_{port}"
        if len(grupo) >= FALLA_MASIVA_MIN and key not in alertas_masivas:
            nuevas.append({
                'olt_id':   olt_id,
                'pon_port': port,
                'count':    len(grupo),
                'sns':      list(grupo['_sn'].head(5)) if '_sn' in grupo.columns else [],
                'key':      key,
            })
    return nuevas

# ══════════════════════════════════════════════════════════════
# OBTENER DATOS
# ══════════════════════════════════════════════════════════════
def get_olts() -> list:
    """Prueba múltiples endpoints conocidos de SmartOLT."""
    for ep in ("system/get_olts", "olt/get_olts", "olts", "system/olts"):
        r = api_get(ep)
        if r and isinstance(r, list) and len(r) > 0:
            return r
    return []

def get_onus_statuses() -> list:
    """Prueba múltiples endpoints de estado de ONUs."""
    for ep in ("onu/get_onus_statuses", "onu/get_all_statuses", "onu/statuses"):
        r = api_get(ep)
        if r and isinstance(r, list) and len(r) > 0:
            return r
    return []

with st.spinner("🔄 Conectando con SmartOLT..."):
    with ThreadPoolExecutor() as ex:
        f_status = ex.submit(get_onus_statuses)
        f_olts   = ex.submit(get_olts)
        f_zones  = ex.submit(api_get, "system/get_zones")
        f_unconf = ex.submit(api_get, "onu/get_unconfigured")
    raw_status = f_status.result() or []
    olts       = f_olts.result()   or []
    zones      = f_zones.result()  or []
    unconf     = f_unconf.result() or []

# Mapa olt_id → nombre
olt_map  = {str(o.get('id', o.get('olt_id', ''))): o.get('name', '?') for o in olts}
zone_map = {str(z.get('id', '')): z.get('name', '') for z in zones}

# ══════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════
with st.sidebar:
    st.image("https://www.smartolt.com/images/logo.png", width=160)
    st.markdown("## ⚙️ Panel de Control")
    st.markdown("---")

    # Sincronización por bloques
    st.markdown("### 🔄 Sincronización de Clientes")
    ultima = st.session_state.get('ultima_sync', 0)
    if ultima:
        st.caption(f"Última sync: {datetime.fromtimestamp(ultima).strftime('%H:%M:%S')}")
    else:
        st.caption("Sin sincronización aún")

    st.caption(f"Clientes en caché: **{len(db_clientes):,}**")
    st.caption(f"OLTs detectadas: **{len(olts)}**")

    if st.button("🔄 Sincronizar (OLT por OLT)", use_container_width=True, type="primary"):
        if olts:
            bar = st.progress(0, text="Iniciando...")
            sincronizar_clientes(olts, progress_bar=bar)
            bar.empty()
            st.success(f"✅ {len(db_clientes):,} clientes sincronizados")
        else:
            st.error("❌ Sin OLTs — revisa diagnóstico ↓")

    # Diagnóstico de API
    with st.expander("🔍 Diagnóstico API"):
        st.caption(f"URL base: `{URL_BASE}`")
        endpoints_test = [
            ("OLTs",    "system/get_olts"),
            ("OLTs v2", "olt/get_olts"),
            ("ONUs st", "onu/get_onus_statuses"),
            ("Zonas",   "system/get_zones"),
        ]
        for label, ep in endpoints_test:
            r = api_get(ep)
            if r and isinstance(r, list):
                st.success(f"✅ `{ep}` → {len(r)} items")
            elif r:
                st.warning(f"⚠️ `{ep}` → respuesta inesperada")
            else:
                st.error(f"❌ `{ep}` → sin respuesta")

    st.markdown("---")

    # Prueba de bot
    st.markdown("### 📬 Telegram")
    if st.button("🧪 Probar Bot", use_container_width=True):
        ok = enviar_telegram("✅ *Test NOC Multinet*\nConexión con Telegram funcionando correctamente\\.")
        log_tg("🧪 Test", "✅ OK" if ok else "❌ Falló")
        st.success("✅ Bot OK" if ok else "❌ Falló — revisa token y chat_id")

    if st.button("📤 Enviar resumen ahora", use_container_width=True):
        st.session_state['forzar_resumen'] = True

    st.markdown("---")

    # Umbrales
    st.markdown("### 🎚️ Umbrales de Alerta")
    nuevo_off = st.slider("Offline (%)", 1, 50,
                           st.session_state.get('umbral_off', int(OFFLINE_UMBRAL_PCT * 100)),
                           key="sl_off")
    st.session_state['umbral_off'] = nuevo_off

    nuevo_rx = st.slider("Señal RX mín (dBm)", -35, -15,
                          st.session_state.get('umbral_rx', int(SIGNAL_UMBRAL_DBM)),
                          key="sl_rx")
    st.session_state['umbral_rx'] = nuevo_rx

    st.markdown("---")
    st.caption(f"🔄 Auto-refresh cada {REFRESH_SEC}s")

# ══════════════════════════════════════════════════════════════
# SIN DATOS
# ══════════════════════════════════════════════════════════════
if not raw_status or not isinstance(raw_status, list):
    st.error("❌ No se pudieron obtener datos de la API.")
    with st.expander("🔍 Diagnóstico"):
        st.write(f"**URL:** `{URL_BASE}/api/onu/get_onus_statuses`")
        st.write("1. URL sin `/` al final.")
        st.write("2. Token sin espacios.")
        st.write("3. IP en whitelist (Settings → API KEY en SmartOLT).")
    time.sleep(REFRESH_SEC)
    st.rerun()

# ══════════════════════════════════════════════════════════════
# PROCESAMIENTO DEL DATAFRAME
# ══════════════════════════════════════════════════════════════
df = pd.DataFrame(raw_status)

# ── Normalizar status ─────────────────────────────────────────
# SmartOLT devuelve: "Online", "Offline", "LOS", "Power fail", "Dying Gasp"
status_col = next((c for c in df.columns if c.lower() == 'status'), None)
if status_col:
    df['status_lower'] = df[status_col].fillna('').str.lower().str.strip()
else:
    df['status_lower'] = ''
df['es_offline'] = (df['status_lower'] != 'online').astype(int)

# ── SN — SmartOLT usa campo 'sn' ──────────────────────────────
# Ejemplo real: "ZXICC5707236"
sn_col = next((c for c in df.columns if c.lower() == 'sn'), None) or \
         next((c for c in df.columns if 'serial' in c.lower()), None)
df['_sn'] = df[sn_col].fillna('').astype(str) if sn_col else ''

# ── ONU identifier — "gpon-onu_0/5/8:6" → board/port extraído ─
# SmartOLT puede devolver campo 'onu' o 'onu_id' con formato gpon-onu_0/BOARD/PORT:ID
onu_id_col = next((c for c in df.columns if c.lower() in ('onu', 'onu_id', 'onu_name')), None)

def parse_onu_port(onu_str: str) -> dict:
    """Extrae board, port, id del formato gpon-onu_0/5/8:6"""
    try:
        parts = str(onu_str).split('/')
        if len(parts) >= 3:
            board = parts[-2]
            port_id = parts[-1].split(':')
            port = port_id[0]
            onu_seq = port_id[1] if len(port_id) > 1 else ''
            return {'board': board, 'port': port, 'onu_seq': onu_seq}
    except Exception:
        pass
    return {'board': '', 'port': '', 'onu_seq': ''}

if onu_id_col:
    parsed = df[onu_id_col].fillna('').apply(parse_onu_port).apply(pd.Series)
    df['_board']   = parsed['board']
    df['_port']    = parsed['port']
    df['_onu_seq'] = parsed['onu_seq']
    # Puerto legible: "Board 5 / Port 8"
    df['_puerto_full'] = df.apply(
        lambda r: f"B{r['_board']}/P{r['_port']}" if r['_board'] else str(r.get('pon_port', '—')),
        axis=1
    )
else:
    df['_board']       = ''
    df['_port']        = df.get('pon_port', pd.Series(['—'] * len(df))).fillna('—').astype(str)
    df['_puerto_full'] = df['_port']

# ── Señal RX/TX — SmartOLT devuelve "ONU/OLT Rx signal" ───────
# Campos posibles en API: 'rx_power', 'olt_rx_signal', 'signal', 'rx'
# El formato en pantalla: "-21.24 dBm / -26.03 dBm (3183m)"
rx_field = next((c for c in df.columns if c.lower() in
    ('rx_power', 'olt_rx_signal', 'signal_rx', 'rx', 'signal',
     'onu_rx_signal', 'rx_signal')), None)
tx_field = next((c for c in df.columns if c.lower() in
    ('tx_power', 'olt_tx_signal', 'signal_tx', 'tx')), None)

if rx_field:
    # Limpiar posibles strings como "-21.24 dBm"
    df[rx_field] = df[rx_field].astype(str).str.extract(r'(-?\d+\.?\d*)')[0]
    df[rx_field] = pd.to_numeric(df[rx_field], errors='coerce')
if tx_field:
    df[tx_field] = df[tx_field].astype(str).str.extract(r'(-?\d+\.?\d*)')[0]
    df[tx_field] = pd.to_numeric(df[tx_field], errors='coerce')

# ── Zona — SmartOLT campo 'zone_name' ────────────────────────
zone_col = next((c for c in df.columns if c.lower() in ('zone_name', 'zone', 'zona')), None)

# ── Campos que vienen DIRECTO de get_onus_statuses ───────────
# Según imagen real: name (código cliente), address_or_comment, zone_name
# Estos campos ya están en el response sin necesidad de sync
name_col    = next((c for c in df.columns if c.lower() == 'name'), None)
address_col = next((c for c in df.columns if c.lower() in
                    ('address_or_comment', 'address', 'comment')), None)

# ── Enriquecer: API directa primero, luego db_clientes como complemento ──
# Prioridad: campo directo API > db_clientes > SN como fallback
df['_name'] = ''
if name_col:
    df['_name'] = df[name_col].fillna('').astype(str)
# Complementar con db_clientes si el campo directo está vacío
df['_name'] = df.apply(
    lambda r: r['_name'] or db_clientes.get(r['_sn'], {}).get('name', ''),
    axis=1
)

df['_address'] = ''
if address_col:
    df['_address'] = df[address_col].fillna('').astype(str)
df['_address'] = df.apply(
    lambda r: r['_address'] or db_clientes.get(r['_sn'], {}).get('address_or_comment', ''),
    axis=1
)

# Zona: campo directo API > db_clientes
df['_zona'] = ''
if zone_col:
    df['_zona'] = df[zone_col].fillna('').astype(str)
df['_zona'] = df.apply(
    lambda r: r['_zona'] or db_clientes.get(r['_sn'], {}).get('zona', ''),
    axis=1
)

# ── Nombre de OLT ─────────────────────────────────────────────
# SmartOLT devuelve olt_id numérico, olt_map lo convierte a "2 - El Rosario"
if 'olt_id' in df.columns:
    df['_olt_name'] = df['olt_id'].astype(str).map(olt_map).fillna('?')
else:
    df['_olt_name'] = '?'

# ── Causa de caída ────────────────────────────────────────────
# Statuses reales SmartOLT: "LOS", "Power fail", "Dying Gasp", "Offline"
df['_causa'] = df.apply(lambda r: detectar_causa(r.to_dict()) if r['es_offline'] else '', axis=1)

# ── Separar online / offline ─────────────────────────────────
df_offline = df[df['es_offline'] == 1].copy()
df_online  = df[df['es_offline'] == 0].copy()
sn_online  = set(df_online['_sn'].tolist())

# ── Registrar caídas y obtener SLAs de recuperados ───────────
slas_recuperados = actualizar_registro_caidas(df_offline, sn_online)

# ── Fallas masivas ───────────────────────────────────────────
fallas_masivas_nuevas = detectar_fallas_masivas(df_offline)

# Métricas
total   = len(df)
online  = int((df['es_offline'] == 0).sum())
offline = total - online
pct_off = offline / total if total > 0 else 0
rx_prom = df[rx_field].mean() if rx_field else None

# ══════════════════════════════════════════════════════════════
# HEADER + MÉTRICAS
# ══════════════════════════════════════════════════════════════
st.markdown("""
<h1 style='font-family:monospace; color:#00d4ff; margin-bottom:0'>
📡 NOC Multinet — SmartView
</h1>
<p style='color:#888; margin-top:0; font-size:0.85rem'>
Monitor en tiempo real · SmartOLT API · Telegram Alerts
</p>
""", unsafe_allow_html=True)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("📶 Total ONUs",      f"{total:,}")
c2.metric("✅ Online",          f"{online:,}")
c3.metric("❌ Offline",         f"{offline:,}",
           delta=f"-{pct_off:.1%}", delta_color="inverse")
c4.metric("📊 Disponibilidad",  f"{online/total*100:.2f}%")
c5.metric("🔌 Sin Configurar",  f"{len(unconf):,}")

st.markdown("---")

# ══════════════════════════════════════════════════════════════
# ALERTAS VISUALES ACTIVAS
# ══════════════════════════════════════════════════════════════
if fallas_masivas_nuevas:
    for fm in fallas_masivas_nuevas:
        olt_nombre = olt_map.get(str(fm['olt_id']), f"OLT {fm['olt_id']}")
        st.error(
            f"🚨 **FALLA MASIVA** — {olt_nombre} / Puerto {fm['pon_port']} "
            f"— **{fm['count']} ONUs caídas simultáneamente**"
        )

if slas_recuperados:
    for s in slas_recuperados[:3]:
        st.success(
            f"✅ Recuperado: **{s['name'] or s['sn']}** "
            f"— Inactividad: `{formato_duracion(s['duracion'])}`"
        )

# ══════════════════════════════════════════════════════════════
# TABLA SMARTVIEW
# ══════════════════════════════════════════════════════════════
st.subheader("🖥️ SmartView — Estado de Red")

# Aviso de sincronización pendiente
if len(db_clientes) == 0:
    st.warning(
        "⚠️ **Sincronización pendiente** — Los campos *Código* y *Dirección* "
        "muestran el SN hasta que hagas clic en **🔄 Sincronizar (OLT por OLT)** "
        "en el panel izquierdo. Solo se hace una vez y tarda ~1 min para 4,300 clientes."
    )
else:
    st.caption(f"✅ {len(db_clientes):,} clientes en caché — Código y Dirección disponibles")

# Buscador
buscar = st.text_input("🔍 Buscar por nombre, SN, dirección o zona...", "")

# Construir tabla SmartView — columnas clonadas de SmartOLT
def build_smartview(df_src: pd.DataFrame, solo_offline: bool = False) -> pd.DataFrame:
    ahora = time.time()
    rows  = []
    src   = df_src[df_src['es_offline'] == 1] if solo_offline else df_src

    for _, row in src.iterrows():
        sn     = str(row.get('_sn', ''))
        es_off = int(row.get('es_offline', 0))
        causa  = str(row.get('_causa', ''))

        # ── Ícono de estado (clona SmartOLT) ──
        if not es_off:
            icon = '🟢'
        elif 'los' in causa.lower() or 'fibra' in causa.lower():
            icon = '🔴'
        elif 'pwfail' in causa.lower() or 'energía' in causa.lower():
            icon = '⚡'
        else:
            icon = '🟠'

        # ── Since — tiempo caído ──────────────
        inicio = registro_caidas.get(sn)
        if inicio:
            since = formato_duracion(ahora - inicio)
        elif es_off:
            since = '—'
        else:
            # Online: mostrar cuánto tiempo lleva online si API da timestamp
            since = '✅'

        # ── Código de cliente (campo 'name' en SmartOLT = "2014236") ──
        codigo = str(row.get('_name', '') or '').strip()
        if not codigo:
            codigo = sn  # fallback al SN si no hay sync

        # ── Dirección / Comentario ────────────────────────────────
        # SmartOLT: "150MB//LOURDES DE MARIA CASTILLO DE SANTOS&&RES&&24494"
        # Viene directo de get_onus_statuses en campo 'address_or_comment'
        address = str(row.get('_address', '') or '').strip()

        # ── Puerto — "gpon-onu_0/5/8:6" → "B5/P8:6" ─────────────
        puerto = str(row.get('_puerto_full', '') or '').strip()
        if not puerto or puerto == '—':
            # Fallback: buscar campo pon_port directo
            puerto = str(row.get('pon_port', row.get('port', '—')) or '—')

        # ── Señal RX ──────────────────────────────────────────────
        rx_val = ''
        if rx_field:
            v = row.get(rx_field)
            try:
                if v is not None and str(v) not in ('', 'nan', 'None'):
                    rx_val = f"{float(v):.2f} dBm"
            except (ValueError, TypeError):
                pass

        # ── ONU Type (ej: "GM630") ────────────────────────────────
        onu_type = str(row.get('onu_type', '') or
                       db_clientes.get(sn, {}).get('onu_type', '')).strip()

        rows.append({
            'St':        icon,
            'Código':    codigo,       # name = "2014236"
            'Dirección / Comentario': address,
            'SN':        sn,
            'Zona':      str(row.get('_zona', '') or '').strip(),
            'OLT':       str(row.get('_olt_name', '') or '').strip(),
            'Puerto':    puerto,
            'ONU Type':  onu_type,
            'RX Signal': rx_val,
            'Status':    causa if es_off else '✅ Online',
            'Since':     since,
        })

    return pd.DataFrame(rows)

tab1, tab2, tab3 = st.tabs(["🔴 Offline", "🟢 Todos", "⚙️ Sin Configurar"])

with tab1:
    df_view_off = build_smartview(df, solo_offline=True)
    if buscar:
        mask = (
            df_view_off['Código'].str.contains(buscar, case=False, na=False) |
            df_view_off['SN'].str.contains(buscar, case=False, na=False) |
            df_view_off['Dirección / Comentario'].str.contains(buscar, case=False, na=False) |
            df_view_off['Zona'].str.contains(buscar, case=False, na=False)
        )
        df_view_off = df_view_off[mask]
    if not df_view_off.empty:
        st.dataframe(df_view_off, use_container_width=True, hide_index=True, height=400)
        st.caption(f"Mostrando {len(df_view_off):,} clientes offline")
    else:
        st.success("✅ Sin clientes offline.")

with tab2:
    df_view_all = build_smartview(df, solo_offline=False)
    if buscar:
        mask = (
            df_view_all['Código'].str.contains(buscar, case=False, na=False) |
            df_view_all['SN'].str.contains(buscar, case=False, na=False) |
            df_view_all['Dirección / Comentario'].str.contains(buscar, case=False, na=False) |
            df_view_all['Zona'].str.contains(buscar, case=False, na=False)
        )
        df_view_all = df_view_all[mask]
    st.dataframe(df_view_all, use_container_width=True, hide_index=True, height=400)
    st.caption(f"Mostrando {len(df_view_all):,} clientes")

with tab3:
    if unconf:
        df_unconf = pd.DataFrame(unconf)
        st.dataframe(df_unconf, use_container_width=True, hide_index=True, height=400)
        st.caption(f"{len(unconf):,} ONUs sin configurar")
    else:
        st.info("✅ Sin ONUs pendientes de configuración.")

st.markdown("---")

# ══════════════════════════════════════════════════════════════
# TRÁFICO / SEÑAL POR PUERTO PON
# ══════════════════════════════════════════════════════════════
st.subheader("📊 Señal por Puerto PON / OLT")

# Usar _port (parseado de gpon-onu_0/BOARD/PORT:ID) o pon_port como fallback
port_grp = '_port' if '_port' in df.columns else \
           ('pon_port' if 'pon_port' in df.columns else None)
group_cols = [c for c in ['olt_id', port_grp] if c and c in df.columns]

if group_cols:
    agg = {'es_offline': 'sum', '_sn': 'count'}
    ren = {'_sn': 'total_onus', 'es_offline': 'offline'}
    if rx_field:
        agg[rx_field] = 'mean'
        ren[rx_field] = 'rx_prom_dBm'
    if tx_field:
        agg[tx_field] = 'mean'
        ren[tx_field] = 'tx_prom_dBm'

    df_port = df.groupby(group_cols).agg(agg).rename(columns=ren).reset_index()
    if 'olt_id' in df_port.columns:
        df_port['OLT'] = df_port['olt_id'].astype(str).map(olt_map).fillna('?')
    if port_grp in df_port.columns:
        df_port = df_port.rename(columns={port_grp: 'Puerto'})

    for olt_id in (df_port['olt_id'].unique() if 'olt_id' in df_port.columns else []):
        nombre = olt_map.get(str(olt_id), f"OLT {olt_id}")
        sub    = df_port[df_port['olt_id'] == olt_id].drop(columns=['olt_id', 'OLT'], errors='ignore')
        # Highlight filas con alto offline
        with st.expander(f"🖥️ {nombre}", expanded=False):
            st.dataframe(sub, use_container_width=True, hide_index=True)
            total_p = int(sub['total_onus'].sum())
            off_p   = int(sub['offline'].sum())
            rx_p    = sub['rx_prom_dBm'].mean() if 'rx_prom_dBm' in sub.columns else None
            m1, m2, m3 = st.columns(3)
            m1.metric("ONUs", total_p)
            m2.metric("Offline", off_p)
            if rx_p is not None:
                m3.metric("RX prom", f"{rx_p:.2f} dBm")

st.markdown("---")

# ══════════════════════════════════════════════════════════════
# ALERTAS TELEGRAM AUTOMÁTICAS
# ══════════════════════════════════════════════════════════════
st.subheader("📬 Telegram")

def resumen_por_olt_msg() -> str:
    res = defaultdict(lambda: {'t': 0, 'off': 0, 'rx': []})
    for _, row in df.iterrows():
        oid = str(row.get('olt_id', 'N/A'))
        res[oid]['t']   += 1
        res[oid]['off'] += int(row['es_offline'])
        if rx_field and pd.notna(row.get(rx_field)):
            res[oid]['rx'].append(float(row[rx_field]))
    lineas = ""
    for oid, v in res.items():
        nombre = olt_map.get(oid, f"OLT {oid}")
        rx_s   = f" | RX: {sum(v['rx'])/len(v['rx']):.1f} dBm" if v['rx'] else ""
        lineas += f"  • *{nombre}*: {v['off']}/{v['t']} offline{rx_s}\n"
    return lineas

rx_str = f"{rx_prom:.2f} dBm" if rx_prom is not None else "N/D"

# ── 1. Resumen automático periódico ──────────────────────────
forzar = st.session_state.pop('forzar_resumen', False)
if forzar or puede_enviar('auto_resumen'):
    msg = (
        f"📊 *Resumen NOC — Multinet*\n\n"
        f"Total: {total:,} | Online: {online:,} | Offline: {offline:,}\n"
        f"Disponibilidad: {online/total*100:.2f}%\n"
        f"Señal RX prom: {rx_str}\n\n"
        f"*Por OLT:*\n{resumen_por_olt_msg()}\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    ok = enviar_telegram(msg)
    marcar_enviado('auto_resumen')
    log_tg("📊 Resumen auto", "✅ Enviado" if ok else "❌ Falló")

# ── 2. Alerta de ONUs offline ─────────────────────────────────
if pct_off > (st.session_state.get('umbral_off', 10) / 100) and puede_enviar('alerta_offline'):
    msg_off = (
        f"🚨 *ALERTA NOC — ONUs Offline*\n\n"
        f"❌ *{offline:,} ONUs offline* ({pct_off:.1%})\n"
        f"✅ Online: {online:,} / {total:,}\n\n"
        f"*Por OLT:*\n{resumen_por_olt_msg()}\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    ok = enviar_telegram(msg_off)
    marcar_enviado('alerta_offline')
    log_tg("🔴 Alerta offline", "✅ Enviado" if ok else "❌ Falló",
           f"{offline} offline ({pct_off:.1%})")

# ── 3. Alerta de señal RX baja ────────────────────────────────
if rx_prom is not None and rx_prom < st.session_state.get('umbral_rx', -27) and puede_enviar('alerta_signal'):
    msg_rx = (
        f"⚠️ *ALERTA NOC — Señal Baja*\n\n"
        f"📶 Señal RX promedio: *{rx_prom:.2f} dBm*\n"
        f"🔻 Umbral: {st.session_state.get('umbral_rx', -27)} dBm\n\n"
        f"*Por OLT:*\n{resumen_por_olt_msg()}\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    ok = enviar_telegram(msg_rx)
    marcar_enviado('alerta_signal')
    log_tg("📶 Alerta señal RX", "✅ Enviado" if ok else "❌ Falló",
           f"RX: {rx_prom:.2f} dBm")

# ── 4. SLAs de recuperación ───────────────────────────────────
for s in slas_recuperados:
    msg_sla = (
        f"✅ *ONU Recuperada — SLA*\n\n"
        f"👤 Cliente: *{s['name'] or s['sn']}*\n"
        f"🔑 SN: `{s['sn']}`\n"
        f"⏱️ Tiempo inactivo: *{formato_duracion(s['duracion'])}*\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    ok = enviar_telegram(msg_sla)
    log_tg("✅ SLA recuperación", "✅ Enviado" if ok else "❌ Falló",
           f"{s['name']} — {formato_duracion(s['duracion'])}")

# ── 5. Fallas masivas nuevas ──────────────────────────────────
for fm in fallas_masivas_nuevas:
    olt_nombre = olt_map.get(str(fm['olt_id']), f"OLT {fm['olt_id']}")
    msg_fm = (
        f"🚨 *FALLA MASIVA DETECTADA*\n\n"
        f"🖥️ OLT: *{olt_nombre}*\n"
        f"🔌 Puerto PON: *{fm['pon_port']}*\n"
        f"📉 ONUs caídas: *{fm['count']}*\n\n"
        f"Posible causa: corte de fibra o falla de nodo\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    ok = enviar_telegram(msg_fm)
    alertas_masivas.add(fm['key'])
    st.session_state['alertas_masivas'] = alertas_masivas
    log_tg("🚨 Falla masiva", "✅ Enviado" if ok else "❌ Falló",
           f"{olt_nombre} / Puerto {fm['pon_port']} — {fm['count']} ONUs")

# ── Panel visual de estado Telegram ──────────────────────────
col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("**📡 Estado condiciones**")
    if pct_off > (st.session_state.get('umbral_off', 10) / 100):
        st.error(f"🔴 Offline: {pct_off:.1%} (supera umbral)")
    else:
        st.success(f"✅ Offline: {pct_off:.1%}")
    if rx_prom is not None:
        if rx_prom < st.session_state.get('umbral_rx', -27):
            st.error(f"📶 RX: {rx_prom:.2f} dBm (bajo umbral)")
        else:
            st.success(f"📶 RX: {rx_prom:.2f} dBm (OK)")
    else:
        st.info("📶 RX: sin datos")

with col2:
    st.markdown("**⏱️ Próximos envíos**")
    resta = int(COOLDOWN_SEC - (time.time() - st.session_state.get('auto_resumen', 0)))
    st.info(f"🔄 Resumen: {max(resta,0)//60}m {max(resta,0)%60}s")
    resta_off = int(COOLDOWN_SEC - (time.time() - st.session_state.get('alerta_offline', 0)))
    st.info(f"🔴 Alerta offline: {max(resta_off,0)//60}m {max(resta_off,0)%60}s")

with col3:
    st.markdown("**📌 Registro activo**")
    st.metric("ONUs en seguimiento", len(registro_caidas))
    st.metric("Alertas masivas activas", len(alertas_masivas))
    if st.button("🗑️ Limpiar alertas masivas"):
        st.session_state['alertas_masivas'] = set()
        st.rerun()

st.markdown("---")

# ══════════════════════════════════════════════════════════════
# HISTORIAL DE MENSAJES TELEGRAM
# ══════════════════════════════════════════════════════════════
st.subheader("🗒️ Historial de mensajes enviados")

historial = st.session_state.get('historial_tg', [])
if historial:
    df_hist = pd.DataFrame(historial)[['fecha', 'hora', 'tipo', 'estado', 'detalle']]
    df_hist.columns = ['Fecha', 'Hora', 'Tipo', 'Estado', 'Detalle']
    st.dataframe(df_hist, use_container_width=True, hide_index=True, height=300)
    if st.button("🗑️ Limpiar historial"):
        st.session_state['historial_tg'] = []
        st.rerun()
else:
    st.info("Aún no se ha enviado ningún mensaje en esta sesión.")

# ══════════════════════════════════════════════════════════════
# REFRESCO AUTOMÁTICO
# ══════════════════════════════════════════════════════════════
time.sleep(REFRESH_SEC)
st.rerun()
