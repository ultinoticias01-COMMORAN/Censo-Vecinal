import streamlit as st
import pandas as pd
from datetime import datetime

# Configuración de la página web
st.set_page_config(page_title="Censo Comunitario", page_icon="🏡", layout="wide")

# Inicializar el estado de la sesión para guardar los registros en memoria
if "censo_data" not in st.session_state:
    st.session_state.censo_data = []

# Funciones de cálculo
def calcular_edad(fecha_nac):
    hoy = datetime.now().date()
    edad = hoy.year - fecha_nac.year - ((hoy.month, hoy.day) < (fecha_nac.month, fecha_nac.day))
    return edad

def calcular_tiempo_comunidad(fecha_llegada):
    hoy = datetime.now().date()
    años = hoy.year - fecha_llegada.year
    meses = hoy.month - fecha_llegada.month
    if hoy.day < fecha_llegada.day:
        meses -= 1
    if meses < 0:
        años -= 1
        meses += 12
    return f"{años} yrs, {meses} meses"

# Título Principal
st.title("🏡 Censo de la Comunidad")
st.markdown("Registro y control de habitantes")

# Pestañas para organizar la interfaz
tab1, tab2 = st.tabs(["📝 Registrar Habitante", "📊 Consultar Censo"])

with tab1:
    st.subheader("Datos del Habitante")
    
    with st.form("form_censo", clear_on_submit=True):
        col1, col2 = st.columns(2)
        
        with col1:
            nombres = st.text_input("Nombres")
            apellidos = st.text_input("Apellidos")
            cedula = st.text_input("Cédula de Identidad")
            telefono = st.text_input("Teléfono")
            
        with col2:
            fecha_nac = st.date_input("Fecha de Nacimiento", min_value=datetime(1920, 1, 1))
            fecha_llegada = st.date_input("Fecha de Llegada a la Comunidad", min_value=datetime(1950, 1, 1))
            direccion = st.text_input("Dirección de Habitación")
            manzana = st.text_input("Manzana / Sector")

        guardar = st.form_submit_button("Guardar Registro")

    if guardar:
        if nombres and apellidos and cedula:
            edad = calcular_edad(fecha_nac)
            tiempo_comunidad = calcular_tiempo_comunidad(fecha_llegada)
            
            # Formatear registro (variable 'telefono' corregida sin tilde)
            nuevo_registro = {
                "Cédula": cedula,
                "Nombres": nombres,
                "Apellidos": apellidos,
                "Edad": edad,
                "F. Nacimiento": fecha_nac.strftime("%d/%m/%Y"),
                "F. Llegada": fecha_llegada.strftime("%d/%m/%Y"),
                "Tiempo en Comunidad": tiempo_comunidad,
                "Manzana": manzana,
                "Dirección": direccion,
                "Teléfono": telefono
            }
            
            st.session_state.censo_data.append(nuevo_registro)
            st.success(f"✅ ¡{nombres} {apellidos} ha sido registrado exitosamente!")
        else:
            st.error("⚠️ Por favor completa al menos los campos de Nombre, Apellido y Cédula.")

with tab2:
    st.subheader("Registros Actuales")
    
    if st.session_state.censo_data:
        df = pd.DataFrame(st.session_state.censo_data)
        
        # Muestra métricas rápidas arriba
        col_m1, col_m2 = st.columns(2)
        col_m1.metric("Total Registrados", len(df))
        col_m2.metric("Promedio de Edad", f"{df['Edad'].mean():.1f} años")
        
        # Tabla interactiva
        st.dataframe(df, use_container_width=True)
        
        # Opción para descargar los datos en Excel/CSV
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Descargar Censo (CSV)",
            data=csv,
            file_name="censo_comunidad.csv",
            mime="text/csv",
        )
    else:
        st.info("No hay habitantes registrados aún.")