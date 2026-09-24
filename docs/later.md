# Later

Out-of-scope ideas parked here so they don't creep into the current step.

- **Shared rate limiting (Step 17).** The per-IP token bucket lives in each container's memory, so N replicas allow N × 30 simulations a minute per IP, and a restart forgets everyone. At more than one replica, move it to a shared store (Redis, or a Mongo TTL collection) or to the ingress.
- **Client IP behind a proxy (Step 17).** Behind Azure Container Apps' ingress, `request.client.host` is the proxy's address unless uvicorn runs with `--proxy-headers --forwarded-allow-ips=*` (trusting `X-Forwarded-For`). Without that, every user shares one bucket. Set it in Step 19's Dockerfile `CMD`.
