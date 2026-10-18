"""Rutas de cash closing."""

# Registramos estas vistas en la instancia Flask existente para conservar las URL.
from app import *  # noqa: F401,F403
from routes.auth import role_required

def obtener_cotizaciones_del_dia(conn, fecha_operativa):
    cursor = conn.cursor()
    cursor.execute('''
        SELECT mc.cotizacion_id, mc.fecha AS fecha_pago, mc.ingreso_total,
               mc.tipo_pago, c.numero_cotizacion, c.cliente_nombre,
               c.cliente_celular, c.total AS total_cotizacion, c.estado,
               u.nombre AS creador
        FROM movimientos_caja mc
        JOIN cotizaciones c ON c.id = mc.cotizacion_id
        LEFT JOIN usuarios u ON u.id = c.usuario_id
        WHERE date(mc.fecha) = ?
        ORDER BY mc.fecha, mc.id
    ''', (fecha_operativa,))
    cotizaciones = {}
    for pago in cursor.fetchall():
        cot_id = pago['cotizacion_id']
        if cot_id not in cotizaciones:
            cotizaciones[cot_id] = {
                'id': cot_id,
                'numero': pago['numero_cotizacion'] or str(cot_id),
                'cliente': pago['cliente_nombre'],
                'celular': pago['cliente_celular'] or '',
                'total': pago['total_cotizacion'] or 0,
                'estado': pago['estado'],
                'creador': pago['creador'] or '',
                'pagos_dia': [],
                'total_pagado_dia': 0,
                'productos': [],
            }
        fecha_pago = str(pago['fecha_pago'] or '')
        cotizaciones[cot_id]['pagos_dia'].append({
            'fecha': fecha_pago[11:16],
            'medio': pago['tipo_pago'] or 'No especificado',
            'monto': pago['ingreso_total'] or 0,
        })
        cotizaciones[cot_id]['total_pagado_dia'] += pago['ingreso_total'] or 0

    for cot_id, cotizacion in cotizaciones.items():
        cursor.execute('''
            SELECT COALESCE(i.nombre, cd.descripcion, 'Producto eliminado') AS nombre,
                   cd.cantidad, cd.precio_unitario_cotizado,
                   cd.cantidad * cd.precio_unitario_cotizado AS subtotal
            FROM cotizacion_detalles cd
            LEFT JOIN inventario i ON i.id = cd.producto_id
            WHERE cd.cotizacion_id = ?
            ORDER BY cd.id
        ''', (cot_id,))
        cotizacion['productos'] = [dict(row) for row in cursor.fetchall()]
    return list(cotizaciones.values())

@app.route('/cierre_caja', methods=['GET', 'POST'])
@role_required('caja')
def cierre_caja():
    hoy = datetime.date.today()
    conn = crear_conexion()
    ultimo_cierre = conn.execute(
        "SELECT MAX(fecha_operativa) FROM cierres_caja"
    ).fetchone()[0]
    if ultimo_cierre:
        # Avanza al siguiente dÃ­a con ingresos registrados. No obliga a cerrar
        # dÃ­as vacÃ­os, lo que podÃ­a dejar la caja mostrando una fecha antigua
        # aunque ya existieran ventas cobradas hoy.
        proxima_fecha_con_ventas = conn.execute(
            """SELECT MIN(date(mc.fecha))
               FROM movimientos_caja mc
               WHERE date(mc.fecha) > ? AND date(mc.fecha) <= ?
                 AND NOT EXISTS (
                     SELECT 1 FROM cierres_caja cc
                     WHERE cc.fecha_operativa = date(mc.fecha)
                 )""",
            (ultimo_cierre, hoy.isoformat()),
        ).fetchone()[0]
        fecha_operativa = (
            datetime.date.fromisoformat(proxima_fecha_con_ventas)
            if proxima_fecha_con_ventas else hoy
        )
    else:
        fecha_operativa = hoy
    cierre_ya_registrado = conn.execute(
        "SELECT 1 FROM cierres_caja WHERE fecha_operativa=?", (fecha_operativa.isoformat(),)
    ).fetchone() is not None
    conn.close()

    fecha_objetivo = fecha_operativa.isoformat()
    hoy_ini = f'{fecha_objetivo} 00:00:00'
    hoy_fin = f'{fecha_objetivo} 23:59:59'

    if request.method == 'POST':
        if cierre_ya_registrado:
            flash('Esta fecha ya tiene un cierre. No se registrÃ³ otro.', 'warning')
            return redirect(url_for('cierre_caja'))
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
                return redirect(url_for('cierre_caja'))
            else:
                flash(res['message'], 'danger')
        except Exception as e:
            flash(f'Error: {e}', 'danger')

    datos = obtener_ventas_aprobadas_para_cierre(hoy_ini, hoy_fin)
    ganancia = datos['total_ventas'] - datos['costo_total_cierre']
    conn = crear_conexion()
    cierres_recientes = conn.execute("""
        SELECT c.id, c.fecha, c.fecha_operativa, c.total_ventas, c.diferencia, u.nombre
        FROM cierres_caja c JOIN usuarios u ON u.id=c.usuario_id
        ORDER BY c.fecha_operativa DESC, c.fecha DESC
    """).fetchall()
    cierres_recientes = [dict(cierre) for cierre in cierres_recientes]
    for cierre in cierres_recientes:
        fecha_op = cierre.get('fecha_operativa') or str(cierre.get('fecha') or '')[:10]
        cierre['fecha_operativa'] = fecha_op
        try:
            cierre['fecha'] = datetime.datetime.strptime(fecha_op, '%Y-%m-%d').strftime('%d/%m/%Y')
        except Exception:
            cierre['fecha'] = fecha_op
        cierre['cotizaciones_dia'] = obtener_cotizaciones_del_dia(conn, fecha_op)
    conn.close()

    return render_template('cierre_caja/cierre.html',
                           total_ventas=datos['total_ventas'],
                           desglose_ventas=datos['desglose_pagos'],
                           total_cogs_dia=datos['costo_total_cierre'],
                           ganancia_bruta_dia=ganancia,
                           movimientos_db=datos['movimientos'],
                           cierres_recientes=cierres_recientes,
                           fecha_hoy=fecha_operativa.strftime('%d/%m/%Y'),
                           cierre_pendiente=fecha_operativa < hoy,
                           cierre_ya_registrado=cierre_ya_registrado)

@app.route('/cierre_caja/historial')
@role_required('caja')
def historial_cierre_caja():
    return redirect(url_for('cierre_caja'))

@app.route('/cierre_caja/editar/<int:id>', methods=['GET', 'POST'])
@role_required('caja')
def editar_cierre_caja(id):
    conn = crear_conexion()
    conn.row_factory = sqlite3.Row
    if request.method == 'POST':
        try:
            desglose = {
                k.replace('desglose_', '').capitalize(): float(request.form[k]) 
                for k in request.form 
                if k.startswith('desglose_')
            }

            conn.execute("""
                UPDATE cierres_caja SET 
                    fecha=?, total_ventas=?, efectivo_en_caja=?, diferencia=?, 
                    observaciones=?, desglose_pagos=?, diferencia_total=?, 
                    monto_apertura=?, ingresos_extra=?, egresos=?, 
                    efectivo_teorico=?, otros_medios_teoricos=? 
                WHERE id=?
            """, (
                request.form['fecha'], 
                float(request.form['total_ventas']), 
                float(request.form['efectivo_en_caja']),
                float(request.form['diferencia_hidden']), 
                request.form['observaciones'], 
                json.dumps(desglose),
                float(request.form['diferencia_total_hidden']), 
                float(request.form['monto_apertura']),
                float(request.form['ingresos_extra']), 
                float(request.form['egresos']),
                float(request.form['efectivo_teorico']), 
                float(request.form['otros_medios_teoricos']), 
                id
            ))
            conn.commit()
            flash('Cierre actualizado', 'success')
            conn.close()
            return redirect(url_for('cierre_caja'))
        except Exception as e:
            flash(f'Error: {e}', 'danger')
            conn.close()
            return redirect(url_for('editar_cierre_caja', id=id))

    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cierres_caja WHERE id=?", (id,))
    row = cursor.fetchone()
    conn.close()
    if not row: 
        return redirect(url_for('cierre_caja'))

    cierre = dict(row)
    try:
        cierre['desglose_pagos'] = json.loads(cierre['desglose_pagos'])
    except Exception:
        cierre['desglose_pagos'] = {}

    ap, ef, ing, eg = (
        cierre.get('monto_apertura') or 0, 
        cierre.get('efectivo_teorico') or 0, 
        cierre.get('ingresos_extra') or 0, 
        cierre.get('egresos') or 0
    )
    cierre['efectivo_teorico_final'] = ap + ef + ing - eg
    cierre['cierre_total_dia'] = (
        (cierre.get('efectivo_en_caja') or 0) + 
        (cierre.get('otros_medios_teoricos') or 0)
    )

    return render_template('cierre_caja/editar.html', cierre=cierre)

@app.route('/eliminar_cierre_caja/<int:cierre_id>', methods=['POST'])
@role_required('caja')
def eliminar_cierre_caja(cierre_id):
    try:
        conn = crear_conexion()
        conn.execute("DELETE FROM cierres_caja WHERE id=?", (cierre_id,))
        conn.commit()
        conn.close()
        flash('Cierre eliminado correctamente', 'success')
    except Exception as e:
        flash('Error al eliminar: ' + str(e), 'danger')
    return redirect(url_for('cierre_caja'))

@app.route('/cierre_caja/imprimir/<int:cierre_id>')
@role_required('caja')
def imprimir_cierre_caja(cierre_id):
    conn = crear_conexion()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.*, u.nombre 
        FROM cierres_caja c 
        JOIN usuarios u ON c.usuario_id = u.id 
        WHERE c.id = ?
    """, (cierre_id,))
    row = cursor.fetchone()
    conn.close()
    if not row: 
        flash('Cierre no encontrado', 'danger')
        return redirect(url_for('cierre_caja'))

    cierre = dict(row)
    try:
        cierre['desglose_pagos'] = json.loads(cierre['desglose_pagos'])
    except Exception:
        cierre['desglose_pagos'] = {}

    ap, ef, ing, eg = (
        cierre.get('monto_apertura') or 0, 
        cierre.get('efectivo_teorico') or 0, 
        cierre.get('ingresos_extra') or 0, 
        cierre.get('egresos') or 0
    )
    cierre['efectivo_teorico_final'] = ap + ef + ing - eg

    html = render_template('cierre_caja/informe_pdf.html', cierre=cierre)
    pdf = io.BytesIO()
    from xhtml2pdf import pisa
    pisa.CreatePDF(html, dest=pdf, encoding='UTF-8')
    pdf.seek(0)
    return send_file(
        pdf, 
        as_attachment=True, 
        download_name=f"Cierre_{cierre_id}.pdf", 
        mimetype='application/pdf'
    )

