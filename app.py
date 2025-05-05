

from flask import Flask, request, jsonify, send_from_directory
from flask_talisman import Talisman
from flask_cors import CORS
from openai import OpenAI
import pymysql
import ssl
import os
from datetime import datetime, timezone, timedelta

# Inicializa la aplicación Flask
app = Flask(__name__)
CORS(app)

# Configura encabezados de seguridad con Talisman
csp = {
    'default-src': ["'self'"],
    'script-src': ["'self'"],
    'style-src': ["'self'"]
}
Talisman(app, content_security_policy=csp, force_https=True)

# Configura el cliente de OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))




# Conexión a la base de datos MariaDB
print("🔧 MYSQLHOST:", os.getenv("MYSQLHOST") or "❌ No encontrado")
print("🔧 MYSQLUSER:", os.getenv("MYSQLUSER") or "❌ No encontrado")
print("🔧 MYSQLPASSWORD:", os.getenv("MYSQL_ROOT_PASSWORD") or "❌ No encontrado")
print("🔧 MYSQLDATABASE:", os.getenv("MYSQLDATABASE") or "❌ No encontrado")
print("🔧 MYSQLPORT:", os.getenv("MYSQLPORT") or "❌ No encontrado")


db = pymysql.connect(
    host=os.getenv("MYSQLHOST"),
    user=os.getenv("MYSQLUSER"),
    password=os.getenv("MYSQL_ROOT_PASSWORD"),
    database=os.getenv("MYSQLDATABASE"),
    port=int(os.getenv("MYSQLPORT"))
)

try:
    test_cursor = db.cursor()
    test_cursor.execute("SELECT NOW()")
    resultado = test_cursor.fetchone()
    print(f"✅ Conexión a la base de datos OK → {resultado[0]}")
    test_cursor.close()
except Exception as err:
    print("❌ Error al conectar a la base de datos:", err)



# Ruta para servir el favicon
@app.route('/favicon.ico')
def favicon():
    return send_from_directory('assets/img', 'favicon.ico', mimetype='image/x-icon')

# Logger de accesos sospechosos
@app.before_request
def registrar_acceso_sospechoso():
    ruta = request.path
    if ruta.startswith("/.") or "config" in ruta or "refs" in ruta:
        ip = request.remote_addr
        user_agent = request.headers.get("User-Agent", "No-UA")
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] IP: {ip} | PATH: {ruta} | UA: {user_agent}\n"
        try:
            os.makedirs("logs", exist_ok=True)
            with open("logs/accesos_sospechosos.log", "a", encoding="utf-8") as f:
                f.write(log_line)
            print(f"🛡️  ACCESO DETECTADO → {ip} ha intentado acceder a {ruta}")
        except Exception as e:
            print(f"⚠️  Error al registrar acceso sospechoso: {e}")

# Ruta principal
@app.route('/')
def home():
    return '''
        <h2>✅ Chatbot Activo</h2>
        <p>1️⃣ POST a <code>/consulta-gpt</code> para consultar.<br>
        2️⃣ Luego POST a <code>/chat</code> para registrar si el usuario acepta.</p>
    '''

# Ruta para consultar a GPT
@app.route('/consulta-gpt', methods=['POST'])
def consulta_gpt():
    try:
        data = request.get_json()
        pregunta = data.get('pregunta')
        tema = data.get('tema', 'General')
        subtema = data.get('subtema', 'No especificado')
        tipo_cliente = data.get('tipo_cliente', 'No indicado')
        ip = request.remote_addr
        user_agent = request.headers.get("User-Agent")

        if not pregunta or pregunta.strip() == "":
            return jsonify({"error": "Falta la pregunta"}), 400

        # Limitar a 3 consultas por IP por hora
        cursor = db.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM consultas_gpt
            WHERE ip = %s AND fecha >= NOW() - INTERVAL 1 HOUR
        """, (ip,))
        count = cursor.fetchone()[0]
        
        # 🔍 Agrega esta línea para ver la IP y el número de consultas
        print(f"📡 IP detectada: {ip} - Consultas registradas en la última hora: {count}")
        
        if count >= 20:
            cursor.close()
            return jsonify({"error": "Has alcanzado el límite de 3 consultas por hora."}), 429

        # Preparar prompt
        prompt = f"""
Eres un asesor especializado en temas {tema}, especialmente en {subtema}.
El usuario se identifica como {tipo_cliente}.
Consulta del usuario: {pregunta}

Eres un asesor tributario, contable y auditor profesional en Perú, con experiencia en NIIF, SUNAT, el Tribunal Fiscal, Impuesto a la Renta, IGV, auditoría financiera, Machine Learning y Business Intelligence.

Responde como un asesor senior. Si el tema depende de normativa oficial reciente, orienta con criterio técnico y sugiere revisar fuentes oficiales.
        """

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.3
        )

        respuesta = response.choices[0].message.content.strip()

        # Guardar en base de datos
        sql = """
            INSERT INTO consultas_gpt (
                fecha, ip, user_agent, tema, subtema, mensaje
            )
            VALUES (NOW(), %s, %s, %s, %s, %s)
        """
        cursor.execute(sql, (ip, user_agent, tema, subtema, pregunta))
        db.commit()
        # 🔍 Log adicional para confirmar registro
        print(f"📝 Consulta registrada → IP: {ip}, Pregunta: {pregunta[:60]}...")
        cursor.close()

        return jsonify({"respuesta": respuesta})

    except Exception as e:
        return jsonify({"error": f"Error al consultar GPT: {str(e)}"}), 500

# Ruta para registrar datos del contacto
@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        nombre = data.get('nombre')
        email = data.get('email')
        empresa = data.get('empresa')
        user_input = data.get('message')
        tema = data.get('tema', 'General')
        subtema = data.get('subtema', 'No especificado')
        acepta_contacto = data.get('acepta_contacto', 0)
        comentario_extra = data.get('comentario_extra', None)

        if not all([nombre.strip(), email.strip(), empresa.strip(), user_input.strip()]):
            return jsonify({"error": "Faltan campos obligatorios"}), 400

        ip = request.remote_addr
        user_agent = request.headers.get("User-Agent")

        cursor = db.cursor()
        sql = """
            INSERT INTO consultas (
                nombre, email, empresa, mensaje, ip, user_agent,
                tema, subtema, acepta_contacto, comentario_extra
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(sql, (
            nombre, email, empresa, user_input, ip, user_agent,
            tema, subtema, acepta_contacto, comentario_extra
        ))
        db.commit()
        cursor.close()

        return jsonify({"response": "Consulta registrada correctamente. Un asesor se comunicará contigo."})

    except Exception as e:
        return jsonify({"error": f"Error al guardar en la base de datos: {str(e)}"}), 500

# ✅ NUEVA RUTA para sincronizar el temporizador cliente-servidor
@app.route('/consulta-tiempo', methods=['GET'])
def consulta_tiempo():
    try:
        ip = request.remote_addr
        cursor = db.cursor()
        cursor.execute("""
            SELECT MIN(fecha) FROM consultas_gpt
            WHERE ip = %s AND fecha >= NOW() - INTERVAL 1 HOUR
        """, (ip,))
        primera_consulta = cursor.fetchone()[0]
        cursor.close()

        # 👇 Aquí agregas el print para debug
        print(f"⏱️ IP solicitante: {ip} - Primera consulta reciente registrada: {primera_consulta}")

        if primera_consulta:
            now = datetime.now()
            restante = (primera_consulta + timedelta(hours=1)) - now
            segundos_restantes = max(int(restante.total_seconds()), 0)
        else:
            segundos_restantes = 3600  # 60 minutos si no ha consultado

        return jsonify({
                "segundos_restantes": segundos_restantes,
                "primera_consulta": str(primera_consulta) if primera_consulta else None
})

    except Exception as e:
        return jsonify({"error": f"Error al calcular tiempo restante: {str(e)}"}), 500


# Desactiva cache
@app.after_request
def desactivar_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# Ejecutar servidor con SSL
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)

