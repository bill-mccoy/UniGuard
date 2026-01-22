<div align="center">
  <h1>✨ UniGuard</h1>
  <p>Plataforma de verificación académica y gestión de comunidades digitales</p>
  <p>
    <img src="https://img.shields.io/github/stars/bill-mccoy/UniGuard?style=social" alt="GitHub stars">
    <img src="https://img.shields.io/github/license/bill-mccoy/UniGuard" alt="License">
  </p>
</div>

---

## 📌 ¿Qué es UniGuard?

**UniGuard** es una plataforma integrada diseñada para facilitar la **verificación de identidad académica** y la **gestión de comunidades digitales**, conectando **Discord** con **Minecraft** y garantizando que solo usuarios con **correos institucionales válidos** puedan acceder.

Está pensada para contextos académicos, comunidades educativas y proyectos institucionales que requieren control de acceso confiable en entornos digitales.

---

## 💡 Características principales

### 🔐 Verificación de identidad
- Validación automática de correos institucionales.
- Generación de códigos únicos con expiración.
- Protección contra accesos no autorizados.

### 🎛️ Integración con Discord
- Asignación automática de roles (verificado / no verificado).
- Flujos de interacción mediante botones y menús.
- Herramientas administrativas para gestión de usuarios.

### 🎮 Integración con Minecraft
- Registro centralizado de nombres de usuario Minecraft.
- Integración directa con **Noble Whitelist**.
- Sincronización automática de la whitelist desde la base de datos.
- Gestión unificada de permisos entre plataformas.

### 📊 Gestión administrativa
- Base de datos centralizada de usuarios verificados.
- Registro de eventos de autenticación.
- Dashboard web administrativo (en desarrollo).

---

## 🧰 Requisitos técnicos

| Componente | Versión mínima | Uso |
|-----------|---------------|-----|
| Python | 3.9+ | Lenguaje principal |
| MySQL | 8.0+ | Almacenamiento persistente |
| Discord Server | — | Comunidad con permisos de administrador |
| Mailjet | Cuenta activa | Envío de correos |
| Noble Whitelist | Última versión | Gestión de whitelist en Minecraft |

---

## 🚀 Instalación y configuración

1. Clonar el repositorio:
```bash
git clone https://github.com/bill-mccoy/UniGuard.git
cd UniGuard
```

2. Instalar dependencias:
```bash
pip install -r requirements.txt
```

3. Configurar variables de entorno:
```bash
cp .env.example .env
```
Editar el archivo `.env` con las credenciales correspondientes (base de datos, Discord, Mailjet y Noble Whitelist).

4. Iniciar el sistema:
```bash
python bot.py
```

---

## 🧩 Casos de uso

- Comunidades privadas en Discord con acceso verificado.
- Servidores de Minecraft académicos con whitelist automática.
- Eventos virtuales interdisciplinarios.
- Proyectos colaborativos con acceso controlado.
- Espacios de tutoría y asesoría académica.

---

## 🎯 Beneficios institucionales

- Seguridad mejorada y control de acceso.
- Procesos de verificación automatizados.
- Reducción de carga administrativa.
- Integración real entre Discord y Minecraft.
- Arquitectura escalable y adaptable.

---

## 🤝 Contribuciones

Las contribuciones son bienvenidas mediante:
- Reportes de errores (Issues).
- Solicitudes de nuevas funcionalidades.
- Pull Requests con mejoras documentadas.

---

## 📄 Licencia

Este proyecto se distribuye bajo licencia **MIT**.  
Consulta el archivo `LICENSE` para más información.

---

✨ *UniGuard — Transformando comunidades académicas con espacios digitales seguros e integrados.*

---

## 🛠️ Desarrollo

- Instala dependencias de desarrollo:

```bash
pip install -r requirements.txt -r dev-requirements.txt
```

- Ejecuta tests unitarios:

```bash
make test
```

- Ejecuta tests de integración localmente (requiere Docker):

```bash
make test-integration
# o
RUN_DB_INTEGRATION=1 pytest -q tests/integration
```

- Instrucciones completas para pruebas de integración: `contrib/README_DB_TESTS.md`
