import sqlite3
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import io

# -----------------------------------------------------------------------------
# 1. CONFIGURACIÓN DE PÁGINA Y BASE DE DATOS
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Censo Comunitario Avanzado", page_icon="🏡", layout="wide")

DB_FILE = "censo.db"

def get_connection():
    return sqlite3.connect(DB_FILE)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Tabla de Habitantes (incluye campo 'sexo')
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
            telefono TEXT
        )
    """)
    
    # Tabla de Usuarios y Roles
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            username TEXT PRIMARY KEY,
            password TEXT,
            nombre_completo TEXT,
            rol TEXT
        )
    """)
    
    # Tabla de Bitácora / Historial de Documentos Emitidos
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
    
    # Crear usuario Master por defecto si no existen usuarios
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "INSERT INTO usuarios VALUES (?, ?, ?, ?)",
            ("master", "master123", "Usuario Master", "Master")
        )
        cursor.execute(
            "INSERT INTO usuarios VALUES (?, ?, ?, ?)",
            ("admin", "admin123", "Administrador Principal", "Administrador")
        )
        cursor.execute(
            "INSERT INTO usuarios VALUES (?, ?, ?, ?)",
            ("user", "user123", "Visualizador Invitado", "Visualizador")
        )
    
    conn.commit()
    conn.close()

init_db()

# -----------------------------------------------------------------------------
# 2. FUNCIONES DE BASE DE DATOS
# -----------------------------------------------------------------------------

# --- Habitantes ---
def cargar_habitantes():
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM habitantes", conn)
    conn.close()
    return df

def guardar_habitante(datos):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO habitantes (cedula, nombres, apellidos, sexo, fecha_nac, fecha_llegada, direccion, manzana, telefono)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, datos)
    conn.commit()
    conn.close()

def eliminar_habitante(cedula):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM habitantes WHERE cedula = ?", (cedula,))
    cursor.execute("DELETE FROM bitacora_documentos WHERE cedula = ?", (cedula,))
    conn.commit()
    conn.close()

# --- Usuarios y Autenticación ---
def verificar_login(username, password):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, nombre_completo, rol FROM usuarios WHERE username = ? AND password = ?", (username, password))
    user = cursor.fetchone()
    conn.close()
    return user

def cargar_usuarios():
    conn = get_connection()
    df = pd.read_sql_query("SELECT username, nombre_completo, rol FROM usuarios", conn)
    conn.close()
    return df

def guardar_usuario(username, password, nombre_completo, rol):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO usuarios VALUES (?, ?, ?, ?)", (username, password, nombre_completo, rol))
    conn.commit()
    conn.close()

def eliminar_usuario(username):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM usuarios WHERE username = ?", (username,))
    conn.commit()
    conn.close()

# --- Bitácora ---
def registrar_documento(cedula, tipo_doc, descripcion, emitido_por):
    conn = get_connection()
    cursor = conn.cursor()
    fecha_hoy = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO bitacora_documentos (cedula, tipo_documento, descripcion, fecha_emision, emitido_por)
        VALUES (?, ?, ?, ?, ?)
    """, (cedula, tipo_doc, descripcion, fecha_hoy, emitido_por))
    conn.commit()
    conn.close()

def cargar_bitacora(cedula=None):
    conn = get_connection()
    if cedula:
        query = "SELECT * FROM bitacora_documentos WHERE cedula = ? ORDER BY id DESC"
        df = pd.read_sql_query(query, conn, params=(cedula,))
    else:
        query = """
            SELECT b.id, b.cedula, h.nombres || ' ' || h.apellidos AS habitante, 
                   b.tipo_documento, b.descripcion, b.fecha_emision, b.emitido_por
            FROM bitacora_documentos b
            LEFT JOIN habitantes h ON b.cedula = h.cedula
            ORDER BY b.id DESC
        """
        df = pd.read_sql_query(query, conn)
    conn.close()
    return df

# -----------------------------------------------------------------------------
# 3. CÁLCULOS
# -----------------------------------------------------------------------------
def calcular_edad(fecha_nac_str):
    try:
        fecha_nac = datetime.strptime(fecha_nac_str, "%Y-%m-%d").date()
        hoy = datetime.now().date()
        return hoy.year - fecha_nac.year - ((hoy.month, hoy.day) < (fecha_nac.month, fecha_nac.day))
    except:
        return 0

def calcular_tiempo_comunidad(fecha_llegada_str):
    try:
        fecha_llegada = datetime.strptime(fecha_llegada_str, "%Y-%m-%d").date()
        hoy = datetime.now().date()
        años = hoy.year - fecha_llegada.year
        meses = hoy.month - fecha_llegada.month
        if hoy.day < fecha_llegada.day:
            meses -= 1
        if meses < 0:
            años -= 1
            meses += 12
        return f"{años} años, {meses} meses"
    except:
        return "N/A"

# -----------------------------------------------------------------------------
# 4. CONTROL DE SESIÓN Y LOGIN
# -----------------------------------------------------------------------------
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
    st.session_state.usuario_actual = None
    st.session_state.rol_actual = None

if not st.session_state.autenticado:
    st.markdown("<h1 style='text-align: center;'>🔒 Control de Acceso - Censo Comunitario</h1>", unsafe_allow_html=True)
    
    _, col_center, _ = st.columns([1, 2, 1])
    with col_center:
        with st.form("form_login"):
            usuario = st.text_input("Usuario")
            clave = st.text_input("Contraseña", type="password")
            btn_login = st.form_submit_button("Ingresar al Sistema", use_container_width=True)
            
            if btn_login:
                user_data = verificar_login(usuario, clave)
                if user_data:
                    st.session_state.autenticado = True
                    st.session_state.usuario_actual = user_data[1]
                    st.session_state.username = user_data[0]
                    st.session_state.rol_actual = user_data[2]
                    st.success(f"¡Bienvenido {user_data[1]}!")
                    st.rerun()
                else:
                    st.error("❌ Credenciales incorrectas.")
    st.stop()

# -----------------------------------------------------------------------------
# 5. BARRA LATERAL (MENÚ Y PERMISOS)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("👤 Perfil de Usuario")
    st.write(f"**Usuario:** {st.session_state.usuario_actual}")
    st.write(f"**Rol:** `{st.session_state.rol_actual}`")
    
    if st.button("🚪 Cerrar Sesión", use_container_width=True):
        st.session_state.autenticado = False
        st.session_state.usuario_actual = None
        st.session_state.rol_actual = None
        st.rerun()
        
    st.markdown("---")
    st.caption("Sistema de Censo Comunitario v2.0")

# Permisos
ROL = st.session_state.rol_actual
ES_MASTER = ROL == "Master"
ES_ADMIN_OR_MASTER = ROL in ["Master", "Administrador"]

# -----------------------------------------------------------------------------
# 6. INTERFAZ PRINCIPAL
# -----------------------------------------------------------------------------
st.title("🏡 Censo Digital de la Comunidad")

# Definir pestañas según permisos
pestañas = ["📊 Consultar y Filtros", "📈 Estadísticas (Gráficos)"]

if ES_ADMIN_OR_MASTER:
    pestañas.insert(0, "📝 Registrar Habitante")
    pestañas.append("📄 Bitácora de Documentos")
    pestañas.append("⚙️ Editar / Eliminar")

if ES_MASTER:
    pestañas.append("👥 Gestión de Usuarios")
    pestañas.append("💾 Respaldos e Importación")

tabs = st.tabs(pestañas)

# -----------------------------------------------------------------------------
# TAB: REGISTRAR HABITANTE (Master, Administrador)
# -----------------------------------------------------------------------------
if ES_ADMIN_OR_MASTER and "📝 Registrar Habitante" in pestañas:
    with tabs[pestañas.index("📝 Registrar Habitante")]:
        st.subheader("Formulario de Registro")
        with st.form("form_censo", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                nombres = st.text_input("Nombres*")
                apellidos = st.text_input("Apellidos*")
                cedula = st.text_input("Cédula de Identidad*")
                sexo = st.selectbox("Sexo / Género*", ["Femenino", "Masculino", "Otro"])
                telefono = st.text_input("Teléfono de Contacto")
            with col2:
                fecha_nac = st.date_input("Fecha de Nacimiento", min_value=datetime(1920, 1, 1), max_value=datetime.now())
                fecha_llegada = st.date_input("Fecha de Llegada a la Comunidad", min_value=datetime(1950, 1, 1), max_value=datetime.now())
                manzana = st.text_input("Manzana / Sector")
                direccion = st.text_input("Dirección de Habitación")

            guardar = st.form_submit_button("Guardar Registro", use_container_width=True)

        if guardar:
            if nombres.strip() and apellidos.strip() and cedula.strip():
                datos = (
                    cedula.strip(), nombres.strip(), apellidos.strip(), sexo,
                    fecha_nac.strftime("%Y-%m-%d"), fecha_llegada.strftime("%Y-%m-%d"),
                    direccion.strip(), manzana.strip(), telefono.strip()
                )
                guardar_habitante(datos)
                st.success(f"✅ ¡{nombres} {apellidos} ha sido registrado exitosamente!")
            else:
                st.error("⚠️ Complete los campos obligatorios (*).")

# -----------------------------------------------------------------------------
# TAB: CONSULTAR Y FILTROS (Todos)
# -----------------------------------------------------------------------------
with tabs[pestañas.index("📊 Consultar y Filtros")]:
    st.subheader("Consulta General del Censo")
    df = cargar_habitantes()
    
    if not df.empty:
        df["Edad"] = df["fecha_nac"].apply(calcular_edad)
        df["Tiempo Comunidad"] = df["fecha_llegada"].apply(calcular_tiempo_comunidad)
        
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            busqueda = st.text_input("Buscar por Nombre, Apellido o Cédula")
        with col_f2:
            sector_sel = st.selectbox("Manzana / Sector", ["Todos"] + list(df["manzana"].unique()))
        with col_f3:
            sexo_sel = st.selectbox("Filtrar por Sexo", ["Todos"] + list(df["sexo"].unique()))

        df_filtrado = df.copy()
        if busqueda:
            df_filtrado = df_filtrado[
                df_filtrado["nombres"].str.contains(busqueda, case=False, na=False) |
                df_filtrado["apellidos"].str.contains(busqueda, case=False, na=False) |
                df_filtrado["cedula"].str.contains(busqueda, case=False, na=False)
            ]
        if sector_sel != "Todos":
            df_filtrado = df_filtrado[df_filtrado["manzana"] == sector_sel]
        if sexo_sel != "Todos":
            df_filtrado = df_filtrado[df_filtrado["sexo"] == sexo_sel]

        # Métricas
        st.markdown("---")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Personas", len(df_filtrado))
        m2.metric("Promedio Edad", f"{df_filtrado['Edad'].mean():.1f} años" if len(df_filtrado) > 0 else "N/A")
        m3.metric("Femenino", len(df_filtrado[df_filtrado["sexo"] == "Femenino"]))
        m4.metric("Masculino", len(df_filtrado[df_filtrado["sexo"] == "Masculino"]))
        st.markdown("---")

        st.dataframe(df_filtrado, use_container_width=True, hide_index=True)
        
        # Exportar vista filtrada
        csv = df_filtrado.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Exportar Tabla Actual (CSV)", csv, "censo_filtrado.csv", "text/csv")
    else:
        st.info("No hay datos en el censo.")

# -----------------------------------------------------------------------------
# TAB: ESTADÍSTICAS Y GRÁFICOS DE TORTA (Todos)
# -----------------------------------------------------------------------------
with tabs[pestañas.index("📈 Estadísticas (Gráficos)")]:
    st.subheader("Análisis Estadístico por Edad y Sexo")
    df_stat = cargar_habitantes()
    
    if not df_stat.empty:
        df_stat["Edad"] = df_stat["fecha_nac"].apply(calcular_edad)
        
        st.markdown("##### 🎯 Filtro por Rango de Edad")
        min_e, max_e = int(df_stat["Edad"].min()), int(df_stat["Edad"].max())
        max_e = max_e if max_e > min_e else min_e + 1
        
        rango_edad = st.slider("Selecciona el Rango de Edad que deseas ver:", min_value=0, max_value=100, value=(min_e, max_e))
        
        # Filtrar DF según el slider
        df_range = df_stat[(df_stat["Edad"] >= rango_edad[0]) & (df_stat["Edad"] <= rango_edad[1])]
        
        st.write(f"Mostrando **{len(df_range)}** personas entre **{rango_edad[0]}** y **{rango_edad[1]}** años.")
        
        if not df_range.empty:
            col_g1, col_g2 = st.columns(2)
            
            with col_g1:
                # Gráfico de Torta por Sexo
                fig_sexo = px.pie(
                    df_range, 
                    names="sexo", 
                    title=f"Distribución por Sexo ({rango_edad[0]}-{rango_edad[1]} años)",
                    hole=0.4,
                    color_discrete_sequence=px.colors.qualitative.Set2
                )
                fig_sexo.update_traces(textinfo="percent+label+value")
                st.plotly_chart(fig_sexo, use_container_width=True)
                
            with col_g2:
                # Gráfico por Manzana / Sector en ese Rango de Edad
                fig_sec = px.pie(
                    df_range, 
                    names="manzana", 
                    title=f"Distribución por Sector/Manzana ({rango_edad[0]}-{rango_edad[1]} años)",
                    hole=0.4,
                    color_discrete_sequence=px.colors.qualitative.Pastel
                )
                fig_sec.update_traces(textinfo="percent+label")
                st.plotly_chart(fig_sec, use_container_width=True)
        else:
            st.warning("No hay habitantes en este rango de edad seleccionado.")
    else:
        st.info("No hay suficiente información para generar estadísticas.")

# -----------------------------------------------------------------------------
# TAB: BITÁCORA DE DOCUMENTOS (Master, Administrador)
# -----------------------------------------------------------------------------
if ES_ADMIN_OR_MASTER and "📄 Bitácora de Documentos" in pestañas:
    with tabs[pestañas.index("📄 Bitácora de Documentos")]:
        st.subheader("Emisión y Registro de Cartas / Documentos")
        
        df_hab = cargar_habitantes()
        if not df_hab.empty:
            col_b1, col_b2 = st.columns([1, 2])
            
            with col_b1:
                st.markdown("### 📝 Registrar Nuevo Documento")
                cedula_sel = st.selectbox("Seleccionar Habitante (Cédula):", df_hab["cedula"].unique())
                
                # Obtener nombre del seleccionado
                hab_info = df_hab[df_hab["cedula"] == cedula_sel].iloc[0]
                st.info(f"**Habitante:** {hab_info['nombres']} {hab_info['apellidos']}")
                
                tipo_doc = st.selectbox("Tipo de Documento:", [
                    "Carta de Residencia", 
                    "Carta de Buena Conducta", 
                    "Carta de Aval", 
                    "Constancia de Constatación", 
                    "Otro"
                ])
                descripcion_doc = st.text_area("Detalles / Motivo del documento:")
                
                if st.button("💾 Guardar en Bitácora", use_container_width=True):
                    if descripcion_doc.strip():
                        registrar_documento(cedula_sel, tipo_doc, descripcion_doc.strip(), st.session_state.usuario_actual)
                        st.success("✅ Registro guardado en la bitácora exitosamente.")
                        st.rerun()
                    else:
                        st.warning("Escriba una breve descripción.")
            
            with col_b2:
                st.markdown("### 📜 Historial de Documentos Emitidos")
                filtro_b_cedula = st.text_input("Filtrar historial por Cédula (opcional):")
                
                df_bitacora = cargar_bitacora(filtro_b_cedula.strip() if filtro_b_cedula else None)
                if not df_bitacora.empty:
                    st.dataframe(df_bitacora, use_container_width=True, hide_index=True)
                else:
                    st.info("No se han registrado documentos aún.")
        else:
            st.info("Debe registrar habitantes antes de emitir documentos.")

# -----------------------------------------------------------------------------
# TAB: EDITAR / ELIMINAR REGISTROS (Master, Administrador)
# -----------------------------------------------------------------------------
if ES_ADMIN_OR_MASTER and "⚙️ Editar / Eliminar" in pestañas:
    with tabs[pestañas.index("⚙️ Editar / Eliminar")]:
        st.subheader("Gestión de Habitantes")
        df_edit = cargar_habitantes()
        
        if not df_edit.empty:
            cedula_buscar = st.selectbox("Seleccione Cédula del habitante a modificar:", df_edit["cedula"].unique())
            hab = df_edit[df_edit["cedula"] == cedula_buscar].iloc[0]
            
            with st.form("form_edit"):
                col_e1, col_e2 = st.columns(2)
                with col_e1:
                    e_nombres = st.text_input("Nombres", value=hab['nombres'])
                    e_apellidos = st.text_input("Apellidos", value=hab['apellidos'])
                    
                    opciones_sexo = ["Femenino", "Masculino", "Otro"]
                    idx_sexo = opciones_sexo.index(hab['sexo']) if hab['sexo'] in opciones_sexo else 0
                    e_sexo = st.selectbox("Sexo", opciones_sexo, index=idx_sexo)
                    
                    e_telefono = st.text_input("Teléfono", value=hab['telefono'])
                with col_e2:
                    fn_dt = datetime.strptime(hab['fecha_nac'], "%Y-%m-%d").date()
                    fl_dt = datetime.strptime(hab['fecha_llegada'], "%Y-%m-%d").date()
                    
                    e_fn = st.date_input("Fecha Nacimiento", value=fn_dt)
                    e_fl = st.date_input("Fecha Llegada", value=fl_dt)
                    e_manzana = st.text_input("Manzana / Sector", value=hab['manzana'])
                    e_direccion = st.text_input("Dirección", value=hab['direccion'])
                    
                btn_mod = st.form_submit_button("💾 Actualizar Registro", use_container_width=True)
                
                if btn_mod:
                    datos_mod = (
                        cedula_buscar, e_nombres, e_apellidos, e_sexo,
                        e_fn.strftime("%Y-%m-%d"), e_fl.strftime("%Y-%m-%d"),
                        e_direccion, e_manzana, e_telefono
                    )
                    guardar_habitante(datos_mod)
                    st.success("✅ Registro actualizado.")
                    st.rerun()

            st.markdown("---")
            if st.button(f"🗑️ Eliminar a {hab['nombres']} {hab['apellidos']}", type="primary"):
                eliminar_habitante(cedula_buscar)
                st.warning("Habitante y su bitácora eliminados.")
                st.rerun()

# -----------------------------------------------------------------------------
# TAB: GESTIÓN DE USUARIOS (Solo Master)
# -----------------------------------------------------------------------------
if ES_MASTER and "👥 Gestión de Usuarios" in pestañas:
    with tabs[pestañas.index("👥 Gestión de Usuarios")]:
        st.subheader("Administración de Usuarios del Sistema")
        
        col_u1, col_u2 = st.columns([1, 2])
        
        with col_u1:
            st.markdown("### ➕ Crear o Modificar Usuario")
            with st.form("form_user"):
                u_user = st.text_input("Usuario (Username)")
                u_pass = st.text_input("Contraseña", type="password")
                u_name = st.text_input("Nombre Completo")
                u_rol = st.selectbox("Rol y Permisos", ["Visualizador", "Administrador", "Master"])
                
                btn_save_user = st.form_submit_button("Guardar Usuario", use_container_width=True)
                
                if btn_save_user:
                    if u_user.strip() and u_pass.strip():
                        guardar_usuario(u_user.strip(), u_pass.strip(), u_name.strip(), u_rol)
                        st.success(f"✅ Usuario `{u_user}` guardado correctamente.")
                        st.rerun()
                    else:
                        st.error("Ingrese usuario y contraseña.")
        
        with col_u2:
            st.markdown("### 📋 Usuarios Registrados")
            df_users = cargar_usuarios()
            st.dataframe(df_users, use_container_width=True, hide_index=True)
            
            st.markdown("---")
            u_del = st.selectbox("Seleccionar usuario a eliminar:", [u for u in df_users["username"] if u != "master"])
            if st.button("🗑️ Eliminar Usuario", type="primary"):
                eliminar_usuario(u_del)
                st.success("Usuario eliminado.")
                st.rerun()

# -----------------------------------------------------------------------------
# TAB: RESPALDOS E IMPORTACIÓN (Solo Master)
# -----------------------------------------------------------------------------
if ES_MASTER and "💾 Respaldos e Importación" in pestañas:
    with tabs[pestañas.index("💾 Respaldos e Importación")]:
        st.subheader("Gestión de Base de Datos y Carga Masiva")
        
        col_db1, col_db2 = st.columns(2)
        
        with col_db1:
            st.markdown("### 📤 Exportar / Descargar Datos")
            
            # Descargar archivo SQLite completo
            with open(DB_FILE, "rb") as f:
                bytes_db = f.read()
            st.download_button("💾 Descargar Base de Datos Completa (.db)", bytes_db, "censo_backup.db", "application/octet-stream")
            
            st.markdown("---")
            # Exportar datos de habitantes a CSV / Excel
            df_exp = cargar_habitantes()
            csv_exp = df_exp.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Descargar Censo Completo (CSV)", csv_exp, "habitantes.csv", "text/csv")
            
        with col_db2:
            st.markdown("### 📥 Importar Datos")
            
            # Subir y reemplazar Base de datos SQLite
            st.markdown("#### 1. Reemplazar Base de Datos (.db)")
            uploaded_db = st.file_uploader("Subir archivo .db", type=["db"])
            if uploaded_db is not None:
                if st.button("⚠️ Confirmar Reemplazo de BD"):
                    with open(DB_FILE, "wb") as f:
                        f.write(uploaded_db.getbuffer())
                    st.success("✅ Base de datos restaurada con éxito.")
                    st.rerun()
                    
            st.markdown("---")
            st.markdown("#### 2. Cargar Habitantes desde CSV")
            uploaded_csv = st.file_uploader("Subir CSV de habitantes", type=["csv"])
            if uploaded_csv is not None:
                if st.button("📥 Importar Habitantes desde CSV"):
                    try:
                        df_imp = pd.read_csv(uploaded_csv)
                        required_cols = ["cedula", "nombres", "apellidos", "sexo", "fecha_nac", "fecha_llegada", "direccion", "manzana", "telefono"]
                        
                        if all(col in df_imp.columns for col in required_cols):
                            for _, row in df_imp.iterrows():
                                guardar_habitante((
                                    str(row["cedula"]), str(row["nombres"]), str(row["apellidos"]),
                                    str(row["sexo"]), str(row["fecha_nac"]), str(row["fecha_llegada"]),
                                    str(row["direccion"]), str(row["manzana"]), str(row["telefono"])
                                ))
                            st.success("✅ Datos importados correctamente.")
                            st.rerun()
                        else:
                            st.error(f"El CSV debe contener las columnas: {required_cols}")
                    except Exception as e:
                        st.error(f"Error al leer el archivo: {e}")
