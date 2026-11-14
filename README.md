# Scalable, Observable E-commerce Backend on AWS with RDS & Datadog

A production-engineered e-commerce API backend designed for high-concurrency read workloads. Built with **Python (Flask, Gunicorn `gthread`)**, backed by **AWS RDS PostgreSQL (Primary + Read Replica)**, and comprehensively instrumented with **Datadog** for APM distributed tracing, container logs, and DogStatsD custom metrics.

---

## 1. System Architecture

```
                          ┌────────────────────────┐
                          │   Client Requests      │
                          │   (Traffic Surge)      │
                          └───────────┬────────────┘
                                      │
                          ┌───────────▼────────────┐
                          │     Gunicorn WSGI      │
                          │  (gthread Worker Pool) │
                          └───────────┬────────────┘
                                      │
                          ┌───────────▼────────────┐
                          │   Flask Application    │
                          │ (Threaded Conn Pools)  │
                          └─────┬────────────┬─────┘
                                │            │
      Read Queries (e.g., /products)         │ Write Queries (e.g., /orders)
                                │            │
                    ┌───────────▼──┐      ┌──▼───────────┐
                    │   RDS Read   │      │  RDS Primary │
                    │   Replica    │◄─────┤   (Writer)   │
                    │ (db.t3.micro)│ Async│ (db.t3.micro)│
                    └──────┬───────┘ Repl └──────┬───────┘
                           │                     │
                           └──────────┬──────────┘
                                      │ CloudWatch Metrics
                          ┌───────────▼────────────┐
                          │     Datadog Agent      │
                          │  (DogStatsD, APM, Logs)│
                          └───────────┬────────────┘
                                      │
                          ┌───────────▼────────────┐
                          │    Datadog Platform    │
                          │ (Dashboards & Monitors)│
                          └────────────────────────┘
```

### Architectural Decisions

1. **Read/Write Splitting with Thread-Safe Connection Pools:**  
   The application leverages `psycopg2.pool.ThreadedConnectionPool` to isolate read operations (`DB_READER_HOST`) from write operations (`DB_WRITER_HOST`). Connection reuse eliminates the high CPU and latency overhead of opening TLS sockets on every incoming query.
2. **Container Security & Concurrency:**  
   The container executes under an unprivileged user (`appuser`, UID 1001) using a multi-stage build that strips compilation tooling (`gcc`, `libpq-dev`). Gunicorn runs using the `gthread` worker class to asynchronously handle database I/O without thread starvation.
3. **Network Isolation:**  
   RDS instances are provisioned in private subnets across multiple Availability Zones with no public IP allocation. The dedicated RDS security group strictly restricts inbound traffic on port 5432 to the application security group.
4. **Full-Stack Observability:**  
   - **CloudWatch Metric Stream / Integration:** Ingests RDS CPU, database connections, and IOPS.
   - **Datadog APM (`ddtrace`):** Injected via `ddtrace-run` to trace HTTP requests and database queries automatically.
   - **DogStatsD:** Custom metrics for business events (`products.requests.total`) and query timings (`db.query.duration_ms`).
   - **Unified Log Management:** Container stdout/stderr auto-harvested with source and service tags.

---

## 2. Repository Layout

```
.
├── app/
│   ├── __init__.py
│   ├── main.py                 # Core API, connection pooling, DogStatsD instrumentation
│   └── wsgi.py                 # WSGI entry-point for Gunicorn
├── datadog/
│   ├── dashboard.json          # Datadog dashboard definition (7 widgets)
│   └── monitor.json            # CPU threshold alert definition (>80% over 5m)
├── infra/
│   ├── outputs.tf              # RDS endpoints, VPC ID, security group IDs
│   ├── providers.tf            # AWS provider specification
│   ├── rds.tf                  # Primary RDS instance & Read Replica
│   ├── security_groups.tf      # Ingress/egress rules for App and RDS
│   ├── terraform.tfvars.example# Input variable defaults
│   ├── variables.tf            # Parameterized infrastructure inputs
│   └── vpc.tf                  # VPC, subnets, IGW, routing tables
├── seeds/
│   └── init.sql                # Relational schema and initial product catalog
├── .dockerignore
├── .env.example                # Documented configuration variables
├── .gitignore
├── Dockerfile                  # Hardened multi-stage container specification
├── docker-compose.yml          # Local environment orchestration
├── requirements.txt            # Runtime dependencies
├── submission.json             # Infrastructure identifiers for verification
└── README.md
```

---

## 3. Local Development & Verification

### Prerequisites
- Docker Engine 20.10+
- Docker Compose v2+
- Datadog API Key (from your trial account)

### Quick Start

1. **Configure Environment:**
   ```bash
   cp .env.example .env
   # Add your DD_API_KEY inside .env
   ```

2. **Launch Services:**
   ```bash
   docker-compose up -d --build
   ```

3. **Verify Service Health:**
   ```bash
   docker-compose ps
   ```
   Both `app` and `db` should report a `healthy` status.

4. **Test API Endpoints:**
   ```bash
   # Health check
   curl -i http://localhost:8080/health

   # Catalog browsing (Read path -> Replica/Reader host)
   curl -i http://localhost:8080/products
   curl -i http://localhost:8080/products/1

   # Order placement (Write path -> Primary host)
   curl -i -X POST http://localhost:8080/orders \
        -H "Content-Type: application/json" \
        -d '{"product_id": 1, "quantity": 2}'
   ```

---

## 4. Cloud Infrastructure Deployment (Terraform)

### Prerequisites
- Terraform >= 1.5.0
- AWS CLI configured with administrator privileges

### Deployment Steps

1. **Navigate to Infrastructure Directory:**
   ```bash
   cd infra
   cp terraform.tfvars.example terraform.tfvars
   ```

2. **Initialize and Validate:**
   ```bash
   terraform init
   terraform validate
   ```

3. **Plan and Deploy:**
   ```bash
   terraform plan -out=tfplan
   terraform apply tfplan
   ```

4. **Capture Outputs:**
   Use the printed outputs (`rds_primary_endpoint` and `rds_replica_endpoint`) to populate `DB_WRITER_HOST` and `DB_READER_HOST` in the application runtime environment.

### Teardown
```bash
terraform destroy -auto-approve
```

---

## 5. Observability & Monitoring Specification

### Custom Metrics
| Metric Name | Type | Purpose | Tags |
| :--- | :--- | :--- | :--- |
| `products.requests.total` | Counter | Tracks total hit count on product catalog endpoints | — |
| `db.query.duration_ms` | Timer/Histogram | Execution latency of SQL queries | `role:reader`, `role:writer` |

### Exported Datadog Artifacts
- **Dashboard (`datadog/dashboard.json`):**  
  - RDS CPU Utilization (Primary vs. Replica) (`aws.rds.cpuutilization`)
  - RDS Database Connections (Primary vs. Replica) (`aws.rds.database_connections`)
  - RDS Read IOPS (Primary vs. Replica) (`aws.rds.read_iops`)
  - Application Request Rate (`trace.ecommerce-api.request.hits`)
  - Application p95 Latency (`trace.ecommerce-api.request.duration`)
  - Custom metrics: `products.requests.total` and `db.query.duration_ms`

- **Monitor (`datadog/monitor.json`):**  
  - Alert Type: Metric Alert
  - Query: `avg(last_5m):avg:aws.rds.cpuutilization{dbinstanceidentifier:ecommerce-primary} > 80`
  - Notification Message: Explicitly alerts that RDS Primary CPU is high and recommends investigation paths.

---

## 6. Verification Identifiers (`submission.json`)

```json
{
  "aws_region": "us-east-1",
  "rds_primary_identifier": "ecommerce-primary",
  "rds_replica_identifier": "ecommerce-replica",
  "datadog_dashboard_url": "https://app.datadoghq.com/dashboard/ecommerce-primary-overview"
}
```
