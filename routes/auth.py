"""Rutas de autenticación, registro y sesiones."""

from app import *  # noqa: F401,F403
from flask import abort

asegurar_columna_dni_usuarios()
asegurar_columnas_administracion_usuarios()


class User(flask_login.UserMixin):
    def __init__(self, user_id, identificador, nombre, rol, debe_cambiar_password=False):
        self.id = user_id
        self.dni = identificador if identificador and identificador.isdigit() else ""
        self.email = identificador if identificador and "@" in identificador else ""
        self.nombre = nombre
        self.rol = rol
        self.debe_cambiar_password = bool(debe_cambiar_password)


@login_manager.user_loader
def load_user(user_id):
    conn = crear_conexion()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, COALESCE(dni, email), nombre, rol, activo, debe_cambiar_password, session_version "
        "FROM usuarios WHERE id = ?",
        (user_id,),
    )
    user_data = cursor.fetchone()
    conn.close()
    if (
        not user_data
        or not user_data[4]
        or session.get('auth_version') != user_data[6]
    ):
        return None
    return User(user_data[0], user_data[1], user_data[2], user_data[3], user_data[5])


def admin_required(view):
    """Limita la vista a cuentas activas con rol de administrador."""
    from functools import wraps

    @wraps(view)
    @flask_login.login_required
    def wrapped(*args, **kwargs):
        if getattr(flask_login.current_user, 'rol', None) != 'admin':
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def role_required(*roles):
    """Permite al administrador todo y limita cada trabajador a su área."""
    from functools import wraps

    def decorator(view):
        @wraps(view)
        @flask_login.login_required
        def wrapped(*args, **kwargs):
            if getattr(flask_login.current_user, 'rol', None) not in {'admin', *roles}:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def destino_inicio():
    """Envía a cada cuenta a su pantalla inicial según el rol asignado."""
    rol = getattr(flask_login.current_user, 'rol', None)
    destinos = {
        'admin': 'menu_inicio',
        'inventario': 'listar_inventario',
        'ventas': 'listar_cotizaciones',
        'caja': 'cierre_caja',
    }
    return redirect(url_for(destinos.get(rol, 'menu_inicio')))


@app.before_request
def requerir_cambio_de_password():
    if (
        flask_login.current_user.is_authenticated
        and flask_login.current_user.debe_cambiar_password
        and request.endpoint not in {'cambiar_password', 'logout', 'static'}
    ):
        return redirect(url_for('cambiar_password'))


@app.route("/")
def raiz():
    if flask_login.current_user.is_authenticated:
        return destino_inicio()
    return render_template("landing.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if flask_login.current_user.is_authenticated:
        return destino_inicio()

    if request.method == "POST":
        identificador = request.form.get("identificador", "").strip()
        password = request.form.get("password", "")

        conn = crear_conexion()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, password, nombre, rol, activo, debe_cambiar_password, session_version "
            "FROM usuarios WHERE dni = ? OR email = ?",
            (identificador, identificador),
        )
        user_data = cursor.fetchone()
        conn.close()

        if user_data and user_data[4] and check_password_hash(user_data[1], password):
            flask_login.login_user(
                User(user_data[0], identificador, user_data[2], user_data[3], user_data[5])
            )
            session['auth_version'] = user_data[6]
            if user_data[5]:
                return redirect(url_for('cambiar_password'))
            flash("Bienvenido", "success")
            return destino_inicio()
        flash("Credenciales incorrectas", "danger")

    return render_template("login.html")


@app.route("/logout")
@flask_login.login_required
def logout():
    flask_login.logout_user()
    return redirect(url_for("login"))


@app.route("/registro", methods=["GET", "POST"])
def registro():
    if flask_login.current_user.is_authenticated:
        return destino_inicio()
    flash('Las cuentas las crea el administrador y asigna el área de trabajo.', 'info')
    return redirect(url_for('login'))


@app.route('/cambiar-password', methods=['GET', 'POST'])
@flask_login.login_required
def cambiar_password():
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirmar = request.form.get('confirmar_password', '')
        if len(password) < 8:
            flash('La contraseña debe tener al menos 8 caracteres.', 'danger')
        elif password != confirmar:
            flash('Las contraseñas no coinciden.', 'danger')
        else:
            conn = crear_conexion()
            conn.execute(
                'UPDATE usuarios SET password=?, debe_cambiar_password=0, '
                'session_version=session_version+1 WHERE id=?',
                (generate_password_hash(password), flask_login.current_user.id),
            )
            conn.commit()
            conn.close()
            session['auth_version'] = int(session.get('auth_version', 0)) + 1
            flash('Contraseña actualizada.', 'success')
            return redirect(url_for('menu_inicio'))
    return render_template('cambiar_password.html')
