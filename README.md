# DDB Sucursales — Procesador de Datos (DP) y de Transacciones (TP)

Aplicación de escritorio (Python + Tkinter) para un sistema de base de datos
distribuida por sucursales sobre MySQL/MariaDB, construida sobre el esquema de
[sql/create_databases.sql](sql/create_databases.sql).

## Requisitos e instalación

- Python 3.10 o superior (incluye Tkinter en Windows).
- MySQL 8 o MariaDB 10.5 o superior, con soporte de transacciones XA (activado por omisión).

```bash
pip install -r requirements.txt
```

1. Crea las bases de datos con el script:
   `mysql -u root -p < sql/create_databases.sql`
2. (Opcional) Copia `config.example.ini` como `config.ini` y ajusta el servidor del catálogo.
3. Ejecuta la aplicación:

```bash
python main.py
```

Al iniciar, la aplicación pide los datos de conexión al **catálogo global**
(`ddb_catalog`). Las direcciones de los nodos se leen de la tabla `Nodes`.

> El usuario debe autenticarse con contraseña (`mysql_native_password`, `caching_sha2_password`
> o `ed25519`). PyMySQL no admite la autenticación `gssapi` que MariaDB usa por omisión para
> `root` en Windows. Si es tu caso, crea un usuario con contraseña para la aplicación.

## Arquitectura

```
Interfaz gráfica (ddb/gui)
        │  peticiones de alto nivel: "insertar cliente", "buscar por RFC"…
        ▼
DP — Procesador de Datos (ddb/dp.py)
   • consulta el catálogo global para saber qué nodos y fragmentos existen
   • enruta cada inserción al nodo correcto
   • divide las consultas globales en subconsultas paralelas y une los resultados
   • poda de fragmentos cuando el filtro determina un solo nodo
        │  escrituras
        ▼
TP — Procesador de Transacciones (ddb/tp.py)
   • commit en dos fases (2PC) con transacciones XA en cada nodo participante
   • optimización de una fase cuando participa un solo nodo
        │
        ▼
Nodos: ddb_morelia, ddb_patzcuaro, …     Catálogo global: ddb_catalog
```

| Archivo | Responsabilidad |
|---|---|
| `ddb/catalog.py` | Catálogo global: nodos, tablas distribuidas, fragmentos y predicados |
| `ddb/dp.py` | Procesador de datos: localización, enrutamiento, búsquedas y DDL distribuido |
| `ddb/tp.py` | Procesador de transacciones: 2PC con XA (`PREPARE` / `COMMIT` / `ROLLBACK`) |
| `ddb/validation.py` | Validación de RFC, código postal y longitudes |
| `ddb/gui/` | Ventana principal y pestañas (Clientes, Tablas distribuidas, Nodos, Bitácora) |

### Metadatos que agrega la aplicación al catálogo

Al conectarse por primera vez, la aplicación crea (si no existen) estas tablas en `ddb_catalog`,
sin modificar `Nodes`:

- `DistributedTables`: esquema global de cada tabla distribuida y su estrategia de fragmentación.
- `Fragments`: el fragmento de cada tabla en cada nodo y su **predicado** (lista de valores o rango).
- `NodeAuth`: credenciales opcionales de un nodo que use un usuario distinto al del catálogo.

`Clients` y `Addresses` se registran como tablas del sistema con fragmentación por sucursal.

### Identificadores globales

Cada nodo tiene su propio rango de Ids (`Id del nodo × 1 000 000 + 1`), igual que en el script:
Morelia usa 1000001…, Pátzcuaro 2000001…, y un tercer nodo usará 3000001…. Así las llaves
primarias son únicas en todo el sistema sin necesidad de coordinar los nodos.

## Funcionalidad

| Requisito | Dónde |
|---|---|
| a. Interfaz gráfica | `python main.py` |
| b. Insertar clientes y direcciones en la BD de su sucursal | Clientes → *Nuevo cliente* (con domicilio opcional) y *Nueva dirección*. El DP enruta el registro a la sucursal elegida, y la dirección siempre va a la sucursal de su cliente. El RFC se verifica como único **en todas** las sucursales. |
| c. Actualizar clientes y direcciones | *Editar cliente* / *Editar dirección* (o doble clic). Si se cambia la sucursal de un cliente, se migra con sus direcciones en una transacción distribuida (2PC): se borra en el origen y se inserta en el destino de forma atómica. |
| d. Búsquedas por nombre, RFC o domicilio desde cualquier sucursal | Barra de búsqueda. La *Sucursal actual* indica desde dónde se lanza la consulta. El ámbito puede ser todas las sucursales o una sola. *Listar todos* muestra todos los clientes. Si un nodo no responde, se muestran resultados parciales con aviso. |
| e. Tablas distribuidas con fragmentación horizontal transparente | Tablas distribuidas → *Nueva tabla*. Se define el esquema una sola vez, y el sistema crea un fragmento en cada nodo. Estrategias: **por sucursal**, **por lista de valores** o **por rango**. Al insertar, el DP evalúa los predicados y ubica la fila. Las consultas muestran la unión de todos los fragmentos. Si al editar una fila cambia su valor de fragmentación, la fila se mueve de nodo con 2PC. |
| f. Agregar nodos | Nodos → *Agregar nodo*. Crea la BD del nuevo nodo con `Clients` y `Addresses` (con su rango de Ids) y los fragmentos de todas las tablas distribuidas (pide el predicado del nuevo nodo en las tablas por lista o rango), y lo registra en el catálogo. Si algo falla, se elimina la BD creada (compensación). |

La pestaña **Bitácora DP / TP** muestra en tiempo real qué hace cada procesador: los nodos
consultados (local o remoto), la poda de fragmentos, el enrutamiento de las inserciones y las
fases del 2PC (`XA START`, `PREPARE`/voto, `COMMIT` o `ROLLBACK`).

## Notas y limitaciones

- El DDL (`CREATE TABLE`, `CREATE DATABASE`) no es transaccional en MySQL. Por eso la creación
  de tablas y nodos usa **compensación**: si falla un nodo, se eliminan los fragmentos ya creados.
  También exige que todos los nodos estén en línea.
- La unicidad global del RFC se verifica antes de la transacción. Dos altas simultáneas con el
  mismo RFC en sucursales distintas podrían pasar la verificación al mismo tiempo.
- Si un nodo falla **después** de votar SÍ (fase 2), su rama queda preparada. Puede consultarse
  con `XA RECOVER` y confirmarse con `XA COMMIT 'gtrid','bqual'`.
- Las contraseñas de `NodeAuth` se guardan en texto plano en el catálogo (proyecto académico).
