import os
import time
import logging
from contextlib import contextmanager
from flask import Flask, jsonify, request
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from datadog import initialize, statsd

# ── Datadog DogStatsD initialization ──────────────────────────
initialize(
    statsd_host=os.getenv("DD_AGENT_HOST", "datadog-agent"),
    statsd_port=int(os.getenv("DD_DOGSTATSD_PORT", "8125"))
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)
logger = logging.getLogger("ecommerce-api")

# ── Thread-Safe Connection Pools ──────────────────────────────
writer_pool = None
reader_pool = None


def get_db_config(host):
    return {
        "host": host,
        "port": int(os.getenv("DB_PORT", "5432")),
        "dbname": os.getenv("DB_NAME", "ecommerce"),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", "postgres"),
        "connect_timeout": 5,
    }


def init_pools():
    global writer_pool, reader_pool
    writer_host = os.getenv("DB_WRITER_HOST", os.getenv("DB_HOST", "db"))
    reader_host = os.getenv("DB_READER_HOST", os.getenv("DB_HOST", "db"))

    logger.info("Initializing connection pools. Writer: %s, Reader: %s", writer_host, reader_host)
    try:
        writer_pool = pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=20,
            **get_db_config(writer_host)
        )
    except Exception as exc:
        logger.error("Failed to initialize writer pool on %s: %s", writer_host, exc)
        raise

    try:
        reader_pool = pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=30,
            **get_db_config(reader_host)
        )
    except Exception as exc:
        logger.warning("Failed to initialize reader pool on %s: %s. Falling back to writer pool.", reader_host, exc)
        reader_pool = writer_pool


@contextmanager
def get_db_connection(role="reader"):
    selected_pool = reader_pool if role == "reader" and reader_pool else writer_pool
    if selected_pool is None:
        raise RuntimeError("Database connection pool is not initialized.")

    conn = selected_pool.getconn()
    try:
        yield conn
    finally:
        selected_pool.putconn(conn)


def _query(sql, params=None, role="reader"):
    """Execute a read query and record execution time in Datadog."""
    start = time.perf_counter()
    try:
        with get_db_connection(role=role) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]
    finally:
        duration_ms = (time.perf_counter() - start) * 1000.0
        # Custom Metric: db.query.duration_ms (TIMER / HISTOGRAM)
        statsd.timing("db.query.duration_ms", duration_ms, tags=[f"role:{role}"])
        logger.debug("Query completed in %.2f ms (role=%s)", duration_ms, role)


def _execute(sql, params=None):
    """Execute a write statement (INSERT/UPDATE/DELETE) on the primary database."""
    start = time.perf_counter()
    try:
        with get_db_connection(role="writer") as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                conn.commit()
    finally:
        duration_ms = (time.perf_counter() - start) * 1000.0
        # Custom Metric: db.query.duration_ms (TIMER / HISTOGRAM)
        statsd.timing("db.query.duration_ms", duration_ms, tags=["role:writer"])
        logger.debug("Write query completed in %.2f ms", duration_ms)


# ── Application Factory ───────────────────────────────────────
def create_app():
    app = Flask(__name__)

    try:
        init_pools()
    except Exception as exc:
        logger.error("Initial database pool setup failed (will retry on health checks): %s", exc)

    @app.route("/health", methods=["GET"])
    def health():
        """Health-check endpoint utilized by Docker healthchecks."""
        try:
            global writer_pool, reader_pool
            if writer_pool is None or reader_pool is None:
                init_pools()
            _query("SELECT 1", role="reader")
            return jsonify({"status": "healthy", "pools": "active"}), 200
        except Exception as exc:
            logger.error("Health check failure: %s", exc)
            return jsonify({"status": "unhealthy", "error": str(exc)}), 503

    @app.route("/products", methods=["GET"])
    def list_products():
        """Fetch all catalog products routed to the read replica."""
        # Custom Metric: products.requests.total (COUNTER)
        statsd.increment("products.requests.total")
        products = _query("SELECT * FROM products ORDER BY id ASC", role="reader")
        return jsonify(products), 200

    @app.route("/products/<int:product_id>", methods=["GET"])
    def get_product(product_id):
        """Fetch a single product by ID routed to the read replica."""
        # Custom Metric: products.requests.total (COUNTER)
        statsd.increment("products.requests.total")
        rows = _query("SELECT * FROM products WHERE id = %s", (product_id,), role="reader")
        if not rows:
            return jsonify({"error": "Product not found"}), 404
        return jsonify(rows[0]), 200

    @app.route("/orders", methods=["POST"])
    def create_order():
        """Submit a new order routed to the primary database."""
        data = request.get_json(silent=True)
        if not data or "product_id" not in data:
            return jsonify({"error": "Malformed request: 'product_id' is required"}), 400

        product_id = data["product_id"]
        quantity = data.get("quantity", 1)

        _execute(
            "INSERT INTO orders (product_id, quantity) VALUES (%s, %s)",
            (product_id, quantity),
        )
        statsd.increment("orders.created.total")
        return jsonify({"message": "Order created successfully"}), 201

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("APP_PORT", "8080")))
