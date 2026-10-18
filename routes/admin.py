"""Administración de cuentas y accesos."""

import secrets
import re

from app import *  # noqa: F401,F403
from routes.auth import admin_required

ROLES = {'admin', 'inventario', 'ventas', 'caja', 'trabajador'}


@app.route('/admin/usuarios')
@admin_required
def administrar_usuarios():
    conn = crear_conexion()
    usuarios = conn.execute(
        """
        SELECT id, nombre, dni, email, rol, activo, debe_cambiar_password, fecha_registro
        FROM usuarios
        ORDER BY nombre COLLATE NOCASE
        """
    ).fetchall()
    conn.close()
    return render_template('admin/usuarios.html', usuarios=usuarios)


@app.route('/admin/razones-sociales')
@admin_required
def administrar_razones_sociales():
    conn = crear_conexion()
    razones = conn.execute(
        'SELECT id, nombre, ruc, telefono, medios_pago, activa '
        'FROM razones_sociales ORDER BY nombre COLLATE NOCASE'
    ).fetchall()
    conn.close()
    return render_template('admin/razones_sociales.html', razones=razones)


@app.route('/admin/razones-sociales/crear', methods=['POST'])
@admin_required
def crear_razon_social():
    nombre = request.form.get('nombre', '').strip()
    ruc = request.form.get('ruc', '').strip()
    telefono = request.form.get('telefono', '').strip()
    medios_pago = request.form.get('medios_pago', '').strip()
    if not nombre:
        flash('Escribe el nombre legal de la razón social.', 'danger')
        return redirect(url_for('administrar_razones_sociales'))
    if ruc and not re.fullmatch(r'\d{11}', ruc):
        flash('El RUC debe contener 11 dígitos o quedar vacío.', 'danger')
        return redirect(url_for('administrar_razones_sociales'))

    conn = crear_conexion()
    try:
        conn.execute(
            'INSERT INTO razones_sociales (nombre, ruc, telefono, medios_pago) VALUES (?, ?, ?, ?)',
            (nombre, ruc, telefono, medios_pago),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        flash('Ya existe una razón social con ese nombre.', 'danger')
    else:
        flash('Razón social agregada.', 'success')
    finally:
        conn.close()
    return redirect(url_for('administrar_razones_sociales'))


@app.route('/admin/razones-sociales/<int:razon_id>/actualizar', methods=['POST'])
@admin_required
def actualizar_razon_social(razon_id):
    nombre = request.form.get('nombre', '').strip()
    ruc = request.form.get('ruc', '').strip()
    telefono = request.form.get('telefono', '').strip()
    medios_pago = request.form.get('medios_pago', '').strip()
    activa = request.form.get('activa') == '1'
    if not nombre or (ruc and not re.fullmatch(r'\d{11}', ruc)):
        flash('Revisa el nombre y el RUC de 11 dígitos.', 'danger')
        return redirect(url_for('administrar_razones_sociales'))

    conn = crear_conexion()
    try:
        conn.execute(
            'UPDATE razones_sociales SET nombre=?, ruc=?, telefono=?, medios_pago=?, activa=? WHERE id=?',
            (nombre, ruc, telefono, medios_pago, int(activa), razon_id),
        )
        if conn.total_changes == 0:
            flash('No se encontró esa razón social.', 'warning')
        else:
            flash('Razón social actualizada. Las cotizaciones anteriores conservan sus datos emitidos.', 'success')
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        flash('Ya existe otra razón social con ese nombre.', 'danger')
    finally:
        conn.close()
    return redirect(url_for('administrar_razones_sociales'))


@app.route('/admin/usuarios/<int:usuario_id>/rol', methods=['POST'])
@admin_required
def cambiar_rol_usuario(usuario_id):
    rol = request.form.get('rol', '')
    if rol not in ROLES:
        flash('El rol seleccionado no es válido.', 'danger')
        return redirect(url_for('administrar_usuarios'))

    conn = crear_conexion()
    usuario = conn.execute(
        'SELECT id, rol, activo FROM usuarios WHERE id=?', (usuario_id,)
    ).fetchone()
    if not usuario:
        conn.close()
        flash('No se encontró esa cuenta.', 'danger')
        return redirect(url_for('administrar_usuarios'))

    if usuario_id == int(flask_login.current_user.id) and rol != 'admin':
        conn.close()
        flash('No puedes quitarte tu propio rol de administrador.', 'warning')
        return redirect(url_for('administrar_usuarios'))

    if usuario['rol'] == 'admin' and usuario['activo'] and rol != 'admin':
        activos = conn.execute(
            "SELECT COUNT(*) FROM usuarios WHERE rol='admin' AND activo=1"
        ).fetchone()[0]
        if activos <= 1:
            conn.close()
            flash('Debe quedar al menos un administrador activo.', 'warning')
            return redirect(url_for('administrar_usuarios'))

    conn.execute('UPDATE usuarios SET rol=? WHERE id=?', (rol, usuario_id))
    conn.commit()
    conn.close()
    flash('Rol actualizado.', 'success')
    return redirect(url_for('administrar_usuarios'))


@app.route('/admin/usuarios/crear', methods=['POST'])
@admin_required
def crear_usuario_trabajador():
    nombre = request.form.get('nombre', '').strip()
    dni = request.form.get('dni', '').strip()
    rol = request.form.get('rol', 'trabajador')
    if not nombre or not re.fullmatch(r'\d{8}', dni):
        flash('Ingresa el nombre y un DNI válido de 8 dígitos.', 'danger')
        return redirect(url_for('administrar_usuarios'))
    if rol not in ROLES:
        flash('El rol seleccionado no es válido.', 'danger')
        return redirect(url_for('administrar_usuarios'))

    password_temporal = secrets.token_urlsafe(12)
    conn = crear_conexion()
    try:
        email_interno = f'dni-{dni}@users.invalid'
        conn.execute(
            """INSERT INTO usuarios
               (nombre, dni, email, password, rol, activo, debe_cambiar_password)
               VALUES (?, ?, ?, ?, ?, 1, 1)""",
            (nombre, dni, email_interno, generate_password_hash(password_temporal), rol),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        flash('Ya existe una cuenta con ese DNI.', 'danger')
        return redirect(url_for('administrar_usuarios'))
    finally:
        conn.close()

    flash(
        f'Cuenta creada para {nombre}. Contraseña temporal: {password_temporal}. '
        'Entrégala en privado; deberá cambiarla al ingresar.',
        'warning',
    )
    return redirect(url_for('administrar_usuarios'))


@app.route('/admin/usuarios/<int:usuario_id>/estado', methods=['POST'])
@admin_required
def cambiar_estado_usuario(usuario_id):
    activo = request.form.get('activo') == '1'
    conn = crear_conexion()
    usuario = conn.execute(
        'SELECT id, rol, activo FROM usuarios WHERE id=?', (usuario_id,)
    ).fetchone()
    if not usuario:
        conn.close()
        flash('No se encontró esa cuenta.', 'danger')
        return redirect(url_for('administrar_usuarios'))

    if usuario_id == int(flask_login.current_user.id) and not activo:
        conn.close()
        flash('No puedes desactivar tu propia cuenta.', 'warning')
        return redirect(url_for('administrar_usuarios'))

    if usuario['rol'] == 'admin' and usuario['activo'] and not activo:
        activos = conn.execute(
            "SELECT COUNT(*) FROM usuarios WHERE rol='admin' AND activo=1"
        ).fetchone()[0]
        if activos <= 1:
            conn.close()
            flash('Debe quedar al menos un administrador activo.', 'warning')
            return redirect(url_for('administrar_usuarios'))

    conn.execute('UPDATE usuarios SET activo=? WHERE id=?', (int(activo), usuario_id))
    conn.commit()
    conn.close()
    flash('Cuenta activada.' if activo else 'Cuenta desactivada.', 'success')
    return redirect(url_for('administrar_usuarios'))


@app.route('/admin/usuarios/<int:usuario_id>/eliminar', methods=['POST'])
@admin_required
def eliminar_usuario(usuario_id):
    if usuario_id == int(flask_login.current_user.id):
        flash('No puedes eliminar tu propia cuenta.', 'warning')
        return redirect(url_for('administrar_usuarios'))

    conn = crear_conexion()
    usuario = conn.execute(
        'SELECT id, nombre, rol, activo FROM usuarios WHERE id=?', (usuario_id,)
    ).fetchone()
    if not usuario:
        conn.close()
        flash('No se encontró esa cuenta.', 'danger')
        return redirect(url_for('administrar_usuarios'))

    if usuario['rol'] == 'admin' and usuario['activo']:
        administradores_activos = conn.execute(
            "SELECT COUNT(*) FROM usuarios WHERE rol='admin' AND activo=1"
        ).fetchone()[0]
        if administradores_activos <= 1:
            conn.close()
            flash('No puedes eliminar al último administrador activo.', 'warning')
            return redirect(url_for('administrar_usuarios'))

    cotizaciones = conn.execute(
        'SELECT COUNT(*) FROM cotizaciones WHERE usuario_id=?', (usuario_id,)
    ).fetchone()[0]
    cierres = conn.execute(
        'SELECT COUNT(*) FROM cierres_caja WHERE usuario_id=?', (usuario_id,)
    ).fetchone()[0]
    if cotizaciones or cierres:
        conn.close()
        flash(
            f"No se puede eliminar a {usuario['nombre']}: tiene "
            f'{cotizaciones} cotización(es) y {cierres} cierre(s) asociados. '
            'Desactiva la cuenta para conservar el historial.',
            'warning',
        )
        return redirect(url_for('administrar_usuarios'))

    try:
        conn.execute('DELETE FROM usuarios WHERE id=?', (usuario_id,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        flash('La cuenta tiene registros vinculados y no se puede eliminar.', 'warning')
    else:
        flash(f"Se eliminó la cuenta de {usuario['nombre']}.", 'success')
    finally:
        conn.close()
    return redirect(url_for('administrar_usuarios'))


@app.route('/admin/usuarios/<int:usuario_id>/restablecer-password', methods=['POST'])
@admin_required
def restablecer_password_usuario(usuario_id):
    conn = crear_conexion()
    usuario = conn.execute(
        'SELECT id, nombre FROM usuarios WHERE id=?', (usuario_id,)
    ).fetchone()
    if not usuario:
        conn.close()
        flash('No se encontró esa cuenta.', 'danger')
        return redirect(url_for('administrar_usuarios'))

    password_temporal = secrets.token_urlsafe(12)
    conn.execute(
        'UPDATE usuarios SET password=?, debe_cambiar_password=1, '
        'session_version=session_version+1 WHERE id=?',
        (generate_password_hash(password_temporal), usuario_id),
    )
    conn.commit()
    conn.close()
    flash(
        f"Contraseña temporal para {usuario['nombre']}: {password_temporal}. "
        'Cópiala ahora; dejará de mostrarse al salir de esta página.',
        'warning',
    )
    return redirect(url_for('administrar_usuarios'))
