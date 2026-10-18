from flask import Flask, render_template, request, redirect, url_for, flash, session, make_response, jsonify, send_file
import flask_login
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import sqlite3
import json
import io
import os
from lenguajes import obtener_texto

# --- IMPORTACIONES DE LÓGICA DE BASE DE DATOS ---
from database import (
    crear_conexion, asegurar_columna_dni_usuarios,
    asegurar_columna_unidades_por_caja, asegurar_columna_imagen_producto, asegurar_columnas_administracion_usuarios,
    asegurar_columnas_razon_social_cotizaciones, asegurar_columnas_folios_y_cierres,
    registrar_pago_cotizacion, crear_cierre_caja,
    obtener_ventas_aprobadas_para_cierre,
    sincronizar_inventario_desde_excel,
)

asegurar_columna_unidades_por_caja()
asegurar_columna_imagen_producto()
asegurar_columnas_razon_social_cotizaciones()
asegurar_columnas_folios_y_cierres()

# --- IMPORTACIONES PARA PDF ---
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 15 * 1024 * 1024
app.secret_key = os.environ.get('GAT_SECRET_KEY') or os.environ.get('SECRET_KEY') or os.urandom(32)
if not os.environ.get('GAT_SECRET_KEY') and not os.environ.get('SECRET_KEY'):
    app.logger.warning('GAT_SECRET_KEY no está configurada; las sesiones se cerrarán al reiniciar la app.')

# --- CONFIGURACIÓN LOGIN ---
login_manager = flask_login.LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ==================================================
#  FUNCIONES PARA MANEJAR INVENTARIO DESDE BD
# ==================================================

def obtener_inventario_desde_bd():
    """Obtiene todos los productos desde la base de datos"""
    try:
        conn = crear_conexion()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, nombre, nombre_en, nombre_zh, descripcion, 
                   cantidad, precio_unitario, precio_unidad, umbral_stock, costo_adquisicion, imagen
            FROM inventario 
            ORDER BY nombre
        """)
        productos = []
        for row in cursor.fetchall():
            productos.append({
                'id': row[0],
                'nombre': row[1],
                'nombre_en': row[2] or '',
                'nombre_zh': row[3] or '',
                'descripcion': row[4] or '',
                'cantidad': row[5] or 0,
                'precio_unitario': row[6] or 0,
                'precio_unidad': row[7] or 0,
                'umbral_stock': row[8] or 5,
                'costo_adquisicion': row[9] or 0,
                'imagen': row[10] or ''
            })
        conn.close()
        return productos
    except Exception as e:
        print(f"Error obteniendo inventario: {e}")
        return []

def obtener_producto_por_id_bd(producto_id):
    """Obtiene un producto específico desde la base de datos"""
    conn = crear_conexion()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, nombre, nombre_en, nombre_zh, descripcion, 
               cantidad, precio_unitario, precio_unidad, umbral_stock, costo_adquisicion, unidades_por_caja, imagen
        FROM inventario 
        WHERE id = ?
    """, (producto_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            'id': row[0],
            'nombre': row[1],
            'nombre_en': row[2] or '',
            'nombre_zh': row[3] or '',
            'descripcion': row[4] or '',
            'cantidad': row[5] or 0,
            'precio_unitario': row[6] or 0,
            'precio_unidad': row[7] or 0,
            'umbral_stock': row[8] or 5,
            'costo_adquisicion': row[9] or 0,
            'unidades_por_caja': row[10] or 0,
            'imagen': row[11] or ''
        }
    return None

def get_productos_bajo_stock_bd():
    """Obtiene productos con stock bajo desde la base de datos"""
    conn = crear_conexion()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, nombre, cantidad, umbral_stock 
        FROM inventario 
        WHERE cantidad <= umbral_stock
        ORDER BY cantidad ASC
    """)
    productos = []
    for row in cursor.fetchall():
        productos.append({
            'id': row[0],
            'nombre': row[1],
            'cantidad': row[2] or 0,
            'umbral_stock': row[3] or 5
        })
    conn.close()
    return productos

def buscar_productos_bd(query):
    """Busca productos en la base de datos"""
    conn = crear_conexion()
    cursor = conn.cursor()
    query = f"%{query}%"
    cursor.execute("""
        SELECT id, nombre, nombre_en, nombre_zh, descripcion, 
               cantidad, precio_unitario, precio_unidad, umbral_stock, costo_adquisicion, imagen
        FROM inventario 
        WHERE nombre LIKE ? OR descripcion LIKE ? OR nombre_en LIKE ? OR nombre_zh LIKE ?
        ORDER BY nombre
    """, (query, query, query, query))
    productos = []
    for row in cursor.fetchall():
        productos.append({
            'id': row[0],
            'nombre': row[1],
            'nombre_en': row[2] or '',
            'nombre_zh': row[3] or '',
            'descripcion': row[4] or '',
            'cantidad': row[5] or 0,
            'precio_unitario': row[6] or 0,
            'precio_unidad': row[7] or 0,
            'umbral_stock': row[8] or 5,
            'costo_adquisicion': row[9] or 0,
            'imagen': row[10] or ''
        })
    conn.close()
    return productos

# ==================================================
#  FUNCIONES AUXILIARES
# ==================================================

# ==================================================
#  CONFIGURACIÓN DE IDIOMAS
# ==================================================

IDIOMAS_DISPONIBLES = ('es', 'en', 'zh')

def idioma_de_solicitud():
    preferencias = request.accept_languages
    idioma = preferencias.best_match(IDIOMAS_DISPONIBLES)
    if idioma:
        return idioma
    for etiqueta, calidad in preferencias:
        idioma_base = etiqueta.lower().replace('_', '-').split('-', 1)[0]
        if calidad > 0 and idioma_base in IDIOMAS_DISPONIBLES:
            return idioma_base
    return 'es'

def locale_de_solicitud():
    return {'es': 'es-PE', 'en': 'en-US', 'zh': 'zh-TW'}.get(idioma_de_solicitud(), 'es-PE')

def t(clave):
    return obtener_texto(clave, idioma_de_solicitud())

@app.context_processor
def inject_globals():
    return dict(
        t=t, 
        idioma_actual=idioma_de_solicitud(),
        locale_actual=locale_de_solicitud(),
        datetime=datetime.datetime
    )


# =============================================================================
# INICIO Y REGISTRO DE RUTAS
# =============================================================================

# Registrar rutas agrupadas por módulo funcional.
# El alias mantiene compatibles `python app.py` y las importaciones normales.
import sys
sys.modules.setdefault('app', sys.modules[__name__])
import routes.auth  # noqa: F401,E402
import routes.admin  # noqa: F401,E402
import routes.dashboard  # noqa: F401,E402
import routes.inventory  # noqa: F401,E402
import routes.quotes  # noqa: F401,E402
import routes.cash_closing  # noqa: F401,E402

if __name__ == '__main__':
    print("🚀 Iniciando aplicación...")
    
    try:
        productos = obtener_inventario_desde_bd()
        print(f"📦 Productos en inventario: {len(productos)}")
        if len(productos) == 0:
            print("⚠️ La base de datos está vacía. Ejecuta database.py primero.")
    except Exception as e:
        print(f"❌ Error: {e}")
        print("⚠️ La base de datos no existe o está corrupta.")
        print("🔧 Ejecuta: python database.py para crearla")
    
    debug = os.environ.get('GAT_DEBUG', '').strip().lower() in {'1', 'true', 'yes', 'si'}
    host = os.environ.get('GAT_HOST', '127.0.0.1')
    port = int(os.environ.get('GAT_PORT', '5000'))
    app.run(debug=debug, host=host, port=port)
