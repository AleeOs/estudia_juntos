import os
import random
import io
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from datetime import datetime, timedelta

# Importaciones para ReportLab (Generación de PDF)
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "secret_key_default")

def get_db_connection():
    return psycopg2.connect(
        os.getenv("DATABASE_URL"),
        cursor_factory=RealDictCursor
    )

@app.route('/')
def home():
    if 'user_id' in session:
        if session['user_rol'] == 'Aprendiz':
            return redirect(url_for('dashboard_aprendiz'))
        return redirect(url_for('dashboard_tutor'))
    return redirect(url_for('login'))

# --- AUTENTICACIÓN ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        nombre = request.form['nombre'].strip()
        apellido = request.form['apellido'].strip()
        correo = request.form['correo'].strip().lower()
        password = request.form['password']
        semestre = request.form['semestre']
        id_rol = request.form['id_rol']

        hashed_password = generate_password_hash(password)

        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT id_usuario FROM usuarios WHERE correo = %s", (correo,))
        if cur.fetchone():
            flash("El correo institucional ya se encuentra registrado.", "danger")
            cur.close()
            conn.close()
            return redirect(url_for('register'))

        cur.execute("""
            INSERT INTO usuarios (nombre, apellido, correo, password_hash, semestre, id_rol)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (nombre, apellido, correo, hashed_password, semestre, id_rol))
        
        conn.commit()
        cur.close()
        conn.close()

        flash("Registro exitoso. ¡Inicia sesión!", "success")
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        correo = request.form['correo'].strip().lower()
        password = request.form['password']

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT u.*, r.nombre_rol 
            FROM usuarios u 
            JOIN roles r ON u.id_rol = r.id_rol 
            WHERE u.correo = %s
        """, (correo,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id_usuario']
            session['user_nombre'] = user['nombre']
            session['user_rol'] = user['nombre_rol']

            if user['nombre_rol'] == 'Aprendiz':
                return redirect(url_for('dashboard_aprendiz'))
            else:
                return redirect(url_for('dashboard_tutor'))
        else:
            flash("Correo o contraseña incorrectos.", "danger")

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Sesión cerrada correctamente.", "info")
    return redirect(url_for('login'))

# --- MÓDULO APRENDIZ ---
@app.route('/dashboard/aprendiz')
def dashboard_aprendiz():
    if 'user_id' not in session or session.get('user_rol') != 'Aprendiz':
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    # 1. Obtener disponibilidades de tutores
    cur.execute("""
        SELECT d.id_disponibilidad, d.fecha, d.hora_inicio, d.hora_fin,
               m.nombre_materia, u.nombre AS tutor_nombre, u.apellido AS tutor_apellido
        FROM disponibilidades d
        JOIN materias m ON d.id_materia = m.id_materia
        JOIN usuarios u ON d.id_tutor = u.id_usuario
        WHERE d.estado = 'Disponible'
        ORDER BY d.fecha ASC, d.hora_inicio ASC
    """)
    disponibles = cur.fetchall()

    # 2. Obtener mis reservas (tutorías agendadas)
    cur.execute("""
        SELECT t.id_tutoria, t.codigo_verificacion, t.estado, t.duracion_horas,
               d.fecha, d.hora_inicio, d.hora_fin, m.nombre_materia,
               u.nombre AS tutor_nombre, u.apellido AS tutor_apellido
        FROM tutorias t
        JOIN disponibilidades d ON t.id_disponibilidad = d.id_disponibilidad
        JOIN materias m ON d.id_materia = m.id_materia
        JOIN usuarios u ON d.id_tutor = u.id_usuario
        WHERE t.id_aprendiz = %s
        ORDER BY t.fecha_creacion DESC
    """, (session['user_id'],))
    mis_reservas = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('dashboard_aprendiz.html', disponibles=disponibles, mis_reservas=mis_reservas)








@app.route('/reservar/<int:id_disponibilidad>', methods=['POST'])
def reservar(id_disponibilidad):
    if 'user_id' not in session or session.get('user_rol') != 'Aprendiz':
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    # Verificar que esté disponible y obtener la hora de inicio y fin
    cur.execute("""
        SELECT * FROM disponibilidades 
        WHERE id_disponibilidad = %s AND estado = 'Disponible'
    """, (id_disponibilidad,))
    disp = cur.fetchone()

    if not disp:
        flash("La franja seleccionada ya no está disponible.", "warning")
        cur.close()
        conn.close()
        return redirect(url_for('dashboard_aprendiz'))

    # Calcular la duración exacta en horas
    # 'hora_inicio' y 'hora_fin' vienen como objetos time o string timedelta
    h_inicio = datetime.strptime(str(disp['hora_inicio']), "%H:%M:%S")
    h_fin = datetime.strptime(str(disp['hora_fin']), "%H:%M:%S")
    diferencia = h_fin - h_inicio
    duracion_horas = round(diferencia.total_seconds() / 3600.0, 2)

    # Generar código de 4 dígitos
    codigo = f"{random.randint(1000, 9999)}"

    # Crear la tutoría con la duración calculada
    cur.execute("""
        INSERT INTO tutorias (id_disponibilidad, id_aprendiz, codigo_verificacion, estado, duracion_horas)
        VALUES (%s, %s, %s, 'Pendiente', %s)
    """, (id_disponibilidad, session['user_id'], codigo, duracion_horas))

    # Cambiar estado de la disponibilidad a Reservado
    cur.execute("UPDATE disponibilidades SET estado = 'Reservado' WHERE id_disponibilidad = %s", (id_disponibilidad,))

    conn.commit()
    cur.close()
    conn.close()

    flash(f"¡Tutoría agendada! Tu código de confirmación es: {codigo}", "success")
    return redirect(url_for('dashboard_aprendiz'))


@app.route('/validar_codigo/<int:id_tutoria>', methods=['POST'])
def validar_codigo(id_tutoria):
    if 'user_id' not in session or session.get('user_rol') != 'Tutor':
        return redirect(url_for('login'))

    codigo_ingresado = request.form['codigo'].strip()

    conn = get_db_connection()
    cur = conn.cursor()

    # Obtener tutoría
    cur.execute("SELECT * FROM tutorias WHERE id_tutoria = %s AND estado = 'Pendiente'", (id_tutoria,))
    tutoria = cur.fetchone()

    if tutoria and tutoria['codigo_verificacion'] == codigo_ingresado:
        # 1. Marcar tutoría como Completada
        cur.execute("UPDATE tutorias SET estado = 'Completada' WHERE id_tutoria = %s", (id_tutoria,))
        
        # 2. Actualizar también el estado de la disponibilidad a 'Completada'
        cur.execute("""
            UPDATE disponibilidades 
            SET estado = 'Completada' 
            WHERE id_disponibilidad = %s
        """, (tutoria['id_disponibilidad'],))

        # 3. Sumar horas exactas al tutor
        cur.execute("""
            UPDATE usuarios 
            SET horas_acumuladas = horas_acumuladas + %s 
            WHERE id_usuario = %s
        """, (tutoria['duracion_horas'], session['user_id']))

        conn.commit()
        flash("¡Código verificado con éxito! Las horas han sido acreditadas.", "success")
    else:
        flash("Código de verificación incorrecto.", "danger")

    cur.close()
    conn.close()

    return redirect(url_for('dashboard_tutor'))

# --- MÓDULO TUTOR ---
@app.route('/dashboard/tutor')
def dashboard_tutor():
    if 'user_id' not in session or session.get('user_rol') != 'Tutor':
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    # 1. Obtener lista de materias
    cur.execute("SELECT * FROM materias ORDER BY nombre_materia ASC")
    materias = cur.fetchall()

    # 2. Mis franjas publicadas
    cur.execute("""
        SELECT d.id_disponibilidad, d.fecha, d.hora_inicio, d.hora_fin, d.estado, m.nombre_materia
        FROM disponibilidades d
        JOIN materias m ON d.id_materia = m.id_materia
        WHERE d.id_tutor = %s
        ORDER BY d.fecha DESC
    """, (session['user_id'],))
    mis_franjas = cur.fetchall()

    # 3. Tutorías pendientes por confirmar código
    cur.execute("""
        SELECT t.id_tutoria, t.estado, t.duracion_horas, d.fecha, d.hora_inicio,
               m.nombre_materia, u.nombre AS aprendiz_nombre, u.apellido AS aprendiz_apellido
        FROM tutorias t
        JOIN disponibilidades d ON t.id_disponibilidad = d.id_disponibilidad
        JOIN materias m ON d.id_materia = m.id_materia
        JOIN usuarios u ON t.id_aprendiz = u.id_usuario
        WHERE d.id_tutor = %s AND t.estado = 'Pendiente'
    """, (session['user_id'],))
    pendientes = cur.fetchall()

    # 4. Total de horas acumuladas del tutor
    cur.execute("SELECT horas_acumuladas FROM usuarios WHERE id_usuario = %s", (session['user_id'],))
    user_data = cur.fetchone()
    horas_totales = user_data['horas_acumuladas'] if user_data else 0.0

    cur.close()
    conn.close()

    return render_template('dashboard_tutor.html', materias=materias, mis_franjas=mis_franjas, pendientes=pendientes, horas_totales=horas_totales)

@app.route('/publicar_disponibilidad', methods=['POST'])
def publicar_disponibilidad():
    if 'user_id' not in session or session.get('user_rol') != 'Tutor':
        return redirect(url_for('login'))

    id_materia = request.form['id_materia']
    fecha = request.form['fecha']
    hora_inicio = request.form['hora_inicio']
    hora_fin = request.form['hora_fin']

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO disponibilidades (id_tutor, id_materia, fecha, hora_inicio, hora_fin)
        VALUES (%s, %s, %s, %s, %s)
    """, (session['user_id'], id_materia, fecha, hora_inicio, hora_fin))
    
    conn.commit()
    cur.close()
    conn.close()

    flash("Franja horaria publicada correctamente.", "success")
    return redirect(url_for('dashboard_tutor'))





@app.route('/descargar_certificado_pdf')
def descargar_certificado_pdf():
    if 'user_id' not in session or session.get('user_rol') != 'Tutor':
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    # 1. Obtener información del tutor
    cur.execute("""
        SELECT nombre, apellido, correo, semestre, horas_acumuladas 
        FROM usuarios 
        WHERE id_usuario = %s
    """, (session['user_id'],))
    tutor = cur.fetchone()

    # 2. Obtener el historial de tutorías completadas
    cur.execute("""
        SELECT m.nombre_materia, d.fecha, d.hora_inicio, d.hora_fin, t.duracion_horas,
               u.nombre AS aprendiz_nombre, u.apellido AS aprendiz_apellido
        FROM tutorias t
        JOIN disponibilidades d ON t.id_disponibilidad = d.id_disponibilidad
        JOIN materias m ON d.id_materia = m.id_materia
        JOIN usuarios u ON t.id_aprendiz = u.id_usuario
        WHERE d.id_tutor = %s AND t.estado = 'Completada'
        ORDER BY d.fecha DESC
    """, (session['user_id'],))
    tutorias_completadas = cur.fetchall()

    cur.close()
    conn.close()

    # Crear buffer en memoria para el PDF
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = []

    styles = getSampleStyleSheet()
    
    # Estilos personalizados
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#0d6efd'),
        alignment=1, # Centrado
        spaceAfter=15
    )
    
    subtitle_style = ParagraphStyle(
        'SubtitleStyle',
        parent=styles['Normal'],
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#555555'),
        alignment=1,
        spaceAfter=25
    )

    body_style = ParagraphStyle(
        'BodyStyle',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        spaceAfter=10
    )

    # Encabezado
    story.append(Paragraph("<b>PLATAFORMA ESTUDIA JUNTOS</b>", title_style))
    story.append(Paragraph("Certificado Oficial de Horas de Tutoría Universitaria", subtitle_style))
    story.append(Spacer(1, 10))

    # Información del Tutor
    texto_tutor = f"""
    <b>Certificado otorgado a:</b> {tutor['nombre']} {tutor['apellido']}<br/>
    <b>Correo institucional:</b> {tutor['correo']}<br/>
    <b>Semestre actual:</b> {tutor['semestre']}° Semestre<br/>
    <b>Total horas acumuladas y validadas:</b> <font color="#0d6efd"><b>{tutor['horas_acumuladas']} horas</b></font>
    """
    story.append(Paragraph(texto_tutor, body_style))
    story.append(Spacer(1, 15))

    story.append(Paragraph("<b>Detalle de Tutorías Impartidas:</b>", body_style))
    story.append(Spacer(1, 5))

    # Tabla de Tutorías
    tabla_data = [["Asignatura", "Aprendiz", "Fecha", "Horario", "Horas"]]
    
    if tutorias_completadas:
        for t in tutorias_completadas:
            tabla_data.append([
                t['nombre_materia'],
                f"{t['aprendiz_nombre']} {t['aprendiz_apellido']}",
                str(t['fecha']),
                f"{t['hora_inicio']} - {t['hora_fin']}",
                f"{t['duracion_horas']} h"
            ])
    else:
        tabla_data.append(["Sin registros completados", "-", "-", "-", "0 h"])

    tabla = Table(tabla_data, colWidths=[150, 130, 80, 100, 50])
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d6efd')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (-1, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
    ]))

    story.append(tabla)
    story.append(Spacer(1, 30))

    # Pie de página / Firma
    texto_pie = "<i>Documento generado automáticamente por el sistema EstudiaJuntos para la validación de horas de monitoría/tutoría académica.</i>"
    story.append(Paragraph(texto_pie, subtitle_style))

    doc.build(story)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"Certificado_Tutor_{tutor['nombre']}_{tutor['apellido']}.pdf",
        mimetype='application/pdf'
    )


if __name__ == '__main__':
    app.run(debug=True)