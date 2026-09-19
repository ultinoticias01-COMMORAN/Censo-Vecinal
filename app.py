import sqlite3
import streamlit as st
import pandas as pd
from datetime import datetime

# -----------------------------------------------------------------------------
# 1. CONFIGURACIÓN DE LA PÁGINA
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Censo Comunitario", page_icon="🏡", layout="wide")

# -----------------------------------------------------------------------------
# 2. BASE DE DATOS (SQLite)
# -----------------------------------------------------------------------------
def init_db():
    conn = sqlite3.connect("censo.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS habitantes (
            cedula TEXT PRIMARY KEY,
            nombres TEXT,
            apellidos TEXT,
            fecha_nac TEXT,
            fecha_llegada TEXT,
            direccion TEXT,
            manzana TEXT,
            telefono TEXT
        )
    """)
    conn.commit()
    conn.close()

def cargar_datos():
    conn = sqlite3.connect("censo.db")
    df = pd.read_sql_query("SELECT * FROM habitantes", conn)
    conn.close()
    return df

def guardar_habitante(datos):
    conn = sqlite3.connect("censo.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO habitantes (cedula, nombres, apellidos, fecha_nac, fecha_llegada, direccion, manzana, telefono)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, datos)
    conn.commit()
    conn.close()

def eliminar_habitante(cedula):
    conn = sqlite3.connect("censo.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM habitantes WHERE cedula = ?", (cedula,))
    conn.commit()
    conn.close()

# Inicializar base de datos
init_db()

# -----------------------------------------------------------------------------
# 3. FUNCIONES AUXILIARES Y DE CÁLCULO
# -----------------------------------------------------------------------------
def calcular_edad(fecha_nac_str):
    fecha_nac = datetime.strptime(fecha_nac_str, "%Y-%m-%d").date()
    hoy = datetime.now().date()
    return hoy.year - fecha_nac.year - ((hoy.month, hoy.day) < (fecha_nac.month, fecha_nac.day))

def calcular_tiempo_comunidad(fecha_llegada_str):
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

# -----------------------------------------------------------------------------
# 4. MÓDULO DE BLOQUEO Y AUTENTICACIÓN
# -----------------------------------------------------------------------------
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

def autenticar():
    # Puedes definir aquí tus credenciales de acceso
    USUARIO_ADMIN = "admin"
    CLAVE_ADMIN = "censo2026"

    if not st.session_state.autenticado:
        st.markdown("<h1 style='text-align: center;'>🔒 Control de Acceso - Censo Comunitario</h1>", unsafe_allow_html=True)
        
        col_center1, col_center2, col_center3 = st.columns([1, 2, 1])
        with col_center2:
            with st.form("form_login"):
                usuario = st.text_input("Usuario")
                clave = st.text_input("Contraseña", type="password")
                btn_login = st.form_submit_button("Ingresar al Sistema", use_container_width=True)
                
                if btn_login:
                    if usuario == USUARIO_ADMIN and clave == CLAVE_ADMIN:
                        st.session_state.autenticado = True
                        st.success("¡Acceso correcto!")
                        st.rerun()
                    else:
                        st.error("❌ Usuario o contraseña incorrectos.")
        return False
    return True

# Detener ejecución si el usuario no ha iniciado sesión
if not autenticar():
    st.stop()

# -----------------------------------------------------------------------------
# 5. APLICACIÓN PRINCIPAL (DESBLOQUEADA)
# -----------------------------------------------------------------------------

# Barra lateral / Menú de sesión
with st.sidebar:
    st.title("👤 Usuario Activo")
    st.info("Rol: **Administrador**")
    if st.button("🚪 Cerrar Sesión", use_container_width=True):
        st.session_state.autenticado = False
        st.rerun()

st.title("🏡 Censo Digital de la Comunidad")
st.markdown("Sistema de registro, consulta y control de residentes.")

# Pestañas principales
tab1, tab2, tab3 = st.tabs(["📝 Registrar Habitante", "📊 Consultar Censo", "⚙️ Gestionar / Editar"])

# -----------------------------------------------------------------------------
# TAB 1: REGISTRAR HABITANTE
# -----------------------------------------------------------------------------
with tab1:
    st.subheader("Formulario de Registro")
    
    with st.form("form_censo", clear_on_submit=True):
        col1, col2 = st.columns(2)
        
        with col1:
            nombres = st.text_input("Nombres*")
            apellidos = st.text_input("Apellidos*")
            cedula = st.text_input("Cédula de Identidad*")
            telefono = st.text_input("Teléfono de Contacto")
            
        with col2:
            fecha_nac = st.date_input("Fecha de Nacimiento", min_value=datetime(1920, 1, 1), max_value=datetime.now())
            fecha_llegada = st.date_input("Fecha de Llegada a la Comunidad", min_value=datetime(1950, 1, 1), max_value=datetime.now())
            manzana = st.text_input("Manzana / Sector")
            direccion = st.text_input("Dirección de Habitación")

        guardar = st.form_submit_button("Guardar Registro", use_container_width=True)

    if guardar:
        cedula_clean = cedula.strip()
        nombres_clean = nombres.strip()
        apellidos_clean = apellidos.strip()

        if nombres_clean and apellidos_clean and cedula_clean:
            datos_registro = (
                cedula_clean,
                nombres_clean,
                apellidos_clean,
                fecha_nac.strftime("%Y-%m-%d"),
                fecha_llegada.strftime("%Y-%m-%d"),
                direccion.strip(),
                manzana.strip(),
                telefono.strip()
            )
            
            try:
                guardar_habitante(datos_registro)
                st.success(f"✅ ¡Habitante **{nombres_clean} {apellidos_clean}** registrado exitosamente en la base de datos!")
            except Exception as e:
                st.error(f"⚠️ Error al guardar en la base de datos: {e}")
        else:
            st.warning("⚠️ Por favor completa los campos obligatorios (*): Nombres, Apellidos y Cédula.")

# -----------------------------------------------------------------------------
# TAB 2: CONSULTAR CENSO
# -----------------------------------------------------------------------------
with tab2:
    st.subheader("Registros y Estadísticas")
    
    df = cargar_datos()
    
    if not df.empty:
        # Calcular columnas derivadas para el reporte
        df["Edad"] = df["fecha_nac"].apply(calcular_edad)
        df["Tiempo Comunidad"] = df["fecha_llegada"].apply(calcular_tiempo_comunidad)
        
        # Filtros de Búsqueda
        st.markdown("##### 🔍 Filtros de Búsqueda")
        col_f1, col_f2 = st.columns(2)
        
        with col_f1:
            busqueda = st.text_input("Buscar por Nombre, Apellido o Cédula", "")
        with col_f2:
            sectores = ["Todos"] + list(df["manzana"].unique())
            sector_sel = st.selectbox("Filtrar por Manzana / Sector", sectores)
        
        # Aplicar filtros
        df_filtrado = df.copy()
        if busqueda:
            df_filtrado = df_filtrado[
                df_filtrado["nombres"].str.contains(busqueda, case=False, na=False) |
                df_filtrado["apellidos"].str.contains(busqueda, case=False, na=False) |
                df_filtrado["cedula"].str.contains(busqueda, case=False, na=False)
            ]
        if sector_sel != "Todos":
            df_filtrado = df_filtrado[df_filtrado["manzana"] == sector_sel]

        # Métricas principales
        st.markdown("---")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Habitantes", len(df_filtrado))
        m2.metric("Promedio de Edad", f"{df_filtrado['Edad'].mean():.1f} años" if len(df_filtrado) > 0 else "N/A")
        m3.metric("Mayores de Edad (≥18)", len(df_filtrado[df_filtrado["Edad"] >= 18]))
        m4.metric("Menores de Edad (<18)", len(df_filtrado[df_filtrado["Edad"] < 18]))
        st.markdown("---")

        # Renombrar columnas para visualización clara
        df_vista = df_filtrado[[
            "cedula", "nombres", "apellidos", "Edad", 
            "fecha_nac", "fecha_llegada", "Tiempo Comunidad", 
            "manzana", "direccion", "telefono"
        ]].rename(columns={
            "cedula": "Cédula",
            "nombres": "Nombres",
            "apellidos": "Apellidos",
            "fecha_nac": "F. Nacimiento",
            "fecha_llegada": "F. Llegada",
            "manzana": "Sector / Manzana",
            "direccion": "Dirección",
            "telefono": "Teléfono"
        })

        st.dataframe(df_vista, use_container_width=True, hide_index=True)

        # Descarga de datos
        csv = df_vista.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Descargar Reporte Completo (CSV)",
            data=csv,
            file_name=f"censo_comunidad_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )
    else:
        st.info("💡 Aún no existen datos registrados en el censo.")

# -----------------------------------------------------------------------------
# TAB 3: GESTIONAR / EDITAR REGISTROS
# -----------------------------------------------------------------------------
with tab3:
    st.subheader("Editar o Eliminar Registro")
    
    df_gestion = cargar_datos()
    if not df_gestion.empty:
        cedula_buscar = st.selectbox("Selecciona un habitante por Cédula:", df_gestion["cedula"].unique())
        
        habitante = df_gestion[df_gestion["cedula"] == cedula_buscar].iloc[0]
        
        with st.form("form_editar"):
            st.markdown(f"**Modificando datos de:** {habitante['nombres']} {habitante['apellidos']}")
            col_e1, col_e2 = st.columns(2)
            
            with col_e1:
                edit_nombres = st.text_input("Nombres", value=habitante['nombres'])
                edit_apellidos = st.text_input("Apellidos", value=habitante['apellidos'])
                edit_telefono = st.text_input("Teléfono", value=habitante['telefono'])
                
            with col_e2:
                fn_dt = datetime.strptime(habitante['fecha_nac'], "%Y-%m-%d").date()
                fl_dt = datetime.strptime(habitante['fecha_llegada'], "%Y-%m-%d").date()
                
                edit_fn = st.date_input("Fecha de Nacimiento", value=fn_dt)
                edit_fl = st.date_input("Fecha de Llegada", value=fl_dt)
                edit_manzana = st.text_input("Manzana / Sector", value=habitante['manzana'])
                edit_direccion = st.text_input("Dirección", value=habitante['direccion'])
            
            btn_actualizar = st.form_submit_button("💾 Guardar Cambios", use_container_width=True)
            
            if btn_actualizar:
                datos_editados = (
                    cedula_buscar,
                    edit_nombres,
                    edit_apellidos,
                    edit_fn.strftime("%Y-%m-%d"),
                    edit_fl.strftime("%Y-%m-%d"),
                    edit_direccion,
                    edit_manzana,
                    edit_telefono
                )
                guardar_habitante(datos_editados)
                st.success("✅ Registro actualizado correctamente.")
                st.rerun()

        st.markdown("---")
        st.subheader("⚠️ Zona de Peligro")
        if st.button(f"🗑️ Eliminar a {habitante['nombres']} {habitante['apellidos']}", type="primary"):
            eliminar_habitante(cedula_buscar)
            st.warning("Registro eliminado exitosamente.")
            st.rerun()
    else:
        st.info("No hay datos disponibles para editar.")
