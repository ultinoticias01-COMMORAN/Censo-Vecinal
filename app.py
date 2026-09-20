import sqlite3
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import io
import json
import hashlib

# -----------------------------------------------------------------------------
# 1. CONFIGURACIÓN DE PÁGINA Y CONSTANTES
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Censo Comunitario Avanzado", page_icon="🏡", layout="wide")

DB_FILE = "censo.db"

CAMPOS_BASE_DEFAULT = {
    "cedula": ("Cédula de Identidad", "texto", "[]"),
    "nombres": ("Nombres", "texto", "[]"),
    "apellidos": ("Apellidos", "texto", "[]"),
    "sexo": ("Sexo / Género", "desplegable", json.dumps(["Femenino", "Masculino", "Otro"])),
    "fecha_nac": ("Fecha de Nacimiento", "texto", "[]"),
    "telefono": ("Teléfono de Contacto", "texto", "[]"),
    "manzana": ("Manzana / Sector", "texto", "[]"),
    "fecha_llegada": ("Fecha de Llegada a la Comunidad", "texto", "[]"),
    "direccion": ("Dirección Detallada de Habitación", "texto", "[]"),
    "condicion_salud": ("Condición / Afectación de Salud", "desplegable", json.dumps(["Ninguna", "Enfermedad Crónica", "Discapacidad", "Adulto Mayor Encamado", "Embarazada", "Población de Riesgo", "Otra"])),
    "detalle_salud": ("Detalles adicionales de salud", "texto", "[]")
}

LISTA_PERMISOS = [
    "ver_censo",
    "registrar_habitantes",
    "editar_habitantes",
    "eliminar_habitantes",
    "ver_estadisticas",
    "gestion_bitacora",
    "personalizar_etiquetas",
    "respaldos_importacion"
]

# -----------------------------------------------------------------------------
# 2. FUNCIONES DE BASE DE DATOS Y MIGRACIONES
# -----------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def get_connection():
    return sqlite3.connect(DB_FILE)

def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS habitantes (
                cedula TEXT PRIMARY KEY,
                nombres TEXT,
                apellidos TEXT,
                sexo TEXT,
                fecha_nac TEXT,
                fecha_llegada TEXT,
                direccion TEXT,
                manzana TEXT,
                telefono TEXT,
                condicion_salud TEXT DEFAULT 'Ninguna',
                detalle_salud TEXT DEFAULT '',
                es_jefe_hogar INTEGER DEFAULT 0,
                jefe_hogar_cedula TEXT DEFAULT '',
                campos_adicionales TEXT DEFAULT '{}'
            )
        """)
        
        cursor.execute("PRAGMA table_info(habitantes)")
        cols_hab = [column[1] for column in cursor.fetchall()]
        if "es_jefe_hogar" not in cols_hab:
            cursor.execute("ALTER TABLE habitantes ADD COLUMN es_jefe_hogar INTEGER DEFAULT 0")
        if "jefe_hogar_cedula" not in cols_hab:
            cursor.execute("ALTER TABLE habitantes ADD COLUMN jefe_hogar_cedula TEXT DEFAULT ''")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                username TEXT PRIMARY KEY,
                password TEXT,
                nombre_completo TEXT,
                rol TEXT,
                permisos TEXT DEFAULT '{}'
            )
        """)
        
        cursor.execute("PRAGMA table_info(usuarios)")
        cols_usuarios = [column[1] for column in cursor.fetchall()]
        if "permisos" not in cols_usuarios:
            cursor.execute("ALTER TABLE usuarios ADD COLUMN permisos TEXT DEFAULT '{}'")
            perm_master = json.dumps({p: True for p in LISTA_PERMISOS})
            perm_admin = json.dumps({p: True for p in LISTA_PERMISOS if p != "personalizar_etiquetas"})
            perm_user = json.dumps({"ver_censo": True, "ver_estadisticas": True})
            cursor.execute("UPDATE usuarios SET permisos = ? WHERE username = 'master'", (perm_master,))
            cursor.execute("UPDATE usuarios SET permisos = ? WHERE username = 'admin'", (perm_admin,))
            cursor.execute("UPDATE usuarios SET permisos = ? WHERE username = 'user'", (perm_user,))

        cursor.execute("SELECT username, password FROM usuarios")
        usuarios_existentes = cursor.fetchall()
        
        if not usuarios_existentes:
            permisos_master = json.dumps({p: True for p in LISTA_PERMISOS})
            permisos_admin = json.dumps({p: True for p in LISTA_PERMISOS if p != "personalizar_etiquetas"})
            permisos_user = json.dumps({"ver_censo": True, "ver_estadisticas": True})
            
            cursor.execute("INSERT INTO usuarios VALUES (?, ?, ?, ?, ?)", ("master", hash_password("master123"), "Usuario Master", "Master", permisos_master))
            cursor.execute("INSERT INTO usuarios VALUES (?, ?, ?, ?, ?)", ("admin", hash_password("admin123"), "Administrador Principal", "Administrador", permisos_admin))
            cursor.execute("INSERT INTO usuarios VALUES (?, ?, ?, ?, ?)", ("user", hash_password("user123"), "Visualizador Invitado", "Visualizador", permisos_user))
        else:
            for user, pwd in usuarios_existentes:
                if len(pwd) != 64:
                    pwd_encriptada = hash_password(pwd)
                    cursor.execute("UPDATE usuarios SET password = ? WHERE username = ?", (pwd_encriptada, user))

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS configuracion_estilo_campos (
                clave_campo TEXT PRIMARY KEY,
                etiqueta TEXT,
                tipo_control TEXT,
                opciones_json TEXT
            )
        """)
        
        cursor.execute("PRAGMA table_info(configuracion_estilo_campos)")
        cols_estilo = [column[1] for column in cursor.fetchall()]
        if "opciones_json" not in cols_estilo:
            cursor.execute("ALTER TABLE configuracion_estilo_campos ADD COLUMN opciones_json TEXT DEFAULT '[]'")

        for clave, (etiqueta_def, tipo_def, opciones_def) in CAMPOS_BASE_DEFAULT.items():
            cursor.execute("""
                INSERT OR IGNORE INTO configuracion_estilo_campos (clave_campo, etiqueta, tipo_control, opciones_json)
                VALUES (?, ?, ?, ?)
            """, (clave, etiqueta_def, tipo_def, opciones_def))

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bitacora_documentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cedula TEXT,
                tipo_documento TEXT,
                descripcion TEXT,
                fecha_emision TEXT,
                emitido_por TEXT,
                FOREIGN KEY (cedula) REFERENCES habitantes (cedula)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS configuracion_campos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre_campo TEXT UNIQUE,
                tipo_campo TEXT,
                opciones_json TEXT DEFAULT '[]'
            )
        """)
        
        conn.commit()

init_db()

# -----------------------------------------------------------------------------
# 3. LÓGICA DE NEGOCIO Y OPERACIONES DE DATOS
# -----------------------------------------------------------------------------
def cargar_configuracion_campos():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT clave_campo, etiqueta, tipo_control, opciones_json FROM configuracion_estilo_campos")
        filas = cursor.fetchall()
    
    config = {}
    for f in filas:
        try:
            opciones = json.loads(f[3]) if f[3] else []
        except Exception:
            opciones = []
        config[f[0]] = {
            "etiqueta": f[1],
            "tipo_control": f[2],
            "opciones": opciones
        }
    return config

def guardar_configuracion_campo(clave, etiqueta, tipo_control, opciones_lista):
    with get_connection() as conn:
        cursor = conn.cursor()
        opciones_json = json.dumps([op.strip() for op in opciones_lista if op.strip()], ensure_ascii=False)
        cursor.execute("""
            INSERT OR REPLACE INTO configuracion_estilo_campos (clave_campo, etiqueta, tipo_control, opciones_json)
            VALUES (?, ?, ?, ?)
        """, (clave, etiqueta, tipo_control, opciones_json))
        conn.commit()

def formato_fecha_pantalla(fecha_str):
    try:
        f = parsear_fecha_bd(fecha_str)
        return f.strftime("%d/%m/%Y")
    except Exception:
        return str(fecha_str)

def parsear_fecha_bd(fecha_str):
    fecha_defecto = datetime(1990, 1, 1).date()
    if pd.isna(fecha_str) or not fecha_str or str(fecha_str).strip() in ["None", "nan", ""]:
        return fecha_defecto
    try:
        if isinstance(fecha_str, (datetime, pd.Timestamp)):
            return fecha_str.date()
        
        s = str(fecha_str).split()[0].strip()
        if "/" in s:
            f = datetime.strptime(s, "%d/%m/%Y").date()
        else:
            f = datetime.strptime(s, "%Y-%m-%d").date()
            
        if f.year < 1900:
            return datetime(1900, 1, 1).date()
        return f
    except Exception:
        return fecha_defecto

def calcular_edad(fecha_nac_str):
    try:
        f_nac = parsear_fecha_bd(fecha_nac_str)
        hoy = datetime.now().date()
        return hoy.year - f_nac.year - ((hoy.month, hoy.day) < (f_nac.month, f_nac.day))
    except Exception:
        return 0

def calcular_tiempo_comunidad(fecha_llegada_str):
    try:
        f_lleg = parsear_fecha_bd(fecha_llegada_str)
        hoy = datetime.now().date()
        anios = hoy.year - f_lleg.year - ((hoy.month, hoy.day) < (f_lleg.month, f_lleg.day))
        return max(0, anios)
    except Exception:
        return 0

def cargar_habitantes():
    with get_connection() as conn:
        df = pd.read_sql_query("SELECT * FROM habitantes", conn)
    
    df["sexo"] = df["sexo"].fillna("No especificado")
    df["condicion_salud"] = df["condicion_salud"].fillna("Ninguna")
    df["detalle_salud"] = df["detalle_salud"].fillna("")
    df["es_jefe_hogar"] = df["es_jefe_hogar"].fillna(0).astype(int)
    df["jefe_hogar_cedula"] = df["jefe_hogar_cedula"].fillna("").astype(str).str.strip()
    df["campos_adicionales"] = df["campos_adicionales"].fillna("{}")
    return df

def obtener_jefes_hogar():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT cedula, nombres, apellidos FROM habitantes WHERE es_jefe_hogar = 1 ORDER BY nombres ASC")
        return cursor.fetchall()

def guardar_habitante(datos):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO habitantes (
                cedula, nombres, apellidos, sexo, fecha_nac, fecha_llegada, 
                direccion, manzana, telefono, condicion_salud, detalle_salud,
                es_jefe_hogar, jefe_hogar_cedula, campos_adicionales
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, datos)
        conn.commit()

def actualizar_habitante_completo(cedula_original, datos_nuevos):
    with get_connection() as conn:
        cursor = conn.cursor()
        nueva_cedula = datos_nuevos[0]
        
        if cedula_original != nueva_cedula:
            cursor.execute("UPDATE bitacora_documentos SET cedula = ? WHERE cedula = ?", (nueva_cedula, cedula_original))
            cursor.execute("UPDATE habitantes SET jefe_hogar_cedula = ? WHERE jefe_hogar_cedula = ?", (nueva_cedula, cedula_original))
            cursor.execute("DELETE FROM habitantes WHERE cedula = ?", (cedula_original,))
        
        cursor.execute("""
            INSERT OR REPLACE INTO habitantes (
                cedula, nombres, apellidos, sexo, fecha_nac, fecha_llegada, 
                direccion, manzana, telefono, condicion_salud, detalle_salud,
                es_jefe_hogar, jefe_hogar_cedula, campos_adicionales
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, datos_nuevos)
        conn.commit()

def eliminar_habitante(cedula):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM habitantes WHERE cedula = ?", (cedula,))
        cursor.execute("DELETE FROM bitacora_documentos WHERE cedula = ?", (cedula,))
        cursor.execute("UPDATE habitantes SET jefe_hogar_cedula = '' WHERE jefe_hogar_cedula = ?", (cedula,))
        conn.commit()

def borrar_todo_el_censo():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM habitantes")
        cursor.execute("DELETE FROM bitacora_documentos")
        conn.commit()

def registrar_documento_bitacora(cedula, tipo_doc, descripcion, emitido_por):
    with get_connection() as conn:
        cursor = conn.cursor()
        fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO bitacora_documentos (cedula, tipo_documento, descripcion, fecha_emision, emitido_por)
            VALUES (?, ?, ?, ?, ?)
        """, (cedula, tipo_doc, descripcion, fecha_actual, emitido_por))
        conn.commit()

def obtener_bitacora_habitante(cedula):
    with get_connection() as conn:
        df = pd.read_sql_query(
            "SELECT id, tipo_documento, descripcion, fecha_emision, emitido_por FROM bitacora_documentos WHERE cedula = ? ORDER BY id DESC", 
            conn, 
            params=(cedula,)
        )
    return df

def cargar_campos_personalizados():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, nombre_campo, tipo_campo, opciones_json FROM configuracion_campos")
        filas = cursor.fetchall()
    
    resultado = []
    for f in filas:
        try:
            opciones = json.loads(f[3]) if f[3] else []
        except Exception:
            opciones = []
        resultado.append({
            "id": f[0],
            "nombre": f[1],
            "tipo": f[2],
            "opciones": opciones
        })
    return resultado

def agregar_campo_personalizado(nombre, tipo, opciones_lista):
    with get_connection() as conn:
        cursor = conn.cursor()
        opciones_json = json.dumps([op.strip() for op in opciones_lista if op.strip()], ensure_ascii=False)
        try:
            cursor.execute("INSERT INTO configuracion_campos (nombre_campo, tipo_campo, opciones_json) VALUES (?, ?, ?)", (nombre, tipo, opciones_json))
            conn.commit()
        except sqlite3.IntegrityError:
            pass

def actualizar_campo_personalizado(id_campo, nuevo_nombre, nuevo_tipo, opciones_lista):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT nombre_campo FROM configuracion_campos WHERE id = ?", (id_campo,))
        f = cursor.fetchone()
        if not f:
            return
        nombre_antiguo = f[0]
        
        opciones_json = json.dumps([op.strip() for op in opciones_lista if op.strip()], ensure_ascii=False)
        cursor.execute("UPDATE configuracion_campos SET nombre_campo = ?, tipo_campo = ?, opciones_json = ? WHERE id = ?", (nuevo_nombre, nuevo_tipo, opciones_json, id_campo))
        
        if nombre_antiguo != nuevo_nombre:
            cursor.execute("SELECT cedula, campos_adicionales FROM habitantes")
            habitantes = cursor.fetchall()
            for ced, raw_json in habitantes:
                try:
                    data_extra = json.loads(raw_json) if raw_json else {}
                    if nombre_antiguo in data_extra:
                        data_extra[nuevo_nombre] = data_extra.pop(nombre_antiguo)
                        cursor.execute("UPDATE habitantes SET campos_adicionales = ? WHERE cedula = ?", (json.dumps(data_extra, ensure_ascii=False), ced))
                except Exception:
                    pass
        conn.commit()

def eliminar_campo_personalizado(id_campo):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT nombre_campo FROM configuracion_campos WHERE id = ?", (id_campo,))
        f = cursor.fetchone()
        if f:
            nombre_campo = f[0]
            cursor.execute("SELECT cedula, campos_adicionales FROM habitantes")
            habitantes = cursor.fetchall()
            for ced, raw_json in habitantes:
                try:
                    data_extra = json.loads(raw_json) if raw_json else {}
                    if nombre_campo in data_extra:
                        del data_extra[nombre_campo]
                        cursor.execute("UPDATE habitantes SET campos_adicionales = ? WHERE cedula = ?", (json.dumps(data_extra, ensure_ascii=False), ced))
                except Exception:
                    pass
        cursor.execute("DELETE FROM configuracion_campos WHERE id = ?", (id_campo,))
        conn.commit()

def verificar_login(username, password):
    pass_hashed = hash_password(password)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT username, nombre_completo, rol, permisos FROM usuarios WHERE username = ? AND password = ?", (username, pass_hashed))
        user = cursor.fetchone()
    return user

def cargar_usuarios():
    with get_connection() as conn:
        df = pd.read_sql_query("SELECT username, nombre_completo, rol, permisos FROM usuarios", conn)
    return df

def guardar_usuario(username, password, nombre_completo, rol, dict_permisos):
    with get_connection() as conn:
        cursor = conn.cursor()
        json_permisos = json.dumps(dict_permisos)
        
        cursor.execute("SELECT password FROM usuarios WHERE username = ?", (username,))
        f = cursor.fetchone()
        
        if password.strip():
            pass_final = hash_password(password.strip())
        else:
            pass_final = f[0] if f else hash_password("123456")
        
        cursor.execute("INSERT OR REPLACE INTO usuarios VALUES (?, ?, ?, ?, ?)", (username, pass_final, nombre_completo, rol, json_permisos))
        conn.commit()

def eliminar_usuario(username):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM usuarios WHERE username = ?", (username,))
        conn.commit()

def tiene_permiso(clave_permiso):
    if st.session_state.rol_actual == "Master":
        return True
    permisos = st.session_state.get("permisos_usuario", {})
    return permisos.get(clave_permiso, False)

def renderizar_campo_dinamico(key_campo, cfg_dict, key_suffix=""):
    cfg = cfg_dict.get(key_campo, {"etiqueta": key_campo, "tipo_control": "texto", "opciones": []})
    etiqueta = cfg["etiqueta"]
    tipo = cfg["tipo_control"]
    opciones = cfg["opciones"]
    key_widget = f"{key_campo}_{key_suffix}"
    
    if key_widget not in st.session_state:
        st.session_state[key_widget] = opciones[0] if (tipo == "desplegable" and opciones) else ""

    if tipo == "desplegable" and opciones:
        return st.selectbox(f"{etiqueta}:", opciones, key=key_widget)
    else:
        return st.text_input(f"{etiqueta}:", key=key_widget)

# -----------------------------------------------------------------------------
# 4. CONTROL DE SESIÓN Y LOGIN
# -----------------------------------------------------------------------------
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
    st.session_state.usuario_actual = None
    st.session_state.rol_actual = None
    st.session_state.permisos_usuario = {}

if not st.session_state.autenticado:
    st.markdown("<h1 style='text-align: center;'>🔒 Control de Acceso - Censo Comunitario</h1>", unsafe_allow_html=True)
    
    _, col_center, _ = st.columns([1, 2, 1])
    with col_center:
        usuario = st.text_input("Usuario")
        clave = st.text_input("Contraseña", type="password")
        btn_login = st.button("Ingresar al Sistema", use_container_width=True, type="primary")
        
        if btn_login:
            user_data = verificar_login(usuario, clave)
            if user_data:
                st.session_state.autenticado = True
                st.session_state.username = user_data[0]
                st.session_state.usuario_actual = user_data[1]
                st.session_state.rol_actual = user_data[2]
                try:
                    st.session_state.permisos_usuario = json.loads(user_data[3])
                except Exception:
                    st.session_state.permisos_usuario = {}
                st.success(f"¡Bienvenido {user_data[1]}!")
                st.rerun()
            else:
                st.error("❌ Credenciales incorrectas.")
    st.stop()

# -----------------------------------------------------------------------------
# 5. CARGA DE CONFIGURACIÓN Y BARRA LATERAL
# -----------------------------------------------------------------------------
cfg_campos = cargar_configuracion_campos()

with st.sidebar:
    st.title("👤 Perfil de Usuario")
    st.write(f"**Usuario:** {st.session_state.usuario_actual}")
    st.write(f"**Rol:** `{st.session_state.rol_actual}`")
    
    if st.button("🚪 Cerrar Sesión", use_container_width=True):
        st.session_state.autenticado = False
        st.session_state.usuario_actual = None
        st.session_state.rol_actual = None
        st.session_state.permisos_usuario = {}
        st.rerun()
        
    st.markdown("---")
    st.caption("Sistema de Censo Comunitario v7.3")

# -----------------------------------------------------------------------------
# 6. NAVEGACIÓN Y PESTAÑAS DINÁMICAS
# -----------------------------------------------------------------------------
st.title("🏡 Censo Digital de la Comunidad")

pestañas = []
if tiene_permiso("ver_censo"):
    pestañas.append("📊 Consultar y Filtros")
if tiene_permiso("registrar_habitantes"):
    pestañas.append("📝 Registrar Habitante")
if tiene_permiso("gestion_bitacora"):
    pestañas.append("📜 Bitácora de Documentos")
if tiene_permiso("ver_estadisticas"):
    pestañas.append("📈 Estadísticas")
if tiene_permiso("personalizar_etiquetas"):
    pestañas.append("✏️ Personalizar Formulario")
if st.session_state.rol_actual == "Master":
    pestañas.append("👥 Usuarios y Permisos")
if tiene_permiso("respaldos_importacion") or st.session_state.rol_actual == "Master":
    pestañas.append("💾 Respaldos y Borrado")

if not pestañas:
    st.warning("⚠️ No tienes permisos asignados para ver módulos en la aplicación. Contacta al Usuario Master.")
    st.stop()

tabs = st.tabs(pestañas)

# -----------------------------------------------------------------------------
# TAB: CONSULTAR Y FILTROS
# -----------------------------------------------------------------------------
if "📊 Consultar y Filtros" in pestañas:
    with tabs[pestañas.index("📊 Consultar y Filtros")]:
        st.subheader("📊 Búsqueda Global y Consulta de Grupo Familiar")
        df = cargar_habitantes()
        
        if not df.empty:
            df["edad_num"] = df["fecha_nac"].apply(calcular_edad)
            df["tiempo_comunidad_num"] = df["fecha_llegada"].apply(calcular_tiempo_comunidad)
            
            col_search1, col_search2, col_search3 = st.columns([2, 2, 1])
            with col_search1:
                busqueda = st.text_input("🔍 Buscar por texto:", placeholder="Cédula, Nombres, Dirección, etc...")
            
            with col_search2:
                jefes_lista = obtener_jefes_hogar()
                opciones_jefes = [("TODOS", "👨‍👩‍👧‍👦 -- Ver Todos los Grupos --")] + [(j[0], f"🏡 {j[1]} {j[2]} (C.I: {j[0]})") for j in jefes_lista]
                
                jefe_filtro_sel = st.selectbox(
                    "👨‍👩‍👧‍👦 Filtrar por Grupo Familiar (Jefe de Hogar):", [op[0] for op in opciones_jefes],
                    format_func=lambda code: dict(opciones_jefes).get(code, code)
                )

            with col_search3:
                vista_modo = st.radio("Modo de vista:", ["Tarjetas Visuales", "Tabla Resumida"], horizontal=True)

            df_filtrado = df.copy()
            if busqueda.strip():
                df_filtrado = df_filtrado[df_filtrado.apply(lambda row: row.astype(str).str.contains(busqueda, case=False).any(), axis=1)]
            
            if jefe_filtro_sel != "TODOS":
                df_filtrado = df_filtrado[(df_filtrado["cedula"] == jefe_filtro_sel) | (df_filtrado["jefe_hogar_cedula"] == jefe_filtro_sel)]

            st.caption(f"Mostrando {len(df_filtrado)} registro(s) encontrado(s).")

            if not df_filtrado.empty:
                col_dl1, col_dl2, _ = st.columns([1, 1, 2])
                with col_dl1:
                    csv_data = df_filtrado.to_csv(index=False, sep=";", encoding="utf-8-sig")
                    st.download_button(
                        label="📥 Descargar Encontrados (CSV)",
                        data=csv_data,
                        file_name=f"censo_busqueda_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                with col_dl2:
                    buffer_excel = io.BytesIO()
                    with pd.ExcelWriter(buffer_excel, engine='openpyxl') as writer:
                        df_filtrado.to_excel(writer, index=False, sheet_name="Resultados")
                    st.download_button(
                        label="📊 Descargar Encontrados (Excel)",
                        data=buffer_excel.getvalue(),
                        file_name=f"censo_busqueda_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
                st.markdown("---")

            if vista_modo == "Tarjetas Visuales":
                for idx, hab in df_filtrado.iterrows():
                    cedula_curr = hab["cedula"]
                    nombre_completo = f"{hab['nombres']} {hab['apellidos']}"
                    es_jefe_flag = (hab['es_jefe_hogar'] == 1)
                    rol_familiar = "👑 JEFE DE HOGAR" if es_jefe_flag else "👨‍👩‍👧‍👦 Cargas / Familiar"
                    
                    cargas_asociadas = df[df["jefe_hogar_cedula"] == cedula_curr] if es_jefe_flag else pd.DataFrame()
                    num_cargas = len(cargas_asociadas)
                    badge_cargas = f" | 👨‍👩‍👧‍👦 {num_cargas} Familiar(es) a cargo" if es_jefe_flag else ""
                    
                    with st.expander(f"👤 **{nombre_completo}** (`{rol_familiar}`) — C.I: `{cedula_curr}` | Manzana: {hab['manzana']}{badge_cargas}", expanded=bool(busqueda.strip() or jefe_filtro_sel != "TODOS")):
                        
                        kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
                        kpi1.metric("🎂 Edad", f"{hab['edad_num']} años")
                        kpi2.metric("🏠 Tiempo Comunidad", f"{hab['tiempo_comunidad_num']} años")
                        kpi3.metric("👫 Sexo", hab['sexo'])
                        kpi4.metric("📞 Teléfono", hab['telefono'] if hab['telefono'] else "Sin datos")
                        kpi5.metric("🏘️ Manzana / Sector", hab['manzana'])

                        st.markdown("---")
                        
                        col_info1, col_info2 = st.columns(2)
                        with col_info1:
                            st.markdown("##### 📌 Datos Personales y Familiares")
                            st.write(f"**Condición Familiar:** {rol_familiar}")
                            if not es_jefe_flag and hab['jefe_hogar_cedula']:
                                match_jefe = df[df["cedula"] == hab['jefe_hogar_cedula']]
                                if not match_jefe.empty:
                                    j_nom = f"{match_jefe.iloc[0]['nombres']} {match_jefe.iloc[0]['apellidos']}"
                                    st.write(f"**Vínculo con Jefe de Hogar:** {j_nom} (`{hab['jefe_hogar_cedula']}`)")
                                else:
                                    st.write(f"**Jefe de Hogar (C.I.):** {hab['jefe_hogar_cedula']}")
                            st.write(f"**Fecha de Nacimiento:** {formato_fecha_pantalla(hab['fecha_nac'])}")
                            st.write(f"**Fecha de Llegada:** {formato_fecha_pantalla(hab['fecha_llegada'])}")
                            st.write(f"**Dirección Detallada:** {hab['direccion']}")

                        with col_info2:
                            st.markdown("##### ⚕️ Salud y Campos Personalizados")
                            st.write(f"**Condición de Salud:** {hab['condicion_salud']}")
                            if hab['detalle_salud']:
                                st.write(f"**Detalle Salud:** {hab['detalle_salud']}")
                            
                            try:
                                extras = json.loads(hab['campos_adicionales'])
                                if extras:
                                    st.markdown("**Campos Personalizados:**")
                                    for k_ext, v_ext in extras.items():
                                        st.write(f"- *{k_ext}:* {v_ext}")
                            except Exception:
                                pass

                        if es_jefe_flag:
                            st.markdown("---")
                            st.markdown(f"##### 👨‍👩‍👧‍👦 Cargas / Familiares Vinculados a {nombre_completo} ({num_cargas})")
                            if not cargas_asociadas.empty:
                                df_cargas_show = cargas_asociadas.copy()
                                df_cargas_show["Edad"] = df_cargas_show["fecha_nac"].apply(calcular_edad)
                                df_cargas_show["Fecha Nac."] = df_cargas_show["fecha_nac"].apply(formato_fecha_pantalla)
                                df_cargas_show["Nombre Completo"] = df_cargas_show["nombres"] + " " + df_cargas_show["apellidos"]
                                
                                cols_cargas = ["cedula", "Nombre Completo", "sexo", "Edad", "telefono", "condicion_salud"]
                                st.dataframe(df_cargas_show[cols_cargas].rename(columns={
                                    "cedula": "Cédula",
                                    "sexo": "Sexo",
                                    "telefono": "Teléfono",
                                    "condicion_salud": "Salud"
                                }), use_container_width=True, hide_index=True)
                            else:
                                st.info("ℹ️ No hay personas o cargas familiares registradas bajo este Jefe de Hogar.")

                        st.markdown("---")
                        
                        btn_col1, btn_col2, _ = st.columns([1, 1, 3])
                        
                        if tiene_permiso("editar_habitantes"):
                            with btn_col1:
                                if st.button("✏️ Editar Datos", key=f"btn_edit_{cedula_curr}", use_container_width=True):
                                    st.session_state[f"modo_edit_{cedula_curr}"] = not st.session_state.get(f"modo_edit_{cedula_curr}", False)

                        if tiene_permiso("eliminar_habitantes"):
                            with btn_col2:
                                if st.button("🗑️ Eliminar Registro", key=f"btn_del_{cedula_curr}", type="primary", use_container_width=True):
                                    eliminar_habitante(cedula_curr)
                                    st.success(f"Habitante con cédula {cedula_curr} eliminado.")
                                    st.rerun()

                        if st.session_state.get(f"modo_edit_{cedula_curr}", False):
                            st.markdown("---")
                            st.subheader(f"🛠️ Editar Datos de {nombre_completo}")
                            
                            col_ins1, col_ins2 = st.columns(2)
                            with col_ins1:
                                e_ced = st.text_input("Cédula:", value=hab['cedula'], key=f"e_ced_{cedula_curr}")
                                e_nom = st.text_input("Nombres:", value=hab['nombres'], key=f"e_nom_{cedula_curr}")
                                e_ape = st.text_input("Apellidos:", value=hab['apellidos'], key=f"e_ape_{cedula_curr}")
                                e_tel = st.text_input("Teléfono:", value=hab['telefono'], key=f"e_tel_{cedula_curr}")
                            with col_ins2:
                                e_sex = st.selectbox("Sexo:", ["Femenino", "Masculino", "Otro"], index=0 if hab['sexo']=="Femenino" else (1 if hab['sexo']=="Masculino" else 2), key=f"e_sex_{cedula_curr}")
                                e_fn = st.date_input(
                                    "Fecha Nacimiento:", 
                                    value=parsear_fecha_bd(hab['fecha_nac']), 
                                    min_value=datetime(1900, 1, 1).date(), 
                                    max_value=datetime.now().date(), 
                                    format="DD/MM/YYYY",
                                    key=f"e_fn_{cedula_curr}"
                                )
                                e_fl = st.date_input(
                                    "Fecha Llegada:", 
                                    value=parsear_fecha_bd(hab['fecha_llegada']), 
                                    min_value=datetime(1900, 1, 1).date(), 
                                    max_value=datetime.now().date(), 
                                    format="DD/MM/YYYY",
                                    key=f"e_fl_{cedula_curr}"
                                )
                            
                            e_es_jefe = st.checkbox("¿Es Jefe de Hogar?", value=bool(hab['es_jefe_hogar']), key=f"e_es_jefe_{cedula_curr}")
                            e_jefe_ced = ""
                            if not e_es_jefe:
                                jefes_disp = obtener_jefes_hogar()
                                ops_jefes_edit = [("", "-- Seleccionar Jefe de Hogar --")] + [(j[0], f"{j[1]} {j[2]} ({j[0]})") for j in jefes_disp if j[0] != cedula_curr]
                                idx_jefe = 0
                                for i_j, o_j in enumerate(ops_jefes_edit):
                                    if str(o_j[0]).strip() == str(hab['jefe_hogar_cedula']).strip():
                                        idx_jefe = i_j
                                        break
                                sel_jefe_edit = st.selectbox("Vincular a Jefe de Hogar:", [o[0] for o in ops_jefes_edit], index=idx_jefe, format_func=lambda c: dict(ops_jefes_edit).get(c, c), key=f"e_jefe_sel_{cedula_curr}")
                                e_jefe_ced = sel_jefe_edit

                            e_man = st.text_input("Manzana:", value=hab['manzana'], key=f"e_man_{cedula_curr}")
                            e_dir = st.text_area("Dirección:", value=hab['direccion'], key=f"e_dir_{cedula_curr}")
                            e_sal = st.text_input("Condición Salud:", value=hab['condicion_salud'], key=f"e_sal_{cedula_curr}")
                            e_detsal = st.text_input("Detalle Salud:", value=hab['detalle_salud'], key=f"e_detsal_{cedula_curr}")
                            
                            if st.button("💾 Guardar Cambios", key=f"btn_save_insitu_{cedula_curr}", type="primary", use_container_width=True):
                                datos_actualizados = (
                                    str(e_ced).strip(), str(e_nom).strip(), str(e_ape).strip(), e_sex,
                                    e_fn.strftime("%Y-%m-%d"), e_fl.strftime("%Y-%m-%d"),
                                    str(e_dir).strip(), str(e_man).strip(), str(e_tel).strip(),
                                    str(e_sal).strip(), str(e_detsal).strip(),
                                    1 if e_es_jefe else 0, str(e_jefe_ced).strip(),
                                    hab['campos_adicionales']
                                )
                                actualizar_habitante_completo(cedula_curr, datos_actualizados)
                                st.session_state[f"modo_edit_{cedula_curr}"] = False
                                st.success("✅ Cambios guardados correctamente.")
                                st.rerun()

            else:
                df_tabla = df_filtrado.copy()
                df_tabla["Edad"] = df_tabla["edad_num"]
                df_tabla["Años Comunidad"] = df_tabla["tiempo_comunidad_num"]
                df_tabla["Rol Familiar"] = df_tabla["es_jefe_hogar"].apply(lambda x: "Jefe de Hogar" if x == 1 else "Familiar/Carga")
                df_tabla["fecha_nac"] = df_tabla["fecha_nac"].apply(formato_fecha_pantalla)
                df_tabla["fecha_llegada"] = df_tabla["fecha_llegada"].apply(formato_fecha_pantalla)
                
                cols_mostrar = ["cedula", "nombres", "apellidos", "Rol Familiar", "jefe_hogar_cedula", "sexo", "Edad", "manzana", "telefono", "condicion_salud"]
                st.dataframe(df_tabla[cols_mostrar].rename(columns={"jefe_hogar_cedula": "C.I. Jefe Hogar"}), use_container_width=True, hide_index=True)
        else:
            st.info("No hay registros cargados en la base de datos.")

# -----------------------------------------------------------------------------
# TAB: BITÁCORA DE DOCUMENTOS
# -----------------------------------------------------------------------------
if "📜 Bitácora de Documentos" in pestañas:
    with tabs[pestañas.index("📜 Bitácora de Documentos")]:
        st.subheader("📜 Registro y Bitácora de Emitidos (Cartas y Constancias)")
        df_bit = cargar_habitantes()
        
        if not df_bit.empty:
            col_b1, col_b2 = st.columns([1, 2])
            
            with col_b1:
                st.markdown("### ✍️ Emitir / Registrar Documento")
                habitante_sel = st.selectbox(
                    "Seleccione Habitante:", 
                    options=df_bit["cedula"].tolist(),
                    format_func=lambda c: f"{c} - {df_bit[df_bit['cedula']==c]['nombres'].values[0]} {df_bit[df_bit['cedula']==c]['apellidos'].values[0]}"
                )
                
                tipo_doc = st.selectbox("Tipo de Documento:", [
                    "Constancia de Residencia",
                    "Carta de Buena Conducta",
                    "Constancia de Soltería",
                    "Permiso de Mudanza",
                    "Aval Comunitario",
                    "Otro Documento"
                ], key="bit_tipo_doc")
                desc_doc = st.text_area("Observaciones / Detalles del Trámite:", key="bit_desc_doc")
                btn_bit = st.button("📜 Registrar en Bitácora", type="primary", use_container_width=True)
                
                if btn_bit:
                    registrar_documento_bitacora(habitante_sel, tipo_doc, desc_doc.strip(), st.session_state.usuario_actual)
                    st.success("✅ Trámite registrado en la bitácora del habitante.")
                    st.rerun()

            with col_b2:
                st.markdown(f"### 📑 Historial de Trámites del Habitante (`Cédula: {habitante_sel}`)")
                df_historial = obtener_bitacora_habitante(habitante_sel)
                
                if not df_historial.empty:
                    df_historial["fecha_emision"] = df_historial["fecha_emision"].apply(formato_fecha_pantalla)
                    df_historial.columns = ["ID", "Documento", "Detalles", "Fecha Emisión", "Emitido Por"]
                    st.dataframe(df_historial, use_container_width=True, hide_index=True)
                else:
                    st.info("No se han emitido constancias ni documentos previos para este habitante.")
        else:
            st.info("Registre habitantes para utilizar el módulo de bitácora.")

# -----------------------------------------------------------------------------
# TAB: REGISTRAR HABITANTE
# -----------------------------------------------------------------------------
if "📝 Registrar Habitante" in pestañas:
    with tabs[pestañas.index("📝 Registrar Habitante")]:
        st.subheader("📝 Formulario Unificado de Registro de Habitante")
        
        datos_extra = {}
        
        st.markdown("### 👤 Datos Personales e Identificación")
        col1, col2 = st.columns(2)
        with col1:
            cedula = renderizar_campo_dinamico("cedula", cfg_campos, key_suffix="reg")
            nombres = renderizar_campo_dinamico("nombres", cfg_campos, key_suffix="reg")
            apellidos = renderizar_campo_dinamico("apellidos", cfg_campos, key_suffix="reg")
        with col2:
            sexo = renderizar_campo_dinamico("sexo", cfg_campos, key_suffix="reg")
            lbl_fn = cfg_campos.get("fecha_nac", {}).get("etiqueta", "Fecha de Nacimiento")
            
            if "reg_fn_key" not in st.session_state:
                st.session_state["reg_fn_key"] = datetime(1990, 1, 1).date()
                
            fecha_nac = st.date_input(
                f"{lbl_fn} (DD/MM/YYYY)", 
                min_value=datetime(1900, 1, 1).date(), 
                max_value=datetime.now().date(), 
                format="DD/MM/YYYY",
                key="reg_fn_key"
            )
            telefono = renderizar_campo_dinamico("telefono", cfg_campos, key_suffix="reg")

        st.markdown("---")

        st.markdown("### 👨‍👩‍👧‍👦 Núcleo Familiar")
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            if "reg_es_jefe_key" not in st.session_state:
                st.session_state["reg_es_jefe_key"] = False
            es_jefe = st.checkbox("¿Es el Jefe de Hogar?", help="Marque si esta persona encabeza la familia", key="reg_es_jefe_key")
        
        jefe_seleccionado_cedula = ""
        with col_f2:
            if not es_jefe:
                jefes_existentes = obtener_jefes_hogar()
                if jefes_existentes:
                    opciones_jefes = [("", "-- Seleccionar Jefe de Hogar --")] + [(str(j[0]).strip(), f"{j[1]} {j[2]} ({j[0]})") for j in jefes_existentes]
                    if "reg_sel_jefe_key" not in st.session_state:
                        st.session_state["reg_sel_jefe_key"] = ""
                    sel_jefe = st.selectbox(
                        "Seleccionar Jefe de Hogar vinculado:",
                        options=[op[0] for op in opciones_jefes],
                        format_func=lambda code: dict(opciones_jefes).get(code, code),
                        help="Busca en la base de datos a las personas marcadas como Jefe de hogar",
                        key="reg_sel_jefe_key"
                    )
                    jefe_seleccionado_cedula = sel_jefe
                else:
                    st.info("ℹ️ No hay Jefes de Hogar registrados aún. Puede registrar primero al Jefe de Hogar.")

        st.markdown("---")

        st.markdown("### 🏠 Ubicación y Vivienda")
        col3, col4 = st.columns(2)
        with col3:
            manzana = renderizar_campo_dinamico("manzana", cfg_campos, key_suffix="reg")
            lbl_fl = cfg_campos.get("fecha_llegada", {}).get("etiqueta", "Fecha de Llegada")
            if "reg_fl_key" not in st.session_state:
                st.session_state["reg_fl_key"] = datetime(2010, 1, 1).date()
            fecha_llegada = st.date_input(
                f"{lbl_fl} (DD/MM/YYYY)", 
                min_value=datetime(1900, 1, 1).date(), 
                max_value=datetime.now().date(), 
                format="DD/MM/YYYY",
                key="reg_fl_key"
            )
        with col4:
            direccion = renderizar_campo_dinamico("direccion", cfg_campos, key_suffix="reg")

        st.markdown("---")

        st.markdown("### ⚕️ Salud y Vulnerabilidad")
        col5, col6 = st.columns(2)
        with col5:
            condicion_salud = renderizar_campo_dinamico("condicion_salud", cfg_campos, key_suffix="reg")
        with col6:
            detalle_salud = renderizar_campo_dinamico("detalle_salud", cfg_campos, key_suffix="reg")

        st.markdown("---")

        campos_config = cargar_campos_personalizados()
        if campos_config:
            st.markdown("### ➕ Campos Personalizados Agregados")
            col_c1, col_c2 = st.columns(2)
            for idx, c_item in enumerate(campos_config):
                nom_c = c_item["nombre"]
                tipo_c = c_item["tipo"]
                ops_c = c_item["opciones"]
                key_cust = f"reg_cust_{c_item['id']}"
                
                if key_cust not in st.session_state:
                    st.session_state[key_cust] = ops_c[0] if (tipo_c == "Desplegable" and ops_c) else ""
                
                target_col = col_c1 if idx % 2 == 0 else col_c2
                with target_col:
                    if tipo_c == "Desplegable" and ops_c:
                        datos_extra[nom_c] = st.selectbox(f"{nom_c}:", options=ops_c, key=key_cust)
                    else:
                        datos_extra[nom_c] = st.text_input(f"{nom_c}:", key=key_cust)

        st.markdown("---")
        guardar = st.button("💾 Guardar Registro de Habitante", type="primary", use_container_width=True)

        if guardar:
            if str(nombres).strip() and str(apellidos).strip() and str(cedula).strip():
                json_extra = json.dumps(datos_extra, ensure_ascii=False)
                datos = (
                    str(cedula).strip(), str(nombres).strip(), str(apellidos).strip(), str(sexo).strip(),
                    fecha_nac.strftime("%Y-%m-%d"), fecha_llegada.strftime("%Y-%m-%d"),
                    str(direccion).strip(), str(manzana).strip(), str(telefono).strip(),
                    str(condicion_salud).strip(), str(detalle_salud).strip(),
                    1 if es_jefe else 0, str(jefe_seleccionado_cedula).strip(), json_extra
                )
                guardar_habitante(datos)
                
                # REINICIO LIMPIO DE TODOS LOS CAMPOS
                for key_campo in cfg_campos.keys():
                    key_w = f"{key_campo}_reg"
                    cfg = cfg_campos.get(key_campo, {})
                    ops = cfg.get("opciones", [])
                    st.session_state[key_w] = ops[0] if (cfg.get("tipo_control") == "desplegable" and ops) else ""

                st.session_state["reg_fn_key"] = datetime(1990, 1, 1).date()
                st.session_state["reg_fl_key"] = datetime(2010, 1, 1).date()
                st.session_state["reg_es_jefe_key"] = False
                if "reg_sel_jefe_key" in st.session_state:
                    st.session_state["reg_sel_jefe_key"] = ""
                    
                for c_item in campos_config:
                    key_c = f"reg_cust_{c_item['id']}"
                    st.session_state[key_c] = c_item["opciones"][0] if (c_item["tipo"] == "Desplegable" and c_item["opciones"]) else ""

                st.toast(f"✅ ¡Registro de {nombres} {apellidos} guardado con éxito! Formulario vaciado.", icon="🎉")
                st.rerun()
            else:
                st.error("⚠️ Ingrese los campos obligatorios (Cédula, Nombres y Apellidos).")

# -----------------------------------------------------------------------------
# TAB: ESTADÍSTICAS
# -----------------------------------------------------------------------------
if "📈 Estadísticas" in pestañas:
    with tabs[pestañas.index("📈 Estadísticas")]:
        st.subheader("📈 Resumen Estadístico e Indicadores Demográficos")
        df_stat = cargar_habitantes()
        
        if not df_stat.empty:
            df_stat["edad"] = df_stat["fecha_nac"].apply(calcular_edad)
            
            st.markdown("### 👑 Jefes de Familia Registrados")
            df_jefes = df_stat[df_stat["es_jefe_hogar"] == 1].copy()
            total_jefes = len(df_jefes)
            
            if total_jefes > 0:
                conteo_cargas = df_stat[df_stat["jefe_hogar_cedula"] != ""].groupby("jefe_hogar_cedula").size().to_dict()
                df_jefes["cargas_count"] = df_jefes["cedula"].map(conteo_cargas).fillna(0).astype(int)
                
                k_jefe1, k_jefe2, k_jefe3 = st.columns(3)
                k_jefe1.metric("Total Jefes de Hogar", total_jefes)
                k_jefe2.metric("Total Cargas / Familiares Vinculados", df_jefes["cargas_count"].sum())
                k_jefe3.metric("Promedio Integrantes por Hogar", f"{((df_jefes['cargas_count'].sum() + total_jefes) / total_jefes):.1f}")
                
                st.markdown("##### 📋 Listado Detallado de Jefes de Hogar")
                df_jefes_tabla = df_jefes.copy()
                df_jefes_tabla["Nombre Completo"] = df_jefes_tabla["nombres"] + " " + df_jefes_tabla["apellidos"]
                df_jefes_tabla["Edad"] = df_jefes_tabla["edad"]
                
                cols_jefes_show = ["cedula", "Nombre Completo", "sexo", "Edad", "manzana", "telefono", "cargas_count"]
                st.dataframe(
                    df_jefes_tabla[cols_jefes_show].rename(columns={
                        "cedula": "Cédula",
                        "sexo": "Sexo",
                        "manzana": "Manzana",
                        "telefono": "Teléfono",
                        "cargas_count": "Familiares a Cargo"
                    }), 
                    use_container_width=True, 
                    hide_index=True
                )
            else:
                st.warning("⚠️ No se encuentran Jefes de Familia registrados actualmente en el sistema.")
                
            st.markdown("---")
            
            def clasificar_rango_edad(edad):
                if edad <= 12: return "0 a 12 años"
                elif 13 <= edad <= 15: return "13 a 15 años"
                elif 16 <= edad <= 17: return "16 a 17 años"
                elif 18 <= edad < 60: return "18 a 59 años"
                else: return "60+ años"
            
            df_stat["rango_etario"] = df_stat["edad"].apply(clasificar_rango_edad)
            
            st.markdown("##### 🔍 Filtrar Estadísticas Demográficas por Sexo")
            opciones_sexo = ["Todos"] + list(df_stat["sexo"].unique())
            sexo_filtro = st.selectbox("Seleccione para filtrar las métricas:", opciones_sexo)
            
            if sexo_filtro != "Todos":
                df_stat_calc = df_stat[df_stat["sexo"] == sexo_filtro]
            else:
                df_stat_calc = df_stat.copy()

            st.markdown("---")
            
            kpi_e1, kpi_e2, kpi_e3, kpi_e4, kpi_e5 = st.columns(5)
            kpi_e1.metric("Población Seleccionada", len(df_stat_calc))
            kpi_e2.metric("Niños (0 a 12 años)", len(df_stat_calc[df_stat_calc["edad"] <= 12]))
            kpi_e3.metric("Mayores de 15 años", len(df_stat_calc[df_stat_calc["edad"] > 15]))
            kpi_e4.metric("Mayores de 18 años", len(df_stat_calc[df_stat_calc["edad"] >= 18]))
            kpi_e5.metric("Mayores de 60 años", len(df_stat_calc[df_stat_calc["edad"] >= 60]))

            st.markdown("---")
            
            col_g1, col_g2 = st.columns(2)
            
            with col_g1:
                st.markdown("##### 📊 Rangos de Edad Distribuidos por Sexo")
                df_edad_sexo = df_stat.groupby(["rango_etario", "sexo"]).size().reset_index(name="Cantidad")
                fig_edad_sexo = px.bar(
                    df_edad_sexo, 
                    x="rango_etario", 
                    y="Cantidad", 
                    color="sexo", 
                    barmode="group",
                    title="Comparativa de Edades por Sexo",
                    color_discrete_sequence=px.colors.qualitative.Set2
                )
                st.plotly_chart(fig_edad_sexo, use_container_width=True)

                st.markdown("##### 👥 Distribución Total por Sexo / Género")
                fig_sexo = px.pie(df_stat, names="sexo", hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
                st.plotly_chart(fig_sexo, use_container_width=True)

            with col_g2:
                st.markdown("##### 🏘️ Habitantes por Manzana y Sexo")
                df_manzana_sexo = df_stat.groupby(["manzana", "sexo"]).size().reset_index(name="Habitantes")
                fig_manz_sexo = px.bar(
                    df_manzana_sexo, 
                    x="manzana", 
                    y="Habitantes", 
                    color="sexo", 
                    title="Habitantes por Manzana desglosados por Sexo",
                    color_discrete_sequence=px.colors.qualitative.Safe
                )
                st.plotly_chart(fig_manz_sexo, use_container_width=True)

                st.markdown("##### ⚕️ Condición de Salud por Sexo")
                df_salud_sexo = df_stat[df_stat["condicion_salud"] != "Ninguna"].groupby(["condicion_salud", "sexo"]).size().reset_index(name="Casos")
                if not df_salud_sexo.empty:
                    fig_salud_sex = px.bar(
                        df_salud_sexo, 
                        x="condicion_salud", 
                        y="Casos", 
                        color="sexo", 
                        title="Afectaciones de Salud por Sexo"
                    )
                    st.plotly_chart(fig_salud_sex, use_container_width=True)
                else:
                    st.info("No hay condiciones de salud especiales registradas.")
        else:
            st.info("📊 No hay datos suficientes para generar estadísticas.")

# -----------------------------------------------------------------------------
# TAB: PERSONALIZAR FORMULARIO
# -----------------------------------------------------------------------------
if "✏️ Personalizar Formulario" in pestañas:
    with tabs[pestañas.index("✏️ Personalizar Formulario")]:
        st.subheader("✏️ Gestión Completa de Campos Personalizados y Etiquetas")
        
        st.markdown("### ➕ Añadir Nuevo Campo Personalizado")
        col_nc1, col_nc2, col_nc3 = st.columns([2, 1.5, 3])
        with col_nc1:
            nom_nuevo = st.text_input("Nombre del Campo:", placeholder="Ej: Nivel Educativo, Ocupación...", key="nc_nom")
        with col_nc2:
            tipo_nuevo = st.selectbox("Tipo de Dato:", ["Texto", "Desplegable"], key="nc_tipo")
        with col_nc3:
            ops_nuevo = st.text_input("Opciones si es Desplegable (separadas por comas):", placeholder="Opción 1, Opción 2, Opción 3", key="nc_ops")
            
        btn_crear_campo = st.button("➕ Añadir Campo", type="primary", use_container_width=True)
        
        if btn_crear_campo:
            if nom_nuevo.strip():
                lista_ops = [x.strip() for x in ops_nuevo.split(",") if x.strip()]
                agregar_campo_personalizado(nom_nuevo.strip(), tipo_nuevo, lista_ops)
                st.success(f"✅ Campo '{nom_nuevo.strip()}' creado con éxito.")
                st.rerun()
            else:
                st.error("Ingrese el nombre del nuevo campo.")

        st.markdown("---")

        st.markdown("### 🛠️ Gestionar, Renombrar y Editar Campos Personalizados")
        lista_campos_cust = cargar_campos_personalizados()
        
        if lista_campos_cust:
            for c_cust in lista_campos_cust:
                c_id = c_cust["id"]
                c_nom = c_cust["nombre"]
                c_tipo = c_cust["tipo"]
                c_ops = ", ".join(c_cust["opciones"]) if c_cust["opciones"] else ""
                
                with st.expander(f"⚙️ Campo: **{c_nom}** (`Tipo: {c_tipo}`)"):
                    col_ec1, col_ec2, col_ec3 = st.columns([2, 1.5, 3])
                    with col_ec1:
                        e_nom_cust = st.text_input("Renombrar Campo:", value=c_nom, key=f"e_nom_{c_id}")
                    with col_ec2:
                        e_tipo_cust = st.selectbox("Cambiar Tipo de Dato:", ["Texto", "Desplegable"], index=0 if c_tipo=="Texto" else 1, key=f"e_tipo_{c_id}")
                    with col_ec3:
                        e_ops_cust = st.text_input("Opciones (separadas por comas):", value=c_ops, key=f"e_ops_{c_id}")

                    col_btn1, col_btn2 = st.columns(2)
                    with col_btn1:
                        btn_upd = st.button("💾 Actualizar Campo", key=f"btn_upd_cust_{c_id}", type="primary", use_container_width=True)
                    with col_btn2:
                        btn_del = st.button("🗑️ Eliminar Campo", key=f"btn_del_cust_{c_id}", use_container_width=True)

                    if btn_upd:
                        lista_ops_updated = [x.strip() for x in e_ops_cust.split(",") if x.strip()]
                        actualizar_campo_personalizado(c_id, e_nom_cust.strip(), e_tipo_cust, lista_ops_updated)
                        st.success(f"✅ Campo '{c_nom}' actualizado a '{e_nom_cust.strip()}'. Estructura guardada actualizada.")
                        st.rerun()

                    if btn_del:
                        eliminar_campo_personalizado(c_id)
                        st.warning(f"Campo '{c_nom}' eliminado y limpiado de la base de datos.")
                        st.rerun()
        else:
            st.info("No hay campos personalizados adicionales creados.")

        st.markdown("---")

        st.markdown("### ⚙️ Configurar Etiquetas de Campos Base Predeterminados")
        for clave, (etiqueta_def, tipo_def, opciones_def) in CAMPOS_BASE_DEFAULT.items():
            st.markdown(f"##### Campo Base: `{clave}`")
            c_data = cfg_campos.get(clave, {"etiqueta": etiqueta_def, "tipo_control": tipo_def, "opciones": json.loads(opciones_def)})
            
            col_c1, col_c2, col_c3 = st.columns([2, 1.5, 3])
            with col_c1:
                st.text_input(f"Etiqueta visible ({clave}):", value=c_data["etiqueta"], key=f"cfg_lbl_{clave}")
            with col_c2:
                st.selectbox(
                    "Tipo de control:",
                    ["texto", "desplegable"],
                    index=0 if c_data["tipo_control"] == "texto" else 1,
                    key=f"cfg_tipo_{clave}"
                )
            with col_c3:
                str_opciones_actuales = ", ".join(c_data["opciones"])
                st.text_input(
                    "Opciones (separadas por comas):",
                    value=str_opciones_actuales,
                    key=f"cfg_ops_{clave}"
                )
            st.markdown("---")

        if st.button("💾 Guardar Etiquetas de Campos Base", type="primary", use_container_width=True):
            for clave in CAMPOS_BASE_DEFAULT.keys():
                etiq_val = st.session_state[f"cfg_lbl_{clave}"].strip()
                tipo_ctrl_val = st.session_state[f"cfg_tipo_{clave}"]
                ops_raw = st.session_state[f"cfg_ops_{clave}"]
                
                lista_ops = [x.strip() for x in ops_raw.split(",") if x.strip()]
                guardar_configuracion_campo(clave, etiq_val, tipo_ctrl_val, lista_ops)
            
            st.success("✅ Configuración guardada correctamente.")
            st.rerun()

# -----------------------------------------------------------------------------
# TAB: GESTIÓN DE USUARIOS
# -----------------------------------------------------------------------------
if st.session_state.rol_actual == "Master" and "👥 Usuarios y Permisos" in pestañas:
    with tabs[pestañas.index("👥 Usuarios y Permisos")]:
        st.subheader("👥 Control de Usuarios y Matriz de Permisos")
        
        df_users = cargar_usuarios()
        col_u1, col_u2 = st.columns([1, 1])
        
        with col_u1:
            st.markdown("### ➕ Crear / Editar Usuario")
            user_sel = st.selectbox("Editar usuario existente o crear nuevo:", ["-- Crear Nuevo --"] + list(df_users["username"]))
            
            if user_sel != "-- Crear Nuevo --":
                row_u = df_users[df_users["username"] == user_sel].iloc[0]
                val_username = row_u["username"]
                val_nombre = row_u["nombre_completo"]
                val_rol = row_u["rol"]
                try:
                    perm_actuales = json.loads(row_u["permisos"])
                except Exception:
                    perm_actuales = {}
            else:
                val_username, val_nombre, val_rol, perm_actuales = "", "", "Administrador", {}

            u_username = st.text_input("Username:", value=val_username, disabled=(user_sel != "-- Crear Nuevo --"), key="usr_input_name")
            u_pass = st.text_input("Contraseña (dejar en blanco para mantener actual):", type="password", key="usr_input_pass")
            u_nombre = st.text_input("Nombre Completo:", value=val_nombre, key="usr_input_fullname")
            u_rol = st.selectbox("Rol Asignado:", ["Administrador", "Visualizador"], index=0 if val_rol == "Administrador" else 1, key="usr_input_rol")
            
            st.markdown("#### 🔑 Permisos:")
            nuevos_permisos = {}
            for perm in LISTA_PERMISOS:
                val_check = perm_actuales.get(perm, False)
                nuevos_permisos[perm] = st.checkbox(f"Permitir: `{perm}`", value=val_check, key=f"perm_chk_{perm}")
            
            if st.button("💾 Guardar Usuario y Permisos", type="primary", use_container_width=True):
                target_user = u_username.strip() if user_sel == "-- Crear Nuevo --" else user_sel
                if target_user:
                    guardar_usuario(target_user, u_pass, u_nombre.strip(), u_rol, nuevos_permisos)
                    st.success(f"✅ Usuario {target_user} guardado.")
                    st.rerun()
                else:
                    st.error("Ingrese un usuario válido.")

        with col_u2:
            st.markdown("### 📋 Usuarios Registrados")
            st.dataframe(df_users[["username", "nombre_completo", "rol"]], use_container_width=True, hide_index=True)
            
            st.markdown("---")
            st.markdown("### 🗑️ Eliminar Usuario")
            u_del = st.selectbox("Seleccionar usuario a eliminar:", [u for u in df_users["username"] if u != "master"])
            if st.button("🗑️ Eliminar Usuario Seleccionado", type="primary"):
                eliminar_usuario(u_del)
                st.success("Usuario eliminado.")
                st.rerun()

# -----------------------------------------------------------------------------
# TAB: RESPALDOS Y BORRADO TOTAL
# -----------------------------------------------------------------------------
if "💾 Respaldos y Borrado" in pestañas:
    with tabs[pestañas.index("💾 Respaldos y Borrado")]:
        st.subheader("💾 Gestión de Respaldos e Importación")
        
        col_res1, col_res2 = st.columns(2)
        
        with col_res1:
            st.markdown("### 📤 Exportar Datos General")
            df_exp = cargar_habitantes()
            if not df_exp.empty:
                csv_bytes = df_exp.to_csv(index=False, sep=";", encoding="utf-8-sig")
                st.download_button("📥 Descargar Censo Completo (CSV)", csv_bytes, "censo_comunidad_completo.csv", "text/csv")
                
                buffer_exc = io.BytesIO()
                with pd.ExcelWriter(buffer_exc, engine='openpyxl') as writer:
                    df_exp.to_excel(writer, index=False, sheet_name="Censo")
                st.download_button("📊 Descargar Censo Completo (Excel)", buffer_exc.getvalue(), "censo_comunidad_completo.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        with col_res2:
            st.markdown("### 📥 Importar Archivos (CSV / Excel)")
            uploaded_file = st.file_uploader("Cargar archivo", type=["csv", "xlsx"])
            if uploaded_file is not None and st.button("📥 Procesar e Importar"):
                try:
                    if uploaded_file.name.endswith(".xlsx"):
                        df_imp = pd.read_excel(uploaded_file, dtype=str)
                    else:
                        try:
                            df_imp = pd.read_csv(uploaded_file, sep=";", encoding="utf-8-sig", dtype=str)
                            if len(df_imp.columns) <= 1:
                                uploaded_file.seek(0)
                                df_imp = pd.read_csv(uploaded_file, sep=",", dtype=str)
                        except Exception:
                            uploaded_file.seek(0)
                            df_imp = pd.read_csv(uploaded_file, sep=",", dtype=str)

                    # Limpieza flexible de encabezados
                    df_imp.columns = [str(col).strip().lower().replace(" ", "_") for col in df_imp.columns]

                    def buscar_valor_columna(row, lista_posibles):
                        for col in lista_posibles:
                            if col in row and pd.notna(row[col]):
                                return str(row[col]).strip()
                        return ""

                    registros_procesados = 0
                    for _, row in df_imp.iterrows():
                        ced_val = buscar_valor_columna(row, ["cedula", "ci", "cédula", "documento"])
                        if not ced_val or ced_val.lower() == "nan":
                            continue

                        f_nac_imp = parsear_fecha_bd(buscar_valor_columna(row, ["fecha_nacimiento", "fecha_nac", "fecha_nacimiento_dd/mm/yyyy"])).strftime("%Y-%m-%d")
                        f_lleg_imp = parsear_fecha_bd(buscar_valor_columna(row, ["fecha_llegada", "fecha_llegada_a_la_comunidad"])).strftime("%Y-%m-%d")
                        
                        jefe_ced_imp = buscar_valor_columna(row, [
                            "jefe_hogar_cedula", "jefe_cedula", "cedula_jefe", 
                            "c.i._jefe_hogar", "jefe_hogar", "jefe"
                        ])
                        
                        es_jefe_raw = buscar_valor_columna(row, ["es_jefe_hogar", "es_jefe", "jefe_de_hogar"])
                        es_jefe_val = 1 if es_jefe_raw.lower() in ["1", "true", "si", "sì", "sí"] else 0

                        guardar_habitante((
                            ced_val,
                            buscar_valor_columna(row, ["nombres", "nombre"]),
                            buscar_valor_columna(row, ["apellidos", "apellido"]),
                            buscar_valor_columna(row, ["sexo", "genero", "género"]) or "No especificado",
                            f_nac_imp,
                            f_lleg_imp,
                            buscar_valor_columna(row, ["direccion", "dirección", "direccion_detallada"]),
                            buscar_valor_columna(row, ["manzana", "sector"]),
                            buscar_valor_columna(row, ["telefono", "teléfono", "celular"]),
                            buscar_valor_columna(row, ["condicion_salud", "condición_salud", "salud"]) or "Ninguna",
                            buscar_valor_columna(row, ["detalle_salud", "detalles_salud"]),
                            es_jefe_val,
                            jefe_ced_imp,
                            buscar_valor_columna(row, ["campos_adicionales"]) or "{}"
                        ))
                        registros_procesados += 1
                        
                    st.success(f"✅ Importación completada. Se procesaron {registros_procesados} registros correctamente.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al importar archivo: {e}")

        st.markdown("---")
        st.markdown("### ⚠️ Zona Peligrosa: Borrado Completo del Censo")
        confirmar_borrado = st.checkbox("Confirmo que deseo borrar todos los datos del censo definitivamente.")
        
        if st.button("💣 BORRAR TODO EL CENSO", type="primary", use_container_width=True):
            if confirmar_borrado:
                borrar_todo_el_censo()
                st.success("🔥 Base de datos vaciada completamente.")
                st.rerun()
            else:
                st.warning("Marque la casilla para confirmar.")
