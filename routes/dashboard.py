"""Rutas de dashboard."""

# Registramos estas vistas en la instancia Flask existente para conservar las URL.
from app import *  # noqa: F401,F403
from routes.auth import admin_required, role_required

@app.route('/inicio')
@flask_login.login_required
def menu_inicio():
    return render_template('inicio.html')

# =============================================================================
# API: DATOS DEL DASHBOARD (USANDO BD)
# =============================================================================

@app.route('/api/dashboard_data')
@flask_login.login_required
def api_dashboard_data():
    conn = crear_conexion()
    cursor = conn.cursor()
    
    try:
        mes_actual = datetime.datetime.now().strftime('%Y-%m')
        cursor.execute('''
            SELECT COALESCE(SUM(ingreso_total), 0)
            FROM movimientos_caja
            WHERE strftime('%Y-%m', fecha) = ?
        ''', (mes_actual,))
        ventas_mes = float(cursor.fetchone()[0] or 0)
        
        hoy = datetime.datetime.now()
        inicio_semana = hoy - datetime.timedelta(days=hoy.weekday())
        ventas_semana = []
        labels_semana = []
        
        for i in range(7):
            dia = inicio_semana + datetime.timedelta(days=i)
            dia_str = dia.strftime('%Y-%m-%d')
            labels_semana.append(dia.strftime('%a'))
            
            cursor.execute('''
                SELECT COALESCE(SUM(ingreso_total), 0)
                FROM movimientos_caja
                WHERE date(fecha) = ?
            ''', (dia_str,))
            total_dia = float(cursor.fetchone()[0] or 0)
            ventas_semana.append(total_dia)
        
        cursor.execute("SELECT COUNT(*) FROM cotizaciones WHERE estado IN ('Pendiente', 'Parcial')")
        cotizaciones_pendientes = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT COUNT(*) FROM inventario')
        total_productos = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT COUNT(*) FROM inventario WHERE cantidad <= umbral_stock')
        stock_bajo = cursor.fetchone()[0] or 0
        
        cursor.execute('''
            SELECT c.id, c.cliente_nombre, c.total, c.estado, c.fecha
            FROM cotizaciones c
            ORDER BY c.fecha DESC
            LIMIT 5
        ''')
        cotizaciones_recientes = []
        for row in cursor.fetchall():
            cotizaciones_recientes.append({
                'id': row[0],
                'cliente': row[1],
                'total': float(row[2]) if row[2] else 0,
                'estado': row[3] or 'Pendiente',
                'fecha': row[4]
            })
        
        cursor.execute('''
            SELECT nombre, cantidad, umbral_stock 
            FROM inventario 
            WHERE cantidad <= umbral_stock 
            ORDER BY cantidad ASC 
            LIMIT 5
        ''')
        productos_stock_bajo = []
        for row in cursor.fetchall():
            productos_stock_bajo.append({
                'nombre': row[0],
                'cantidad': row[1] or 0,
                'umbral': row[2] or 5
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'data': {
                'ventas_mes': ventas_mes,
                'cotizaciones_pendientes': cotizaciones_pendientes,
                'total_productos': total_productos,
                'stock_bajo': stock_bajo,
                'ventas_semana': ventas_semana,
                'labels_semana': labels_semana,
                'cotizaciones_recientes': cotizaciones_recientes,
                'productos_stock_bajo': productos_stock_bajo,
                'timestamp': datetime.datetime.now().strftime('%H:%M:%S')
            }
        })
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)}), 500

# =============================================================================
# RUTAS: INVENTARIO (USANDO BASE DE DATOS)
# =============================================================================
