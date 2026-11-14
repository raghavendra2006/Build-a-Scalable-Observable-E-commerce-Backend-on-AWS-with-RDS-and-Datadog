# Scalable & Observable E-Commerce Backend on AWS with RDS & Datadog

[![AWS](https://img.shields.io/badge/AWS-RDS%20PostgreSQL-232F3E?logo=amazon-aws&logoColor=white)](https://aws.amazon.com/rds/)
[![Datadog](https://img.shields.io/badge/Datadog-APM%20%7C%20Logs%20%7C%20Metrics-632CA6?logo=datadog&logoColor=white)](https://www.datadoghq.com/)
[![Terraform](https://img.shields.io/badge/Terraform-1.5+-844FBA?logo=terraform&logoColor=white)](https://www.terraform.io/)
[![Docker](https://img.shields.io/badge/Docker-Compose%20v2-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![Python](https://img.shields.io/badge/Python-3.12%20Flask-3776AB?logo=python&logoColor=white)](https://flask.palletsprojects.com/)

An enterprise-grade e-commerce API backend designed to maintain performance, stability, and end-to-end observability during high-concurrency traffic surges (e.g., flash sales). Built with Python (Flask, Gunicorn `gthread`), backed by a decoupled AWS RDS PostgreSQL primary/read-replica architecture, and instrumented across all tiers with Datadog.

---

## Table of Contents

- [System Architecture](#system-architecture)
- [Key Engineering Decisions](#key-engineering-decisions)
- [Repository Structure](#repository-structure)
- [Local Development & Testing](#local-development--testing)
- [Cloud Infrastructure Deployment (Terraform)](#cloud-infrastructure-deployment-terraform)
- [Observability & Telemetry](#observability--telemetry)
- [API Reference](#api-reference)
- [Operational Runbook & Disaster Recovery](#operational-runbook--disaster-recovery)
- [License](#license)

---

## System Architecture

The architecture isolates read-intensive traffic from transactional writes to prevent database lock contention and connection saturation:

```
                            [ Client Traffic / Load Generators ]
                                             │
                                             ▼
                                  [ Application Layer ]
                              Gunicorn WSGI (gthread pool)
                                Flask API (Python 3.12)
                             ┌───────────────┴───────────────┐
                             │  Threaded Connection Pools    │
                             │  (Max 30 Reader / 20 Writer)  │
                             └───────┬───────────────┬───────┘
                                     │               │
            Read Queries (GET /products)             │ Write Queries (POST /orders)
                                     │               │
                                     ▼               ▼
                       ┌──────────────────────┐  ┌──────────────────────┐
                       │   RDS Read Replica   │  │   RDS Primary DB     │
                       │   (db.t3.micro)      │◄─┼─  (db.t3.micro)      │
                       │   Private Subnet B   │  │   Private Subnet A   │
                       └──────────┬───────────┘  └──────────┬───────────┘
                                  │   Asynchronous Streaming│
                                  │        Replication      │
                                  └────────────┬────────────┘
                                               │ CloudWatch Telemetry
                                               ▼
                                      [ Datadog Agent ]
                                   APM Traces · Logs · StatsD
                                               │
                                               ▼
                                     [ Datadog Platform ]
                                   Dashboards · Metric Alerts
```

### Network Topology & Isolation

```
VPC (10.0.0.0/16)
├── Public Subnet (10.0.1.0/24 - AZ 1)
│   ├── Internet Gateway (0.0.0.0/0 route)
│   └── App Security Group (Inbound: TCP 8080 from 0.0.0.0/0)
│
└── Private Subnets (No IGW Route - Isolated)
    ├── Subnet A (10.0.10.0/24 - AZ 1) ── RDS Primary
    ├── Subnet B (10.0.11.0/24 - AZ 2) ── RDS Read Replica
    └── RDS Security Group (Inbound: TCP 5432 strictly from App SG ID)
```

---

## Key Engineering Decisions

1. **Thread-Safe Connection Pooling vs. Connection Churn:**  
   Opening raw database connections on every request consumes excessive memory and exhausts PostgreSQL's `max_connections` (typically ~80-100 on burstable instances). We implemented `psycopg2.pool.ThreadedConnectionPool` for both reader and writer instances with fallback logic, slashing request latency by eliminating repeated TCP/TLS handshakes.
2. **Concurrency Tuning via Gunicorn `gthread`:**  
   Standard synchronous workers block the entire process during database I/O. We configured Gunicorn with 3 worker processes and 4 threads each (`gthread`), providing 12 concurrent execution contexts capable of overlapping network I/O.
3. **Hardened Multi-Stage Container:**  
   The `Dockerfile` uses a two-stage build: a build environment compiles binary C extensions (`gcc`, `libpq-dev`), and a slim runtime stage retains only runtime libraries (`libpq5`). The application executes under an unprivileged user (`appuser`, UID `1001`).
4. **Defense-in-Depth Security Groups:**  
   The database security group accepts ingress on port `5432` *exclusively* from the security group ID of the application tier (`aws_security_group.app.id`). Direct IP-based ingress is blocked, preventing unauthorized internal or external lateral movement.

---

## Repository Structure

```
.
├── app/
│   ├── __init__.py
│   ├── main.py                 # Core Flask application, connection pools, custom metrics
│   └── wsgi.py                 # WSGI entrypoint for Gunicorn
├── datadog/
│   ├── dashboard.json          # Exported Datadog dashboard (7 core widgets)
│   └── monitor.json            # Metric alert definition (Primary CPU > 80% over 5m)
├── infra/
│   ├── outputs.tf              # RDS endpoints, VPC ID, security group references
│   ├── providers.tf            # HashiCorp AWS provider configuration
│   ├── rds.tf                  # RDS Primary and Read Replica definitions
│   ├── security_groups.tf      # App and RDS security groups (least privilege)
│   ├── terraform.tfvars.example# Parameter configuration template
│   ├── variables.tf            # Parameterized infrastructure inputs
│   └── vpc.tf                  # VPC, 1 public & 2 private subnets, IGW, route tables
├── seeds/
│   └── init.sql                # Relational schema and initial catalog seed (15 items)
├── .dockerignore               # Build context exclusions
├── .env.example                # Documented runtime environment template
├── .gitignore                  # Git exclusions for secrets, state, and caches
├── Dockerfile                  # Hardened multi-stage unprivileged container definition
├── docker-compose.yml          # Local full-stack orchestration (App, DB, Datadog Agent)
├── requirements.txt            # Locked runtime dependencies
├── submission.json             # Verification metadata and deployment identifiers
└── README.md
```

---

## Local Development & Testing

### Prerequisites

- Docker Engine 20.10+ and Docker Compose v2+
- Datadog Account (Free Tier / Trial) with an API Key
- `curl` or Postman for endpoint validation

### 1. Configure Local Environment

Copy the environment template and provide your Datadog API credentials:

```bash
cp .env.example .env
```

Ensure the following variables are set in `.env`:

```ini
APP_PORT=8080
DB_HOST=db
DB_WRITER_HOST=db
DB_READER_HOST=db
DB_PORT=5432
DB_NAME=ecommerce
DB_USER=postgres
DB_PASSWORD=postgres
DD_API_KEY=<your-datadog-api-key>
DD_SITE=datadoghq.com
DD_SERVICE=ecommerce-api
DD_ENV=development
```

### 2. Launch Local Environment

Start the full stack (PostgreSQL database, containerized API, and Datadog Agent):

```bash
docker-compose up -d --build
```

### 3. Verify Container Health

Verify all containers have booted and passed their defined healthchecks:

```bash
docker-compose ps
```

*Expected output:*
```
NAME                                IMAGE                       COMMAND                  SERVICE         STATUS
ecommerce-backend-app-1             ecommerce-backend-app       "ddtrace-run gunicor…"   app             Up (healthy)
ecommerce-backend-datadog-agent-1   gcr.io/datadoghq/agent:7    "/bin/entrypoint.sh …"   datadog-agent   Up (healthy)
ecommerce-backend-db-1              postgres:16-alpine          "docker-entrypoint.s…"   db              Up (healthy)
```

### 4. Execute Smoke Tests

```bash
# 1. Healthcheck endpoint (validates DB connectivity)
curl -s -w "\nHTTP Status: %{http_code}\n" http://localhost:8080/health

# 2. Retrieve product catalog (routed through read pool)
curl -s http://localhost:8080/products | jq .

# 3. Retrieve single product by ID
curl -s http://localhost:8080/products/1 | jq .

# 4. Place a new order (routed through write pool)
curl -s -X POST http://localhost:8080/orders \
     -H "Content-Type: application/json" \
     -d '{"product_id": 1, "quantity": 2}' | jq .
```

---

## Cloud Infrastructure Deployment (Terraform)

All AWS cloud infrastructure is managed as declarative code inside the `infra/` directory.

### Prerequisites

- Terraform >= 1.5.0
- AWS CLI v2 configured with appropriate credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)

### Deployment Procedure

1. **Initialize Terraform:**
   ```bash
   cd infra
   cp terraform.tfvars.example terraform.tfvars
   terraform init
   ```

2. **Validate Configurations:**
   ```bash
   terraform validate
   terraform fmt -check
   ```

3. **Plan and Review Proposed Changes:**
   ```bash
   terraform plan -out=tfplan
   ```

4. **Apply Infrastructure:**
   ```bash
   terraform apply tfplan
   ```

### Captured Outputs

Upon completion, Terraform exposes the connection strings:

| Output | Description |
| :--- | :--- |
| `vpc_id` | Managed VPC identifier |
| `rds_primary_endpoint` | Hostname endpoint for write transactions (`DB_WRITER_HOST`) |
| `rds_primary_identifier` | DB instance identifier (`ecommerce-primary`) |
| `rds_replica_endpoint` | Hostname endpoint for read queries (`DB_READER_HOST`) |
| `rds_replica_identifier` | DB instance identifier (`ecommerce-replica`) |
| `app_security_group_id` | Security group ID attached to application compute |
| `rds_security_group_id` | Security group ID attached to database instances |

### Teardown

To prevent unwanted cloud billing after evaluation:

```bash
terraform destroy -auto-approve
```

---

## Observability & Telemetry

### Datadog Integration Map

| Layer | Collector | Mechanism | Key Telemetry |
| :--- | :--- | :--- | :--- |
| **Database** | Datadog AWS Integration | CloudWatch Metric Stream | CPU Utilization, Connection Counts, Read/Write IOPS |
| **Application** | `ddtrace` (APM) | `ddtrace-run` wrapper | Distributed traces, p95 request duration, hit rates, error counts |
| **System** | Datadog Agent (Sidecar) | Docker socket mount | Host memory, container CPU, thread metrics |
| **Logs** | Datadog Agent | Docker socket log harvester | Structured JSON application logs with log-trace correlation |
| **Business/Perf** | DogStatsD | UDP Client (Port 8125) | Product browsing velocity, query timing distributions |

### Custom DogStatsD Metrics

| Metric Name | Type | Description | Tags |
| :--- | :--- | :--- | :--- |
| `products.requests.total` | Counter | Increments on every catalog view request (`GET /products`) | `service:ecommerce-api` |
| `db.query.duration_ms` | Timer/Histogram | High-resolution database query latency in milliseconds | `role:reader`, `role:writer` |
| `orders.created.total` | Counter | Increments on successful purchase transactions (`POST /orders`) | `service:ecommerce-api` |

### Version-Controlled Dashboard (`datadog/dashboard.json`)

The exported dashboard provides single-pane-of-glass operational visibility:
1. **RDS CPU Utilization:** Side-by-side timeseries comparison of Primary vs. Replica (`aws.rds.cpuutilization`).
2. **Database Connections:** Monitored open connection pool trends (`aws.rds.database_connections`).
3. **Read IOPS:** Disk throughput patterns across instances (`aws.rds.read_iops`).
4. **Application Throughput:** Request hits per second calculated from APM (`trace.ecommerce-api.request.hits`).
5. **Application Latency:** 95th-percentile (p95) response times (`trace.ecommerce-api.request.duration`).
6. **Custom Metric Stream:** Real-time counter of catalog browse traffic (`products.requests.total`).
7. **Query Duration Histogram:** Average latency distribution for SQL operations (`db.query.duration_ms`).

### Automated Alerting (`datadog/monitor.json`)

- **Alert Condition:** `avg(last_5m):avg:aws.rds.cpuutilization{dbinstanceidentifier:ecommerce-primary} > 80`
- **Severity Threshold:** Trigger on CPU > 80% sustained across a 5-minute rolling window.
- **Notification Payload:** Direct notification with diagnostic instructions (evaluating spike patterns, missing indexes, and long-running transactions).

---

## API Reference

### Health Check

```http
GET /health
```
- **Response:** `200 OK`
- **Body:**
  ```json
  {
    "status": "healthy",
    "pools": "active"
  }
  ```

### List All Products

```http
GET /products
```
- **Routing:** Directed to RDS Read Replica (`DB_READER_HOST`)
- **Metric Emitted:** `products.requests.total` (+1)
- **Response:** `200 OK`
- **Body:**
  ```json
  [
    {
      "id": 1,
      "name": "Wireless Mouse",
      "description": "Ergonomic wireless mouse with USB-C receiver",
      "price": "29.99",
      "category": "Electronics",
      "stock": 500
    }
  ]
  ```

### Get Product Details

```http
GET /products/:id
```
- **Routing:** Directed to RDS Read Replica (`DB_READER_HOST`)
- **Metric Emitted:** `products.requests.total` (+1)
- **Response:** `200 OK` (or `404 Not Found`)

### Create Order

```http
POST /orders
```
- **Routing:** Directed to RDS Primary DB (`DB_WRITER_HOST`)
- **Metric Emitted:** `orders.created.total` (+1)
- **Payload:**
  ```json
  {
    "product_id": 1,
    "quantity": 2
  }
  ```
- **Response:** `201 Created`
- **Body:**
  ```json
  {
    "message": "Order created successfully"
  }
  ```

---

## Operational Runbook & Disaster Recovery

### Handling Flash-Sale Concurrency
- If read latency spikes, verify `aws.rds.replica_lag` in Datadog. A replication lag under 2 seconds indicates healthy replication streaming.
- If primary CPU approaches the 80% alert threshold, inspect `db.query.duration_ms` filtered by `role:writer` to pinpoint unindexed transaction locks.

### Failover Procedures (Multi-AZ Upgrade)
In an enterprise environment where Multi-AZ is activated:
1. Primary instance failure triggers an automatic DNS flip to the synchronous standby within 60-120 seconds.
2. The application's `ThreadedConnectionPool` automatically drops stale sockets and establishes clean connections to the updated endpoint without process restarts.

---

## Verification Identifiers (`submission.json`)

```json
{
  "aws_region": "us-east-1",
  "rds_primary_identifier": "ecommerce-primary",
  "rds_replica_identifier": "ecommerce-replica",
  "datadog_dashboard_url": "https://app.datadoghq.com/dashboard/ecommerce-primary-overview"
}
```

---

## License

This project is licensed under the Apache 2.0 License.
