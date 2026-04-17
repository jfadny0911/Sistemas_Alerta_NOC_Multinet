import telebot
import gspread
from datetime import datetime
import os

# --- CONFIGURACIÓN ---
# Reemplaza "TU_TOKEN_DE_TELEGRAM_AQUI" por el token de tu bot de @BotFather
TOKEN = "8291607048:AAEbfL-sqqfWTrl0hQoBUtKPUovMDoTmLWQ" 
NOMBRE_SHEET = "Inventario_NOC"

bot = telebot.TeleBot(TOKEN)

def conectar_google():
    try:
        # Asegúrate de que google_creds.json esté en el mismo lugar que este script
        gc = gspread.service_account(filename='google_creds.json')
        return gc.open(NOMBRE_SHEET)
    except Exception as e:
        print(f"❌ Error conectando a Google Sheets: {e}")
        return None

# --- COMANDO /pendientes ---
@bot.message_handler(commands=['pendientes'])
def ver_pendientes(message):
    print(f"🔍 Consulta de pendientes recibida de: {message.from_user.first_name}")
    sh = conectar_google()
    if sh:
        try:
            ws = sh.worksheet("Log_Fallas")
            datos = ws.get_all_records()
            
            # Filtrar filas donde el evento sea ASIGNADO
            pendientes = [
                f"• 🛠 *{d['Equipo']}* (IP: {d['Ip']})\n  └ {d['Duracion']}"
                for d in datos if str(d.get('Evento (DOWN / UP)', '')).upper() == 'ASIGNADO'
            ]
            
            if pendientes:
                bot.reply_to(message, "📝 *EQUIPOS EN REPARACIÓN:*\n\n" + "\n".join(pendientes), parse_mode="Markdown")
            else:
                bot.reply_to(message, "✅ No hay fallas pendientes asignadas actualmente.")
        except Exception as e:
            bot.reply_to(message, "⚠️ Error al acceder a la pestaña Log_Fallas.")
            print(f"Error en /pendientes: {e}")

# --- MANEJADOR DE BOTONES (Callback de "Asignarme") ---
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    # Confirmar a Telegram que recibimos el clic para quitar el reloj de carga
    bot.answer_callback_query(call.id, "Asignando tarea...")
    
    usuario = call.from_user.first_name
    ahora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Extraer datos del texto del mensaje de alerta enviado por app.py
    lineas = call.message.text.split('\n')
    nombre_eq = "Desconocido"
    ip_eq = "-"
    ubicacion_eq = "N/A"

    for l in lineas:
        if "Host:" in l: nombre_eq = l.split("Host:")[1].strip()
        if "IP:" in l: ip_eq = l.split("IP:")[1].strip()
        if "Ubicación:" in l: ubicacion_eq = l.split("Ubicación:")[1].strip()

    sh = conectar_google()
    if sh:
        try:
            ws = sh.worksheet("Log_Fallas")
            # Estructura del Excel: Fecha, Equipo, Ip, Evento (DOWN / UP), Duracion
            # Guardamos al usuario y la ubicación en la columna "Duracion"
            ws.append_row([ahora, nombre_eq, ip_eq, "ASIGNADO", f"🙋‍♂️ {usuario} ({ubicacion_eq})"])
            
            # Editar el mensaje original en el grupo de Telegram para que todos lo vean
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=call.message.text + f"\n\n✅ *Atendido por:* {usuario}",
                parse_mode="Markdown"
            )
            print(f"✅ {usuario} tomó el equipo {nombre_eq} ({ip_eq})")
        except Exception as e:
            print(f"❌ Error guardando en Excel: {e}")

print("🚀 MONITOR OYENTE ACTIVO. Esperando mensajes...")
bot.polling(non_stop=True)
