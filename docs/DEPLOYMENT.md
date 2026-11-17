# Deployment & operations

## Components

| Service | Image | Scale | Notes |
|---|---|---|---|
| web | `frontend/Dockerfile` (nginx) | 2+ | Serves the SPA, proxies `/api`, CSP, 110 MB uploads |
| api | `backend/Dockerfile` | 2+ | Runs `alembic upgrade head` then uvicorn (`PMA_WEB_WORKERS`, default 4). Stateless. |
| worker | same image, `python -m app.worker` | 2+ | RQ `SimpleWorker` with the JVM/MPXJ preloaded. CPU and memory heavy for large plans (`PMA_JVM_MAX_HEAP`). |
| PostgreSQL 16 | managed | HA | All metadata, tasks, KPIs, governance, audit |
| Redis 7 | managed | | Job queue only (no session state) |
| Object storage | S3/MinIO or Azure Blob | | Original files and logos. Enable versioning/soft delete. |
| Ollama | optional | GPU | Self-hosted AI. Or set `PMA_OLLAMA_CLOUD_API_KEY` for Ollama Cloud. |

All configuration uses `PMA_*` environment variables (see `.env.example` and `backend/app/config.py`).

## Docker Compose (single host)

```bash
cp .env.example .env && $EDITOR .env
docker compose up -d --build
docker compose logs -f api worker
```

Put TLS in front (Azure Front Door, Application Gateway, Traefik or Caddy) and set `PMA_PUBLIC_URL` to the HTTPS URL.

## Azure (recommended target)

| Need | Azure service |
|---|---|
| Containers | Azure Container Apps: apps `web`, `api` (ingress internal, `web` proxies) and `worker` (no ingress; KEDA Redis-list scaler on queue `rq:queue:pma`) |
| Database | Azure Database for PostgreSQL Flexible Server (zone-redundant HA, PITR 7–35 days) |
| Queue | Azure Cache for Redis (Standard C1+) |
| Files | Storage account + Blob container: `PMA_STORAGE_BACKEND=azure`, `PMA_AZURE_CONNECTION_STRING` (or Key Vault reference), soft delete on |
| Secrets | Key Vault referenced by Container Apps secrets |
| SSO | Microsoft Entra ID app registration: redirect `https://<host>/api/auth/oidc/callback`. Emit `roles` claim with app roles `PMA.Admin`, `PMA.Editor`. |
| AI | GPU VM / AKS node pool running Ollama on a private VNet (`PMA_OLLAMA_SELF_HOSTED_URL`), or Ollama Cloud per tenant |
| Monitoring | Container Apps logs → Log Analytics. Alert on `/api/ready` failing and on worker failures. |

```bash
az group create -n rg-pma -l uaenorth
az containerapp env create -n pma-env -g rg-pma -l uaenorth
az containerapp create -n pma-api -g rg-pma --environment pma-env \
  --image ghcr.io/<org>/<repo>/pma-backend:<sha> --ingress internal --target-port 8000 \
  --min-replicas 2 --secrets db-url=<...> secret-key=<...> blob=<...> \
  --env-vars PMA_ENV=production PMA_DATABASE_URL=secretref:db-url PMA_SECRET_KEY=secretref:secret-key \
             PMA_QUEUE_BACKEND=rq PMA_REDIS_URL=rediss://:<key>@<name>.redis.cache.windows.net:6380/0 \
             PMA_STORAGE_BACKEND=azure PMA_AZURE_CONNECTION_STRING=secretref:blob
az containerapp create -n pma-worker -g rg-pma --environment pma-env \
  --image ghcr.io/<org>/<repo>/pma-backend:<sha> --command "python" --args "-m" "app.worker" \
  --min-replicas 1 --max-replicas 6 <same env/secrets>
az containerapp create -n pma-web -g rg-pma --environment pma-env \
  --image ghcr.io/<org>/<repo>/pma-frontend:<sha> --ingress external --target-port 8080 --min-replicas 2
```

For Container Apps, change the `proxy_pass` target in `frontend/nginx.conf` to the internal FQDN of `pma-api`
(or route `/api` with ingress path rules).

## CI/CD

`.github/workflows/ci.yml`: backend migrations + tests (Java 17 + real MPXJ parsing), frontend strict
type-check + build, then images pushed to GHCR on `main`. Promote by updating the image tag on Container Apps
(`az containerapp update --image ...`). Migrations run automatically when the API starts.

## Operations

* **Health:** `GET /api/health` (liveness), `GET /api/ready` (database, storage, queue).
* **Backups:** PostgreSQL PITR + blob soft delete. Snapshots can be re-derived from stored originals
  (*Reprocess*), so the database plus blob storage is the full state.
* **First start:** the bootstrap admin is created from `PMA_BOOTSTRAP_ADMIN_*` (required in production).
  Change the password after first login.
* **Upgrading the KPI engine:** formulas are versioned. After an upgrade, re-approve the mapping (or Reprocess)
  to recompute history with the new versions. Stored values keep the version they were computed with.
* **AI capacity:** watch *Administration → AI call log* (latency, tokens, cache hits). Adjust
  `PMA_AI_DAILY_CALL_LIMIT`, `PMA_AI_TIMEOUT_SECONDS` and `PMA_AI_MAX_INPUT_CHARS`.
