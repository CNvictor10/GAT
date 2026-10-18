"""Rutas de inventory."""

# Registramos estas vistas en la instancia Flask existente para conservar las URL.
from app import *  # noqa: F401,F403
from routes.auth import role_required
from werkzeug.utils import secure_filename
import os
import uuid


def guardar_imagen_producto(archivo):
    """Guarda únicamente imágenes raster permitidas y devuelve su ruta estática."""
    if not archivo or not archivo.filename:
        return ''
    extension = os.path.splitext(secure_filename(archivo.filename))[1].lower()
    firmas = {
        '.jpg': lambda data: data.startswith(b'\xff\xd8\xff'),
        '.jpeg': lambda data: data.startswith(b'\xff\xd8\xff'),
        '.png': lambda data: data.startswith(b'\x89PNG\r\n\x1a\n'),
        '.webp': lambda data: len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP',
    }
    archivo.stream.seek(0)
    firma = archivo.stream.read(16)
    archivo.stream.seek(0)
    if extension not in firmas or not firmas[extension](firma):
        raise ValueError('La imagen debe ser JPG, PNG o WEBP válida.')
    directorio = os.path.join(app.root_path, 'static', 'uploads', 'products')
    os.makedirs(directorio, exist_ok=True)
    nombre = f"{uuid.uuid4().hex}{extension}"
    archivo.save(os.path.join(directorio, nombre))
    return f"uploads/products/{nombre}"


def eliminar_imagen_producto(ruta):
    if not ruta or not ruta.startswith('uploads/products/'):
        return
    directorio = os.path.realpath(os.path.join(app.root_path, 'static', 'uploads', 'products'))
    archivo = os.path.realpath(os.path.join(app.root_path, 'static', ruta))
    if os.path.commonpath([directorio, archivo]) == directorio and os.path.isfile(archivo):
        os.remove(archivo)


@app.route('/inventario/importar-excel', methods=['POST'])
@role_required('inventario')
def importar_inventario_excel():
    archivo = request.files.get('archivo_excel')
    nombre_archivo = (archivo.filename or '').strip() if archivo else ''
    if not archivo or not nombre_archivo:
        flash('Selecciona un archivo Excel .xlsx.', 'warning')
        return redirect(url_for('listar_inventario'))
    if not nombre_archivo.lower().endswith('.xlsx'):
        flash('El archivo debe tener formato .xlsx.', 'danger')
        return redirect(url_for('listar_inventario'))

    resultado = sincronizar_inventario_desde_excel(archivo)
    flash(
        resultado.get('message', 'No se pudo importar el Excel.'),
        'success' if resultado.get('success') else 'danger',
    )
    return redirect(url_for('listar_inventario'))

@app.route('/inventario')
@role_required('inventario')
def listar_inventario():
    search = request.args.get('search_query', '').strip()
    
    if search:
        productos = buscar_productos_bd(search)
    else:
        productos = obtener_inventario_desde_bd()
    
    bajos = get_productos_bajo_stock_bd()
    
    return render_template('inventario/listar.html', 
                         inventario=productos, 
                         alertas_stock=len(bajos),
                         productos_bajo_stock=bajos, 
                         search_query=search)

@app.route('/inventario/agregar', methods=['GET', 'POST'])
@role_required('inventario')
def agregar_inventario():
    if request.method == 'POST':
        try:
            imagen = guardar_imagen_producto(request.files.get('imagen'))
            conn = crear_conexion()
            cursor = conn.cursor()
            
            cursor.execute("SELECT MAX(id) FROM inventario")
            max_id = cursor.fetchone()[0] or 0
            nuevo_id = max_id + 1
            
            nombre_es = request.form['nombre']
            nombre_en = request.form.get('nombre_en', '')
            nombre_zh = request.form.get('nombre_zh', '')
            
            cursor.execute("""
                INSERT INTO inventario (
                    id, nombre, nombre_en, nombre_zh, descripcion, 
                    cantidad, precio_unitario, precio_unidad, umbral_stock, costo_adquisicion, unidades_por_caja, imagen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                nuevo_id,
                nombre_es,
                nombre_en,
                nombre_zh,
                request.form['descripcion'],
                int(request.form['cantidad']),
                float(request.form['precio_unitario']),
                float(request.form.get('precio_unidad_nuevo', 0)),
                int(request.form['umbral_stock']),
                0,
                int(request.form.get('unidades_por_caja', 0)),
                imagen
            ))
            
            conn.commit()
            conn.close()
            flash('Producto agregado correctamente', 'success')
            return redirect(url_for('listar_inventario'))
            
        except Exception as e:
            flash(f'Error: {e}', 'danger')
    
    return render_template('inventario/agregar.html')

@app.route('/inventario/editar/<int:id>', methods=['GET', 'POST'])
@role_required('inventario')
def editar_inventario(id):
    producto = obtener_producto_por_id_bd(id)
    
    if not producto:
        flash('Producto no encontrado', 'danger')
        return redirect(url_for('listar_inventario'))
    
    if request.method == 'POST':
        try:
            imagen_actual = producto.get('imagen', '')
            archivo_imagen = request.files.get('imagen')
            nueva_imagen = guardar_imagen_producto(archivo_imagen) if archivo_imagen and archivo_imagen.filename else imagen_actual
            if request.form.get('quitar_imagen') == '1':
                nueva_imagen = ''
            conn = crear_conexion()
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE inventario SET 
                    nombre = ?,
                    descripcion = ?,
                    cantidad = ?,
                    precio_unitario = ?,
                    precio_unidad = ?,
                    umbral_stock = ?,
                    costo_adquisicion = ?,
                    unidades_por_caja = ?,
                    imagen = ?,
                    fecha_actualizacion = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                request.form['nombre'],
                request.form['descripcion'],
                int(request.form['cantidad']),
                float(request.form['precio_unitario']),
                float(request.form.get('precio_unidad_nuevo', 0)),
                int(request.form['umbral_stock']),
                # El costo es interno y este formulario no lo modifica.
                float(producto.get('costo_adquisicion', 0)),
                int(request.form.get('unidades_por_caja', 0)),
                nueva_imagen,
                id
            ))
            
            conn.commit()
            conn.close()
            if nueva_imagen != imagen_actual:
                eliminar_imagen_producto(imagen_actual)
            flash('Producto actualizado correctamente', 'success')
            return redirect(url_for('listar_inventario'))
            
        except Exception as e:
            flash(f'Error: {e}', 'danger')
    
    return render_template('inventario/editar.html', producto=producto)

@app.route('/inventario/eliminar/<int:id>', methods=['POST'])
@role_required('inventario')
def eliminar_inventario(id):
    try:
        producto = obtener_producto_por_id_bd(id)
        conn = crear_conexion()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM inventario WHERE id = ?", (id,))
        conn.commit()
        conn.close()
        if producto:
            eliminar_imagen_producto(producto.get('imagen', ''))
        flash('Producto eliminado correctamente', 'success')
    except Exception as e:
        flash(f'Error al eliminar: {e}', 'danger')
    
    return redirect(url_for('listar_inventario'))

@app.route('/inventario/exportar_pdf')
@role_required('inventario')
def exportar_inventario_pdf():
    productos = obtener_inventario_desde_bd()
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [Paragraph("<b>Reporte Inventario</b>", styles['Heading1']), Spacer(1, 12)]
    
    t_data = [['ID', 'Nombre', 'Desc', 'Cant', 'Precio', 'Min']]
    for p in productos:
        t_data.append([str(p['id']), p['nombre'], p['descripcion'][:50] if p['descripcion'] else '', 
                      str(p['cantidad']), f"{p['precio_unitario']:.2f}", str(p['umbral_stock'])])
    
    table = Table(t_data)
    table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 1, colors.black)]))
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    
    return make_response(buffer.getvalue(), 200, {
        'Content-Type': 'application/pdf', 
        'Content-Disposition': 'attachment; filename=inventario.pdf'
    })

# =============================================================================
# RUTAS: COTIZACIONES (COMPLETAS)
# =============================================================================
