import os
import time
import logging
from flask import Flask, jsonify, request
from datadog import initialize, statsd
import psycopg2
from psycopg2.extras import RealDictCursor

# Datadog DogStatsD initialisation
initialize(statsd_host=os.getenv("DD_AGENT_HOST", "datadog-agent"),
           statsd_port=int(os.getenv("DD_DOGSTATSD_PORT", "8125")))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)
logger = logging.getLogger("ecommerce-api")


def _get_conn(role="reader"):
    """Return a psycopg2 connection.
    role='writer' -> primary DB  |  role='reader' -> read replica (falls back to primary)
    """
    if role == "writer":
        host = os.getenv("DB_WRITER_HOST", os.getenv("DB_HOST", "db"))
    else:
        host = os.getenv("DB_READER_HOST", os.getenv("DB_HOST", "db"))
    return psycopg2.connect(
        host=host,
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "ecommerce"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )


def _query(sql, params=None, role="reader"):
    """Execute a SELECT and return rows as list[dict].
    Sends the custom metric db.query.duration_ms to Datadog.
    """
    start = time.time()
    conn = _get_conn(role=role)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    duration_ms = (time.time() - start) * 1000
    # Custom Metric 2: db.query.duration_ms (TIMER / HISTOGRAM)
    statsd.timing("db.query.duration_ms", duration_ms)
    logger.info("query took %.2f ms  host=%s", duration_ms,
                os.getenv("DB_READER_HOST", os.getenv("DB_HOST", "db")))
    return rows


def _execute(sql, params=None):
    """Execute a write statement (INSERT/UPDATE/DELETE) on the primary."""
    start = time.time()
    conn = _get_conn(role="writer")
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()
    finally:
        conn.close()
    duration_ms = (time.time() - start) * 1000
    statsd.timing("db.query.duration_ms", duration_ms)


def create_app():
    app = Flask(__name__)

    @app.route("/health", methods=["GET"])
    def health():
        """Health-check endpoint used by Docker HEALTHCHECK."""
        try:
            _query("SELECT 1")
            return jsonify({"status": "healthy"}), 200
        except Exception as exc:
            logger.error("health check failed: %s", exc)
            return jsonify({"status": "unhealthy", "error": str(exc)}), 503

    @app.route("/products", methods=["GET"])
    def list_products():
        """Return all products (routed to read replica)."""
        # Custom Metric 1: products.requests.total (COUNTER)
        statsd.increment("products.requests.total")
        products = _query("SELECT * FROM products ORDER BY id")
        return jsonify(products), 200

    @app.route("/products/<int:product_id>", methods=["GET"])
    def get_product(product_id):
        """Return a single product by ID (routed to read replica)."""
        statsd.increment("products.requests.total")
        rows = _query("SELECT * FROM products WHERE id = %s", (product_id,))
        if not rows:
            return jsonify({"error": "Product not found"}), 404
        return jsonify(rows[0]), 200

    @app.route("/orders", methods=["POST"])
    def create_order():
        """Simulate creating an order (routed to primary / writer)."""
        data = request.get_json(force=True)
        product_id = data.get("product_id")
        quantity = data.get("quantity", 1)
        if not product_id:
            return jsonify({"error": "product_id is required"}), 400
        _execute(
            "INSERT INTO orders (product_id, quantity) VALUES (%s, %s)",
            (product_id, quantity),
        )
        statsd.increment("orders.created.total")
        return jsonify({"message": "Order created"}), 201

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("APP_PORT", "8080")))
