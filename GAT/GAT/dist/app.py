from flask import Flask, render_template, request, redirect, url_for, flash, session, make_response, jsonify, send_file
import flask_login
from flask_login import login_required
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import sqlite3
import json
import io
import os
from lenguajes import obtener_texto
from deep_translator import GoogleTranslator
# --- IMPORTACIONES DE LÓGICA DE BASE DE DATOS ---
from database import (
    crear_conexion, inicializar_db,
    aprobar_cotizacion, crear_cierre_caja,
    obtener_ventas_aprobadas_para_cierre
)

# --- IMPORTACIONES PARA PDF ---
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from xhtml2pdf import pisa

app = Flask(__name__)
app.secret_key = 'tu_clave_secreta_aqui_cambiala_por_una_fuerte_y_unica'

# --- CONFIGURACIÓN LOGIN ---
login_manager = flask_login.LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

def traducir_automaticamente(texto, idioma_destino):
    """
    Traduce un texto al idioma destino.
    idioma_destino: 'en' (Inglés), 'zh-TW' (Chino Tradicional), etc.
    """
    if not texto:
        return ""
    try:
        # Usamos el traductor de Google integrado
        traductor = GoogleTranslator(source='auto', target=idioma_destino)
        return traductor.translate(texto)
    except Exception as e:
        print(f"Error traduciendo: {e}")
        return texto # Si falla, devolvemos el original para que no se rompa

class User(flask_login.UserMixin):
    def __init__(self, id, email, nombre, rol):
        self.id = id
        self.email = email
        self.nombre = nombre
        self.rol = rol

    def get_id(self): return str(self.id)


@login_manager.user_loader
def load_user(user_id):
    conn = crear_conexion()
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, nombre, rol FROM usuarios WHERE id = ?", (user_id,))
    user_data = cursor.fetchone()
    conn.close()
    if user_data: return User(*user_data)
    return None


# ==================================================
#  CONFIGURACIÓN DE IDIOMAS (ACTUALIZADA)
# ==================================================
def t(clave):
    """Función auxiliar para traducir desde Python"""
    idioma_actual = session.get('idioma', 'es')  # Por defecto español
    return obtener_texto(clave, idioma_actual)


@app.context_processor
def inject_traductor():
    """Esto permite usar la función t('clave') directamente en los HTML"""
    return dict(t=t, idioma_actual=session.get('idioma', 'es'))


@app.route('/cambiar_idioma/<idioma>')
def cambiar_idioma(idioma):
    """Ruta para que el botón de banderas funcione"""
    # IMPORTANTE: Agregamos 'zh' a la lista permitida
    if idioma in ['es', 'en', 'zh']:
        session['idioma'] = idioma

    # Regresa a la misma página donde estaba el usuario
    return redirect(request.referrer or url_for('menu_inicio'))
# ==================================================


# =============================================================================
# RUTAS: AUTENTICACIÓN
# =============================================================================

@app.route('/')
def raiz():
    if flask_login.current_user.is_authenticated: return redirect(url_for('menu_inicio'))
    return render_template('landing.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if flask_login.current_user.is_authenticated: return redirect(url_for('menu_inicio'))
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        conn = crear_conexion()
        cursor = conn.cursor()
        cursor.execute("SELECT id, password, nombre, rol FROM usuarios WHERE email = ?", (email,))
        user_data = cursor.fetchone()
        conn.close()
        if user_data and check_password_hash(user_data[1], password):
            user = User(user_data[0], email, user_data[2], user_data[3])
            flask_login.login_user(user)
            flash('Bienvenido', 'success')
            return redirect(url_for('menu_inicio'))
        else:
            flash('Credenciales incorrectas', 'danger')
    return render_template('login.html')


@app.route('/logout')
@flask_login.login_required
def logout():
    flask_login.logout_user()
    return redirect(url_for('login'))


@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if flask_login.current_user.is_authenticated: return redirect(url_for('menu_inicio'))
    if request.method == 'POST':
        nombre = request.form['nombre']
        email = request.form['email']
        password = request.form['password']
        confirm = request.form['confirm_password']
        if password != confirm:
            flash('Contraseñas no coinciden', 'danger')
            return redirect(url_for('registro'))
        conn = crear_conexion()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM usuarios WHERE email = ?", (email,))
        if cursor.fetchone():
            flash('Correo ya existe', 'danger')
            conn.close()
            return redirect(url_for('registro'))
        cursor.execute("INSERT INTO usuarios (nombre, email, password, rol) VALUES (?, ?, ?, ?)",
                       (nombre, email, generate_password_hash(password), 'usuario'))
        conn.commit()
        conn.close()
        session.clear()
        flash('Registro exitoso', 'success')
        return redirect(url_for('login'))
    return render_template('registro.html')


@app.route('/inicio')
@flask_login.login_required
def menu_inicio():
    return render_template('inicio.html')


# =============================================================================
# RUTAS: INVENTARIO
# =============================================================================

@app.route('/inventario')
@flask_login.login_required
def listar_inventario():
    conn = crear_conexion()
    cursor = conn.cursor()
    search = request.args.get('search_query', '').strip()
    if search:
        # Nota: La consulta SELECT * ya incluye la columna 'precio_unidad' si existe en la tabla.
        cursor.execute("SELECT * FROM inventario WHERE nombre LIKE ? ORDER BY nombre", ('%' + search + '%',))
    else:
        cursor.execute("SELECT * FROM inventario ORDER BY nombre")
    inventario = cursor.fetchall()
    cursor.execute("SELECT nombre, cantidad, umbral_stock FROM inventario WHERE cantidad <= umbral_stock")
    bajos = cursor.fetchall()
    conn.close()
    return render_template('inventario/listar.html', inventario=inventario, alertas_stock=len(bajos),
                           productos_bajo_stock=bajos, search_query=search)


@app.route('/inventario/agregar', methods=['GET', 'POST'])
@flask_login.login_required
def agregar_inventario():
    if request.method == 'POST':
        try:
            conn = crear_conexion()
            texto_original = request.form['nombre']

            # --- LÓGICA DE TRADUCCIÓN UNIVERSAL ---
            try:
                # 1. Generamos la versión en ESPAÑOL
                nombre_es = GoogleTranslator(source='auto', target='es').translate(texto_original)
                # 2. Generamos la versión en CHINO
                nombre_zh = GoogleTranslator(source='auto', target='zh-TW').translate(texto_original)
                # 3. Generamos la versión en INGLÉS
                nombre_en = GoogleTranslator(source='auto', target='en').translate(texto_original)

            except Exception as ex:
                print(f"Fallo traducción: {ex}")
                nombre_es = texto_original
                nombre_zh = texto_original
                nombre_en = texto_original
            # ---------------------------------------

            # Obtener los dos campos de precio
            precio_unitario_caja = float(request.form['precio_unitario']) # Precio Caja (Valor existente)
            # Nuevo campo: 'precio_unidad_nuevo' viene del formulario, si no existe, por defecto es 0.00
            precio_unidad = float(request.form.get('precio_unidad_nuevo', 0.00))

            # *** CAMBIO: Se añade 'precio_unidad' a la consulta INSERT y a la tupla de valores. ***
            conn.execute(
                "INSERT INTO inventario (nombre, nombre_en, nombre_zh, descripcion, cantidad, precio_unitario, precio_unidad, umbral_stock) VALUES (?,?,?,?,?,?,?,?)",
                (nombre_es, nombre_en, nombre_zh, request.form['descripcion'], int(request.form['cantidad']),
                 precio_unitario_caja, precio_unidad, int(request.form['umbral_stock'])))

            conn.commit()
            conn.close()
            flash(t('msg_producto_agregado'), 'success')
            return redirect(url_for('listar_inventario'))
        except Exception as e:
            flash(f'Error: {e}', 'danger')
    # Nota: Aquí falta la lógica del 'GET' si el usuario visita /agregar directamente.
    # Asumo que esta línea: "return render_template('inventario/agregar.html')" maneja ese caso.
    return render_template('inventario/agregar.html')

@app.route('/inventario/editar/<int:id>', methods=['GET', 'POST'])
@flask_login.login_required
def editar_inventario(id):
    conn = crear_conexion()

    if request.method == 'POST':
        try:
            nombre_es = request.form['nombre']

            # --- MAGIA DE TRADUCCIÓN AUTOMÁTICA (AL EDITAR) ---
            nombre_en = request.form.get('nombre_en')
            if not nombre_en:
                nombre_en = traducir_automaticamente(nombre_es, 'en')

            nombre_zh = request.form.get('nombre_zh')
            if not nombre_zh:
                nombre_zh = traducir_automaticamente(nombre_es, 'zh-TW')
            # --------------------------------------------------

            # Obtener los dos campos de precio
            precio_unitario_caja = float(request.form['precio_unitario']) # Precio Caja (Valor existente)
            # Nuevo campo: 'precio_unidad_nuevo' viene del formulario
            precio_unidad = float(request.form.get('precio_unidad_nuevo', 0.00))

            # *** CAMBIO: Se añade 'precio_unidad' al SET y al final de la tupla de valores. ***
            conn.execute("""
                UPDATE inventario 
                SET nombre=?, nombre_en=?, nombre_zh=?, descripcion=?, 
                    cantidad=?, precio_unitario=?, 
                    precio_unidad=?, umbral_stock=? 
                WHERE id=?""",
                         (nombre_es, nombre_en, nombre_zh, request.form['descripcion'],
                          int(request.form['cantidad']), precio_unitario_caja,
                          precio_unidad, # Nuevo valor de Precio Unidad
                          int(request.form['umbral_stock']), id))

            conn.commit()
            flash(t('btn_guardar_cambios'), 'success')
            conn.close()
            return redirect(url_for('listar_inventario'))
        except Exception as e:
            # Aquí se capturará el error "no such column: precio_unidad"
            flash(f'Error: {e}', 'danger')
            conn.close()
            # Redirigir de nuevo a la página de edición con el error
            return redirect(url_for('editar_inventario', id=id))

    # --- PARTE 2: MOSTRAR FORMULARIO (GET) ---
    # Nota: Tu código tiene esta parte duplicada, mantendré la última versión.
    conn.row_factory = sqlite3.Row  # Importante para poder llamar a las columnas por nombre
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inventario WHERE id=?", (id,))
    prod = cursor.fetchone()
    conn.close()

    return render_template('inventario/editar.html', producto=prod)


@app.route('/inventario/eliminar/<int:id>', methods=['POST'])
@flask_login.login_required
def eliminar_inventario(id):
    conn = crear_conexion()
    conn.execute("DELETE FROM inventario WHERE id=?", (id,))
    conn.commit()
    conn.close()
    flash('Eliminado', 'success')
    return redirect(url_for('listar_inventario'))


@app.route('/inventario/exportar_pdf')
@flask_login.login_required
def exportar_inventario_pdf():
    conn = crear_conexion()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT nombre, descripcion, cantidad, precio_unitario, umbral_stock FROM inventario ORDER BY nombre")
    data = cursor.fetchall()
    conn.close()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    story = [Paragraph("<b>Reporte Inventario</b>", getSampleStyleSheet()['Heading1']), Spacer(1, 12)]
    t_data = [['Nombre', 'Desc', 'Cant', 'Precio', 'Min']]
    for i in data: t_data.append([i[0], i[1], str(i[2]), f"{i[3]:.2f}", str(i[4])])

    table = Table(t_data)
    table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 1, colors.black)]))
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    return make_response(buffer.getvalue(), 200,
                         {'Content-Type': 'application/pdf', 'Content-Disposition': 'attachment; filename=inv.pdf'})


# =============================================================================
# RUTAS: COTIZACIONES
# =============================================================================

@app.route('/cotizaciones')
@flask_login.login_required
def listar_cotizaciones():
    conn = crear_conexion()
    cursor = conn.cursor()
    search = request.args.get('search_query', '').strip()

    sql = '''SELECT c.id, c.cliente_nombre, c.fecha, c.total, c.estado, u.nombre, c.tipo_pago 
             FROM cotizaciones c JOIN usuarios u ON c.usuario_id = u.id'''
    if search:
        sql += " WHERE c.cliente_nombre LIKE ? ORDER BY c.fecha DESC"
        cursor.execute(sql, ('%' + search + '%',))
    else:
        sql += " ORDER BY c.fecha DESC"
        cursor.execute(sql)

    lista = []
    for row in cursor.fetchall():
        r = list(row)
        try:
            r[2] = datetime.datetime.strptime(str(r[2]).split('.')[0], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y')
        except:
            pass
        lista.append(tuple(r))
    conn.close()
    return render_template('cotizaciones/listar.html', cotizaciones=lista, search_query=search)


@app.route('/aprobar_cotizacion/<int:cotizacion_id>', methods=['POST'])
@flask_login.login_required
def route_aprobar_cotizacion(cotizacion_id):
    pago = request.form.get('tipo_pago', 'Efectivo')
    res = aprobar_cotizacion(cotizacion_id, pago)
    if res['success']:
        flash(res['message'], 'success')
    else:
        flash(res['message'], 'danger')
    return redirect(url_for('listar_cotizaciones'))


@app.route('/cotizaciones/nueva', methods=['GET', 'POST'])
@flask_login.login_required
def nueva_cotizacion():
    conn = crear_conexion()
    cursor = conn.cursor()
    if request.method == 'POST':
        try:
            cliente = request.form['cliente_nombre']
            celular = request.form.get('cliente_celular')
            email = request.form.get('cliente_email')
            ruc = request.form.get('cliente_ruc')
            pago = request.form['tipo_pago']
            estado = request.form.get('estado_cotizacion', 'Pendiente')
            prod_json = request.form.get('productos_seleccionados', '[]')
            prods = json.loads(prod_json)

            if not prods:
                # Aquí se debería usar la traducción
                flash('Agregue productos', 'danger')
                return redirect(url_for('nueva_cotizacion'))

            conn.execute('BEGIN TRANSACTION;')
            total = 0
            items_listos = []

            for p in prods:
                cursor.execute("SELECT cantidad, costo_adquisicion FROM inventario WHERE id=?", (p['id'],))
                inv = cursor.fetchone()
                if estado == 'Aprobada' and int(p['cantidad']) > inv[0]:
                    # Aquí se debería usar la traducción
                    raise Exception(f"Stock insuficiente: {p['descripcion']}")

                sub = float(p['precio']) * int(p['cantidad'])
                total += sub
                items_listos.append({
                    'id': p['id'], 'cant': int(p['cantidad']), 'desc': p['descripcion'],
                    'precio': float(p['precio']), 'costo': inv[1] or 0
                })

            fecha = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute("""INSERT INTO cotizaciones (cliente_nombre, cliente_celular, cliente_email, cliente_ruc, 
                              fecha, total, estado, usuario_id, tipo_pago) VALUES (?,?,?,?,?,?,?,?,?)""",
                           (cliente, celular, email, ruc, fecha, total, estado, flask_login.current_user.id, pago))
            cot_id = cursor.lastrowid

            costo_total = 0
            for it in items_listos:
                cursor.execute(
                    "INSERT INTO cotizacion_detalles (cotizacion_id, producto_id, cantidad, descripcion, precio_unitario_cotizado, costo_unitario) VALUES (?,?,?,?,?,?)",
                    (cot_id, it['id'], it['cant'], it['desc'], it['precio'], it['costo']))
                if estado == 'Aprobada':
                    cursor.execute("UPDATE inventario SET cantidad=cantidad-? WHERE id=?", (it['cant'], it['id']))
                    costo_total += it['costo'] * it['cant']

            if estado == 'Aprobada':
                cursor.execute(
                    "INSERT INTO movimientos_caja (cotizacion_id, fecha, ingreso_total, costo_total, tipo_pago) VALUES (?,?,?,?,?)",
                    (cot_id, fecha, total, costo_total, pago))

            conn.commit()
            # Aquí se debería usar la traducción
            flash('Creada correctamente', 'success')
            return redirect(url_for('listar_cotizaciones'))
        except Exception as e:
            conn.rollback()
            # Aquí se debería usar la traducción
            flash(f'Error: {e}', 'danger')
            return redirect(url_for('nueva_cotizacion'))
        finally:
            conn.close()
    else:
        cursor.execute("SELECT id, nombre, precio_unitario, descripcion FROM inventario ORDER BY nombre")
        inv_data = cursor.fetchall()
        conn.close()

        # --- MODIFICACIÓN CLAVE AQUÍ ---
        productos_inventario_traducidos = []
        for p in inv_data:
            producto_traducido = (
                p[0],  # ID (sin traducción)
                t(p[1]),  # NOMBRE traducido
                p[2],  # PRECIO (sin traducción)
                t(p[3]) if p[3] else '',  # DESCRIPCIÓN traducida (si existe)
            )
            productos_inventario_traducidos.append(producto_traducido)

        return render_template('cotizaciones/nueva.html', productos_inventario=productos_inventario_traducidos)

@app.route('/cotizaciones/detalle/<int:id>')
@flask_login.login_required
def detalle_cotizacion(id):
    conn = crear_conexion()
    cursor = conn.cursor()
    cursor.execute('''SELECT c.id, c.cliente_nombre, c.cliente_celular, c.cliente_email, c.cliente_ruc, 
                      c.fecha, c.total, c.estado, u.nombre, c.tipo_pago
                      FROM cotizaciones c JOIN usuarios u ON c.usuario_id = u.id WHERE c.id = ?''', (id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        flash('No encontrada', 'danger')
        return redirect(url_for('listar_cotizaciones'))

    cot = list(row)
    try:
        cot[5] = datetime.datetime.strptime(str(cot[5]).split('.')[0], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y %H:%M')
    except:
        pass

    cursor.execute('''SELECT cd.cantidad, i.nombre, cd.descripcion, cd.precio_unitario_cotizado 
                      FROM cotizacion_detalles cd JOIN inventario i ON cd.producto_id = i.id 
                      WHERE cd.cotizacion_id = ?''', (id,))
    detalles = cursor.fetchall()
    conn.close()
    return render_template('cotizaciones/detalle.html', cotizacion=cot, detalles=detalles)


@app.route('/cotizaciones/editar/<int:id>', methods=['GET', 'POST'])
@flask_login.login_required
def editar_cotizacion(id):
    conn = crear_conexion()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT estado, total FROM cotizaciones WHERE id = ?", (id,))
    row_ant = cursor.fetchone()
    if not row_ant:
        conn.close()
        return redirect(url_for('listar_cotizaciones'))

    estado_anterior = row_ant['estado']

    if request.method == 'POST':
        try:
            cliente = request.form['cliente_nombre']
            celular = request.form.get('cliente_celular')
            email = request.form.get('cliente_email')
            ruc = request.form.get('cliente_ruc')
            nuevo_estado = request.form['estado']
            tipo_pago = request.form['tipo_pago']
            prod_json = request.form.get('productos_seleccionados', '[]')
            nuevos_productos = json.loads(prod_json)

            if not nuevos_productos:
                raise Exception("Debe haber al menos un producto.")

            conn.execute('BEGIN TRANSACTION;')

            cursor.execute("""
                UPDATE cotizaciones SET cliente_nombre=?, cliente_celular=?, cliente_email=?, 
                cliente_ruc=?, estado=?, tipo_pago=? WHERE id=?
            """, (cliente, celular, email, ruc, nuevo_estado, tipo_pago, id))

            if estado_anterior == 'Aprobada':
                cursor.execute("SELECT producto_id, cantidad FROM cotizacion_detalles WHERE cotizacion_id=?", (id,))
                viejos = cursor.fetchall()
                for pid, cant in viejos:
                    cursor.execute("UPDATE inventario SET cantidad = cantidad + ? WHERE id=?", (cant, pid))
                cursor.execute("DELETE FROM movimientos_caja WHERE cotizacion_id=?", (id,))

            cursor.execute("DELETE FROM cotizacion_detalles WHERE cotizacion_id=?", (id,))

            total_venta = 0
            costo_total_venta = 0

            for p in nuevos_productos:
                pid = int(p['id'])
                cant = int(p['cantidad'])
                precio = float(p['precio'])
                desc = p.get('descripcion', '')

                cursor.execute("SELECT costo_adquisicion FROM inventario WHERE id=?", (pid,))
                costo_unit = cursor.fetchone()['costo_adquisicion'] or 0

                total_venta += precio * cant
                costo_total_venta += costo_unit * cant

                cursor.execute("""
                    INSERT INTO cotizacion_detalles (cotizacion_id, producto_id, cantidad, descripcion, precio_unitario_cotizado, costo_unitario)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (id, pid, cant, desc, precio, costo_unit))

            cursor.execute("UPDATE cotizaciones SET total=? WHERE id=?", (total_venta, id))

            if nuevo_estado == 'Aprobada':
                for p in nuevos_productos:
                    cursor.execute("UPDATE inventario SET cantidad = cantidad - ? WHERE id=?",
                                   (int(p['cantidad']), int(p['id'])))

                fecha_hoy = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute("""
                    INSERT INTO movimientos_caja (cotizacion_id, fecha, ingreso_total, costo_total, tipo_pago)
                    VALUES (?, ?, ?, ?, ?)
                """, (id, fecha_hoy, total_venta, costo_total_venta, tipo_pago))

                cursor.execute("UPDATE cotizaciones SET fecha_aprobacion = ? WHERE id = ?", (fecha_hoy, id))
            else:
                cursor.execute("UPDATE cotizaciones SET fecha_aprobacion = NULL WHERE id = ?", (id,))

            conn.commit()
            flash('Cotización actualizada y procesada correctamente.', 'success')
            return redirect(url_for('listar_cotizaciones'))

        except Exception as e:
            conn.rollback()
            flash(f'Error: {e}', 'danger')
            return redirect(url_for('editar_cotizacion', id=id))
        finally:
            conn.close()

    cursor.execute("SELECT * FROM cotizaciones WHERE id=?", (id,))
    cot = cursor.fetchone()
    cursor.execute('''SELECT cd.producto_id, i.nombre as nombre_producto, cd.descripcion, cd.cantidad, cd.precio_unitario_cotizado 
                      FROM cotizacion_detalles cd JOIN inventario i ON cd.producto_id = i.id WHERE cd.cotizacion_id = ?''',
                   (id,))
    detalles = [dict(row) for row in cursor.fetchall()]
    cursor.execute("SELECT id, nombre, precio_unitario, descripcion FROM inventario")
    inv = cursor.fetchall()
    conn.close()
    return render_template('cotizaciones/editar.html', cotizacion=cot, detalles=detalles, productos_inventario=inv)


@app.route('/cotizaciones/eliminar/<int:id>', methods=['POST'])
@flask_login.login_required
def eliminar_cotizacion(id):
    conn = crear_conexion()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT estado FROM cotizaciones WHERE id=?", (id,))
        est = cursor.fetchone()[0]
        conn.execute("BEGIN TRANSACTION;")
        if est == 'Aprobada':
            cursor.execute("SELECT producto_id, cantidad FROM cotizacion_detalles WHERE cotizacion_id=?", (id,))
            for pid, cant in cursor.fetchall():
                cursor.execute("UPDATE inventario SET cantidad=cantidad+? WHERE id=?", (cant, pid))
        cursor.execute("DELETE FROM movimientos_caja WHERE cotizacion_id=?", (id,))
        cursor.execute("DELETE FROM cotizacion_detalles WHERE cotizacion_id=?", (id,))
        cursor.execute("DELETE FROM cotizaciones WHERE id=?", (id,))
        conn.commit()
        flash('Eliminada', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error: {e}', 'danger')
    finally:
        conn.close()
    return redirect(url_for('listar_cotizaciones'))


@app.route('/cotizaciones/rechazar/<int:id>')
@flask_login.login_required
def rechazar_cotizacion(id):
    conn = crear_conexion()
    try:
        conn.execute("BEGIN TRANSACTION;")
        cursor = conn.cursor()
        cursor.execute("SELECT estado FROM cotizaciones WHERE id=?", (id,))
        estado_ant = cursor.fetchone()[0]

        if estado_ant == 'Aprobada':
            cursor.execute("SELECT producto_id, cantidad FROM cotizacion_detalles WHERE cotizacion_id=?", (id,))
            for pid, cant in cursor.fetchall():
                cursor.execute("UPDATE inventario SET cantidad=cantidad+? WHERE id=?", (cant, pid))
            cursor.execute("DELETE FROM movimientos_caja WHERE cotizacion_id=?", (id,))

        conn.execute("UPDATE cotizaciones SET estado='Rechazado' WHERE id=?", (id,))
        conn.commit()
        flash('Rechazada', 'info')
    except:
        conn.rollback()
    conn.close()
    return redirect(url_for('detalle_cotizacion', id=id))


@app.route('/cotizaciones/exportar_pdf/<int:id>')
@flask_login.login_required
def exportar_cotizacion_pdf(id):
    conn = crear_conexion()
    cursor = conn.cursor()

    # PASO 1: SELECCIONAR CLIENTE_CELULAR Y CLIENTE_RUC
    cursor.execute('''SELECT c.id, c.cliente_nombre, c.cliente_celular, c.cliente_email, c.cliente_ruc, 
                      c.fecha, c.total, c.estado, u.nombre, c.tipo_pago
                      FROM cotizaciones c JOIN usuarios u ON c.usuario_id = u.id WHERE c.id = ?''', (id,))
    cot_data = cursor.fetchone()
    if not cot_data:
        conn.close()
        flash('Cotización no encontrada', 'danger')
        return redirect(url_for('listar_cotizaciones'))

    # PASO 2: MAPEO DE DATOS (Asegurando los índices correctos)
    # [0]id, [1]cliente_nombre, [2]cliente_celular, [3]cliente_email, [4]cliente_ruc, [5]fecha, [6]total, [9]tipo_pago
    cotizacion = {
        'id': cot_data[0],
        'cliente_nombre': cot_data[1],
        'cliente_celular': cot_data[2] or '',  # Usar cadena vacía si es nulo
        'cliente_ruc': cot_data[4] or '',  # Usar cadena vacía si es nulo
        'fecha': cot_data[5],
        'total': cot_data[6],
        'tipo_pago': cot_data[9]
    }

    cursor.execute('''SELECT cd.cantidad, i.nombre, cd.descripcion, cd.precio_unitario_cotizado 
                      FROM cotizacion_detalles cd JOIN inventario i ON cd.producto_id = i.id 
                      WHERE cd.cotizacion_id = ?''', (id,))
    detalles = cursor.fetchall()
    conn.close()

    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=50, rightMargin=50, topMargin=50, bottomMargin=50)
        story = []
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name='TableData', fontSize=10, leading=12))
        styles.add(ParagraphStyle(name='RightAligned', alignment=TA_RIGHT, fontName='Helvetica-Bold'))
        styles.add(ParagraphStyle(name='MediosPagoHeader', fontSize=8, leading=10, alignment=TA_RIGHT))
        # Se elimina el estilo InfoClienteHeader y no se usa la tabla.

        # --- CABECERA DE EMPRESA ---
        logo_path = os.path.join(app.root_path, 'static', 'images', 'donglai.png')
        try:
            logo = Image(logo_path, width=40, height=40)
        except:
            logo = Spacer(1, 1)

        info_empresa = Paragraph(
            "<b>DING FENG IMPORT AND EXPORT TRADE S.A.C.</b><br/>RUC: 20608796859<br/>Teléfono: 929 877 778",
            styles['Normal']
        )

        medios_pago_html = "<b>MEDIOS DE PAGO</b><br/>BCP (S/): 194-7100461027<br/>CCI BCP: 00219400710046102796<br/>YAPE: 900 654 001 - XIUYING YU"
        medios_pago = Paragraph(medios_pago_html, styles['MediosPagoHeader'])

        header_table_data = [[logo, info_empresa, medios_pago]]
        header_table = Table(header_table_data, colWidths=[50, 250, 200])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (1, 0), (1, 0), 'LEFT'),
            ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 12))

        # PASO 3: RECONSTRUCCIÓN EN UNA SOLA LÍNEA (PARAGRAPH)
        fecha_fmt = datetime.datetime.strptime(str(cotizacion['fecha']).split(' ')[0], '%Y-%m-%d').strftime('%d/%m/%Y')

        # Construye las partes de RUC y Celular solo si tienen valor.
        ruc_text = f" | RUC: {cotizacion['cliente_ruc']}" if cotizacion['cliente_ruc'] else ""
        celular_text = f" | Teléfono: {cotizacion['cliente_celular']}" if cotizacion['cliente_celular'] else ""

        info_line = f"<b>COTIZACIÓN #{cotizacion['id']}</b> | Fecha: {fecha_fmt} | Cliente: {cotizacion['cliente_nombre']}{ruc_text}{celular_text} | Pago: {cotizacion['tipo_pago']}"
        story.append(Paragraph(info_line, styles['Normal']))
        story.append(Spacer(1, 12))

        # --- TABLA DE PRODUCTOS ---
        data = [['#', 'Producto', 'Descripción', 'Cant', 'P. Unit', 'Subtotal']]
        total_acumulado = 0

        for i, item in enumerate(detalles, 1):
            # ... (Lógica de la tabla de productos, sin cambios) ...
            cant = item[0]
            nombre = item[1]
            desc = item[2] if item[2] else ""
            precio = item[3]
            subtotal = cant * precio
            total_acumulado += subtotal

            data.append([
                str(i),
                Paragraph(f"<b>{nombre}</b>", styles['TableData']),
                Paragraph(desc, styles['TableData']),
                str(cant),
                f"S/. {precio:.2f}",
                f"S/. {subtotal:.2f}"
            ])

        col_widths = [30, 110, 150, 40, 80, 80]
        table = Table(data, colWidths=col_widths)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7'))
        ]))
        story.append(table)
        story.append(Spacer(1, 12))

        # --- TOTAL ---
        total_html = f"<b>TOTAL: S/. {total_acumulado:.2f}</b>"
        total_table = Table([[Paragraph(total_html, styles['RightAligned'])]], colWidths=[490])
        total_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7'))
        ]))
        story.append(total_table)

        doc.build(story)
        buffer.seek(0)
        return send_file(buffer, mimetype='application/pdf', as_attachment=True, download_name=f'Cotizacion_{id}.pdf')
    except Exception as e:
        print(f"Error al generar PDF: {e}")
        flash(f'Error al generar PDF: {e}', 'danger')
        return redirect(url_for('listar_cotizaciones'))

# =============================================================================
# RUTAS: CIERRE DE CAJA
# =============================================================================

@app.route('/cierre_caja', methods=['GET', 'POST'])
@flask_login.login_required
def cierre_caja():
    hoy_ini = datetime.datetime.now().strftime('%Y-%m-%d 00:00:00')
    hoy_fin = datetime.datetime.now().strftime('%Y-%m-%d 23:59:59')

    if request.method == 'POST':
        try:
            res = crear_cierre_caja(
                hoy_ini, hoy_fin, flask_login.current_user.id,
                float(request.form.get('monto_apertura', 0)),
                float(request.form.get('ingresos_extra', 0)),
                float(request.form.get('egresos', 0)),
                float(request.form.get('efectivo_en_caja', 0)),
                request.form.get('observaciones', '')
            )
            if res['success']:
                flash('Cierre Guardado', 'success')
                return redirect(url_for('historial_cierre_caja'))
            else:
                flash(res['message'], 'danger')
        except:
            flash('Datos inválidos', 'danger')

    datos = obtener_ventas_aprobadas_para_cierre(hoy_ini, hoy_fin)
    ganancia = datos['total_ventas'] - datos['costo_total_cierre']

    return render_template('cierre_caja/cierre.html',
                           total_ventas=datos['total_ventas'],
                           desglose_ventas=datos['desglose_pagos'],
                           total_cogs_dia=datos['costo_total_cierre'],
                           ganancia_bruta_dia=ganancia,
                           movimientos_db=datos['movimientos'],
                           fecha_hoy=datetime.date.today().strftime('%d/%m/%Y'))


@app.route('/historial_cierre_caja')
@flask_login.login_required
def historial_cierre_caja():
    conn = crear_conexion()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. Obtener datos básicos de los cierres
    cursor.execute(
        'SELECT c.*, u.nombre FROM cierres_caja c JOIN usuarios u ON c.usuario_id = u.id ORDER BY c.fecha DESC')
    filas = cursor.fetchall()

    cierres = []
    for f in filas:
        item = dict(f)

        # Parsear desglose
        try:
            item['desglose_pagos'] = json.loads(item['desglose_pagos'])
        except:
            item['desglose_pagos'] = {}

        # Calcular finales
        ap = item.get('monto_apertura') or 0.0
        ef = item.get('efectivo_teorico') or 0.0
        ing = item.get('ingresos_extra') or 0.0
        eg = item.get('egresos') or 0.0
        item['efectivo_teorico_final'] = ap + ef + ing - eg

        # Formato de fecha
        try:
            item['fecha'] = datetime.datetime.strptime(str(item['fecha']).split('.')[0], '%Y-%m-%d %H:%M:%S').strftime(
                '%d/%m/%Y %H:%M')
        except:
            pass

        # ----------------------------------------------------------------
        # MAGIA PARA PRODUCTOS: Obtener los productos del día de ese cierre
        # ----------------------------------------------------------------
        # Usamos la fecha del cierre para buscar ventas de ESE día
        fecha_cierre_str = str(f['fecha']).split(' ')[0]  # Solo la parte YYYY-MM-DD

        # Consulta para traer los productos aprobados en esa fecha
        cursor.execute('''
            SELECT i.nombre, SUM(cd.cantidad) as cantidad, SUM(cd.cantidad * cd.precio_unitario_cotizado) as subtotal
            FROM movimientos_caja mc
            JOIN cotizaciones c ON mc.cotizacion_id = c.id
            JOIN cotizacion_detalles cd ON c.id = cd.cotizacion_id
            JOIN inventario i ON cd.producto_id = i.id
            WHERE date(mc.fecha) = date(?)
            GROUP BY i.nombre
        ''', (fecha_cierre_str,))

        prods_vendidos = []
        for p in cursor.fetchall():
            prods_vendidos.append({
                'nombre': p[0],
                'cantidad': p[1],
                'subtotal': p[2]
            })

        item['productos_vendidos'] = prods_vendidos
        # ----------------------------------------------------------------

        cierres.append(item)

    # 2. Resumen mensual
    cursor.execute('''
        SELECT STRFTIME('%Y-%m', fecha) as mes, 
        SUM(total_ventas), SUM(efectivo_teorico), SUM(otros_medios_teoricos), 
        SUM(costo_total_cierre), SUM(ganancia_bruta)
        FROM cierres_caja GROUP BY mes ORDER BY mes DESC
    ''')
    resumen = []
    for r in cursor.fetchall():
        resumen.append({
            'mes_ano': r[0],
            'total_ventas_mes': r[1] or 0,
            'efectivo_teorico_mes': r[2] or 0,
            'otros_medios_mes': r[3] or 0,
            'total_cogs_mes': r[4] or 0,
            'ganancia_bruta_mes': r[5] or 0
        })

    conn.close()
    return render_template('cierre_caja/historial.html', cierres=cierres, resumen=resumen)


@app.route('/cierre_caja/editar/<int:id>', methods=['GET', 'POST'])
@flask_login.login_required
def editar_cierre_caja(id):
    conn = crear_conexion()
    conn.row_factory = sqlite3.Row
    if request.method == 'POST':
        try:
            desglose = {}
            for k in request.form:
                if k.startswith('desglose_'):
                    desglose[k.replace('desglose_', '').capitalize()] = float(request.form[k])

            conn.execute("""UPDATE cierres_caja SET fecha=?, total_ventas=?, efectivo_en_caja=?, diferencia=?, 
                            observaciones=?, desglose_pagos=?, diferencia_total=?, monto_apertura=?, ingresos_extra=?, 
                            egresos=?, efectivo_teorico=?, otros_medios_teoricos=? WHERE id=?""",
                         (request.form['fecha'], float(request.form['total_ventas']),
                          float(request.form['efectivo_en_caja']),
                          float(request.form['diferencia_hidden']), request.form['observaciones'], json.dumps(desglose),
                          float(request.form['diferencia_total_hidden']), float(request.form['monto_apertura']),
                          float(request.form['ingresos_extra']), float(request.form['egresos']),
                          float(request.form['efectivo_teorico']), float(request.form['otros_medios_teoricos']), id))
            conn.commit()
            flash('Cierre actualizado', 'success')
            conn.close()
            return redirect(url_for('historial_cierre_caja'))
        except Exception as e:
            flash(f'Error: {e}', 'danger')
            conn.close()
            return redirect(url_for('editar_cierre_caja', id=id))

    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cierres_caja WHERE id=?", (id,))
    row = cursor.fetchone()
    conn.close()
    if not row: return redirect(url_for('historial_cierre_caja'))

    cierre = dict(row)
    try:
        cierre['desglose_pagos'] = json.loads(cierre['desglose_pagos'])
    except:
        cierre['desglose_pagos'] = {}

    ap = cierre.get('monto_apertura') or 0
    ef = cierre.get('efectivo_teorico') or 0
    ing = cierre.get('ingresos_extra') or 0
    eg = cierre.get('egresos') or 0
    cierre['efectivo_teorico_final'] = ap + ef + ing - eg
    cierre['cierre_total_dia'] = (cierre.get('efectivo_en_caja') or 0) + (cierre.get('otros_medios_teoricos') or 0)

    return render_template('cierre_caja/editar.html', cierre=cierre)


@app.route('/cierre_caja/guardar_edicion', methods=['POST'])
@flask_login.login_required
def guardar_edicion_cierre_caja():
    return editar_cierre_caja(request.form.get('id'))


# BUSCA ESTA PARTE EN TU CÓDIGO Y REEMPLÁZALA ASÍ:

@app.route('/eliminar_cierre_caja/<int:cierre_id>', methods=['POST'])  # <--- AGREGAR ESTO
@flask_login.login_required
def eliminar_cierre_caja(cierre_id):
    # Opcional: Validar si es admin
    # if flask_login.current_user.rol != 'admin':
    #     return redirect(url_for('historial_cierre_caja'))

    try:
        conn = crear_conexion()
        conn.execute("DELETE FROM cierres_caja WHERE id=?", (cierre_id,))
        conn.commit()
        conn.close()
        flash('Cierre eliminado correctamente', 'success')
    except Exception as e:
        flash('Error al eliminar: ' + str(e), 'danger')

    return redirect(url_for('historial_cierre_caja'))


@app.route('/cierre_caja/imprimir/<int:cierre_id>')
@flask_login.login_required
def imprimir_cierre_caja(cierre_id):
    conn = crear_conexion()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cierres_caja WHERE id=?", (cierre_id,))
    row = cursor.fetchone()
    conn.close()
    if not row: return redirect(url_for('historial_cierre_caja'))

    cierre = dict(row)
    try:
        cierre['desglose_pagos'] = json.loads(cierre['desglose_pagos'])
    except:
        cierre['desglose_pagos'] = {}

    ap = cierre.get('monto_apertura') or 0
    ef = cierre.get('efectivo_teorico') or 0
    ing = cierre.get('ingresos_extra') or 0
    eg = cierre.get('egresos') or 0
    cierre['efectivo_teorico_final'] = ap + ef + ing - eg

    html = render_template('cierre_caja/informe_pdf.html', cierre=cierre)
    pdf = io.BytesIO()
    pisa.CreatePDF(html, dest=pdf)
    pdf.seek(0)
    return send_file(pdf, as_attachment=True, download_name=f"Cierre_{cierre_id}.pdf", mimetype='application/pdf')


if __name__ == '__main__':
    inicializar_db()
    app.run(debug=True, host='0.0.0.0')