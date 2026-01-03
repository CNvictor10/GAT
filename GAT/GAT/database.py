import sqlite3
import datetime
import json
import random
import os
from werkzeug.security import generate_password_hash

DB_NAME = 'donglai.db'


def crear_conexion():
    """Crea conexión a la DB con row_factory para acceder por nombres de columna."""
    conn = sqlite3.connect(DB_NAME)
    # Permite acceder a los datos de las filas como un diccionario (por nombre de columna)
    conn.row_factory = sqlite3.Row
    return conn


def inicializar_db():
    """Crea tablas, añade columnas faltantes (migraciones) y datos iniciales."""
    conn = crear_conexion()
    cursor = conn.cursor()

    # --- FUNCIÓN INTERNA DE MIGRACIÓN (Soporte para Columnas Faltantes) ---
    def check_and_add_column(table, column, type, default=None):
        """Verifica si una columna existe y la añade si es necesario."""
        cursor.execute(f"PRAGMA table_info({table})")
        cols = [col[1] for col in cursor.fetchall()]
        if column not in cols:
            print(f"Migrando: Añadiendo '{column}' a '{table}'...")

            # Construcción segura del valor por defecto (sin comillas si es numérico)
            default_clause = ""
            if default is not None:
                if isinstance(default, (int, float)):
                    default_clause = f" DEFAULT {default}"
                else:  # Incluye strings como TEXT y JSON '{}'
                    default_clause = f" DEFAULT '{default}'"

            try:
                # Nota: Usamos f-string para ALTER TABLE y PRAGMA table_info ya que no admiten parámetros.
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {type}{default_clause}")
                conn.commit()  # Importante: hacer commit después de cada alteración
                print(f"Éxito: Columna {column} añadida a {table}.")
            except Exception as e:
                print(f"Error migración al añadir {column} a {table}: {e}")

    # 1. CREACIÓN DE TABLAS
    print("Creando o verificando tablas...")
    cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, email TEXT UNIQUE NOT NULL, 
        password TEXT NOT NULL, rol TEXT NOT NULL DEFAULT 'usuario', fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS inventario (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, descripcion TEXT, 
        cantidad INTEGER NOT NULL DEFAULT 0, precio_unitario REAL NOT NULL, 
        umbral_stock INTEGER DEFAULT 10, fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS cotizaciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT, cliente_nombre TEXT NOT NULL, cliente_celular TEXT, 
        cliente_email TEXT, cliente_ruc TEXT, fecha TEXT NOT NULL, total REAL NOT NULL, 
        estado TEXT NOT NULL DEFAULT 'pendiente', tipo_pago TEXT, usuario_id INTEGER NOT NULL,
        FOREIGN KEY (usuario_id) REFERENCES usuarios (id))''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS cotizacion_detalles (
        id INTEGER PRIMARY KEY AUTOINCREMENT, cotizacion_id INTEGER NOT NULL, producto_id INTEGER NOT NULL, 
        cantidad INTEGER NOT NULL, descripcion TEXT, precio_unitario_cotizado REAL NOT NULL, 
        FOREIGN KEY (cotizacion_id) REFERENCES cotizaciones (id), FOREIGN KEY (producto_id) REFERENCES inventario (id))''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS cierres_caja (
        id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL, hora TEXT NOT NULL, 
        total_ventas REAL NOT NULL, efectivo_en_caja REAL NOT NULL, diferencia REAL NOT NULL, 
        observaciones TEXT, usuario_id INTEGER NOT NULL, desglose_pagos TEXT NOT NULL, 
        FOREIGN KEY (usuario_id) REFERENCES usuarios (id))''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS movimientos_caja (
        id INTEGER PRIMARY KEY AUTOINCREMENT, cotizacion_id INTEGER NOT NULL, fecha TEXT NOT NULL, 
        ingreso_total REAL NOT NULL, costo_total REAL NOT NULL, tipo_pago TEXT NOT NULL, 
        FOREIGN KEY(cotizacion_id) REFERENCES cotizaciones(id))''')

    conn.commit()

    # 2. MIGRACIONES (Asegura que existan columnas nuevas)
    print("Iniciando migraciones de columnas...")

    # Columnas de Inventario
    check_and_add_column('inventario', 'precio_unidad', 'REAL', 0.0)
    check_and_add_column('inventario', 'costo_adquisicion', 'REAL', 0.0)
    check_and_add_column('inventario', 'nombre_en', 'TEXT', '')
    check_and_add_column('inventario', 'nombre_zh', 'TEXT', '')

    # Columnas de Cotizaciones y Detalles
    check_and_add_column('cotizaciones', 'fecha_aprobacion', 'TEXT', 'NULL')
    # === ESTA ES LA MIGRACIÓN CLAVE PARA LA DIRECCIÓN ===
    check_and_add_column('cotizaciones', 'cliente_direccion', 'TEXT', '')
    check_and_add_column('cotizacion_detalles', 'costo_unitario', 'REAL', 0.0)

    # Columna para tipo de pago en movimientos (aunque ya estaba en la creación, se deja para migrar viejas DBs)
    check_and_add_column('movimientos_caja', 'tipo_pago', 'TEXT', 'Efectivo')

    # Campos extendidos para Cierres de Caja
    check_and_add_column('cierres_caja', 'diferencia_total', 'REAL', 0.0)
    check_and_add_column('cierres_caja', 'monto_apertura', 'REAL', 0.0)
    check_and_add_column('cierres_caja', 'ingresos_extra', 'REAL', 0.0)
    check_and_add_column('cierres_caja', 'egresos', 'REAL', 0.0)
    check_and_add_column('cierres_caja', 'efectivo_teorico', 'REAL', 0.0)
    check_and_add_column('cierres_caja', 'otros_medios_teoricos', 'REAL', 0.0)
    check_and_add_column('cierres_caja', 'costo_total_cierre', 'REAL', 0.0)
    check_and_add_column('cierres_caja', 'ganancia_bruta', 'REAL', 0.0)
    check_and_add_column('cierres_caja', 'desglose_pagos', 'TEXT', '{}')

    # 3. ADMIN POR DEFECTO
    print("Verificando usuario administrador...")
    cursor.execute("SELECT COUNT(*) FROM usuarios WHERE email = 'admin@clinica.com'")
    if cursor.fetchone()[0] == 0:
        pwd = generate_password_hash('admin123')
        cursor.execute("INSERT INTO usuarios (nombre, email, password, rol) VALUES (?,?,?,?)",
                       ('Administrador', 'admin@clinica.com', pwd, 'admin'))
        conn.commit()

    # 4. DATOS DE INVENTARIO POR DEFECTO (para testing)
    print("Verificando datos de inventario de prueba...")
    cursor.execute("SELECT COUNT(*) FROM inventario")
    if cursor.fetchone()[0] == 0:
        print("Migrando: Añadiendo datos de inventario de prueba...")
        cursor.execute(
            "INSERT INTO inventario (nombre, nombre_en, nombre_zh, descripcion, cantidad, precio_unitario, precio_unidad, umbral_stock, costo_adquisicion) VALUES (?,?,?,?,?,?,?,?,?)",
            ('Producto de Prueba (Caja)', 'Test Product (Box)', '測試產品 (箱)',
             'Producto inicial para demostración. El Precio Unidad debería ser $5.00', 100, 50.00, 5.00, 10, 30.00)
        )
        conn.commit()

    conn.close()
    print("Inicialización y migración de la base de datos completada.")


# --- LÓGICA DE NEGOCIO ---

def aprobar_cotizacion(cotizacion_id, tipo_pago):
    """Convierte cotización en venta: descuenta stock y registra movimiento financiero."""
    conn = crear_conexion()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM cotizaciones WHERE id = ?", (cotizacion_id,))
        cot = cursor.fetchone()

        if not cot:
            return {"success": False, "message": f"Cotización ID {cotizacion_id} no encontrada."}
        if cot['estado'] == 'Aprobada':
            return {"success": False, "message": f"Cotización ID {cotizacion_id} ya ha sido aprobada previamente."}

        cursor.execute("SELECT * FROM cotizacion_detalles WHERE cotizacion_id = ?", (cotizacion_id,))
        detalles = cursor.fetchall()

        cogs = 0.0
        for d in detalles:
            # Descontar stock del inventario
            cursor.execute("UPDATE inventario SET cantidad = cantidad - ? WHERE id = ?",
                           (d['cantidad'], d['producto_id']))

            # Calcular Costo de Bienes Vendidos (COGS)
            # Utilizamos el costo_unitario registrado en el detalle de la cotización.
            # === REVISIÓN: Asegurar que se use 'costo_unitario' si existe ===
            costo = d['costo_unitario'] if d['costo_unitario'] is not None else 0.0
            cogs += costo * d['cantidad']

        fecha_aprob = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Actualizar estado de la cotización a Venta
        cursor.execute("UPDATE cotizaciones SET estado='Aprobada', tipo_pago=?, fecha_aprobacion=? WHERE id=?",
                       (tipo_pago, fecha_aprob, cotizacion_id))

        # Registrar el movimiento financiero en caja
        cursor.execute(
            "INSERT INTO movimientos_caja (cotizacion_id, fecha, ingreso_total, costo_total, tipo_pago) VALUES (?,?,?,?,?)",
            (cotizacion_id, fecha_aprob, cot['total'], cogs, tipo_pago))

        conn.commit()
        return {"success": True, "message": "Venta aprobada y registrada correctamente."}
    except sqlite3.IntegrityError as e:
        conn.rollback()
        return {"success": False, "message": f"Error de integridad (posiblemente stock negativo): {str(e)}"}
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": f"Error desconocido al aprobar la cotización: {str(e)}"}
    finally:
        conn.close()


def obtener_ventas_aprobadas_para_cierre(fecha_inicio, fecha_fin):
    """
    Obtiene totales, desglose de pagos y la lista detallada de movimientos
    aprobados dentro del rango de fechas para el proceso de cierre de caja.
    """
    conn = crear_conexion()
    cursor = conn.cursor()
    try:
        # 1. Totales (Ingreso total y Costo Total de Ventas/COGS)
        cursor.execute(
            "SELECT SUM(ingreso_total) as t, SUM(costo_total) as c FROM movimientos_caja WHERE fecha BETWEEN ? AND ?",
            (fecha_inicio, fecha_fin))
        res = cursor.fetchone()
        total = res['t'] or 0.0
        cogs = res['c'] or 0.0

        # 2. Desglose por Tipo de Pago
        cursor.execute(
            "SELECT tipo_pago, SUM(ingreso_total) as s FROM movimientos_caja WHERE fecha BETWEEN ? AND ? GROUP BY tipo_pago",
            (fecha_inicio, fecha_fin))
        # Convierte el resultado a un diccionario: {'Efectivo': 100.0, 'Tarjeta': 50.0}
        desglose = {row['tipo_pago']: round(row['s'] or 0.0, 2) for row in cursor.fetchall()}

        # 3. LISTA DETALLADA PARA LA TABLA/Reporte
        cursor.execute("""
            SELECT m.ingreso_total, m.tipo_pago, m.fecha, c.cliente_nombre, c.id as cot_id
            FROM movimientos_caja m 
            JOIN cotizaciones c ON m.cotizacion_id = c.id
            WHERE m.fecha BETWEEN ? AND ?
            ORDER BY m.fecha DESC
        """, (fecha_inicio, fecha_fin))
        movimientos = [dict(row) for row in cursor.fetchall()]

        return {
            "total_ventas": round(total, 2),
            "costo_total_cierre": round(cogs, 2),
            "desglose_pagos": desglose,
            "movimientos": movimientos
        }
    except Exception as e:
        print(f"Error obteniendo ventas para cierre: {e}")
        return {"total_ventas": 0, "costo_total_cierre": 0, "desglose_pagos": {}, "movimientos": []}
    finally:
        conn.close()


def crear_cierre_caja(inicio, fin, uid, apertura, extra, egresos, fisico, obs):
    """
    Guarda el registro final del cierre de caja, calculando las diferencias y la ganancia.
    """
    datos = obtener_ventas_aprobadas_para_cierre(inicio, fin)
    total_ventas = datos['total_ventas']
    cogs = datos['costo_total_cierre']

    # --- CÁLCULOS FINANCIEROS TEÓRICOS ---
    efectivo_ventas = datos['desglose_pagos'].get('Efectivo', 0.0)
    otros_medios_teoricos = total_ventas - efectivo_ventas
    efectivo_teorico = apertura + efectivo_ventas + extra - egresos
    diferencia = fisico - efectivo_teorico
    ganancia = total_ventas - cogs

    conn = crear_conexion()
    try:
        fecha = datetime.datetime.now().strftime('%Y-%m-%d')
        hora = datetime.datetime.now().strftime('%H:%M:%S')

        conn.execute("""
            INSERT INTO cierres_caja (fecha, hora, total_ventas, efectivo_en_caja, diferencia, 
            observaciones, usuario_id, desglose_pagos, monto_apertura, ingresos_extra, egresos, 
            efectivo_teorico, otros_medios_teoricos, costo_total_cierre, ganancia_bruta, diferencia_total)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (fecha, hora, total_ventas, fisico, diferencia, obs, uid, json.dumps(datos['desglose_pagos']),
              apertura, extra, egresos, efectivo_teorico, otros_medios_teoricos, cogs, ganancia, diferencia))

        conn.commit()
        return {"success": True, "message": "Cierre de caja registrado exitosamente."}
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": f"Error al registrar cierre de caja: {str(e)}"}
    finally:
        conn.close()


if __name__ == '__main__':
    # Ejecuta esta línea cuando se corre el script directamente para configurar la DB.
    inicializar_db()
    print("Base de datos Donglai.db lista para usar.")