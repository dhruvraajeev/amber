# Later

Out-of-scope ideas parked here so they don't creep into the current step.

- **Shared rate limiting (Step 17).** The per-IP token bucket lives in each container's memory, so N replicas allow N × 30 simulations a minute per IP, and a restart forgets everyone. At more than one replica, move it to a shared store (Redis, or a Mongo TTL collection) or to the ingress.
- **Check the client IP on Azure (Step 24).** The image trusts `X-Forwarded-For` only from private-network hops (`FORWARDED_ALLOW_IPS`, see decisions.md). If Container Apps' ingress turns out not to connect from a private range, every user shares one rate-limit bucket: find its address and set `FORWARDED_ALLOW_IPS` on the container app (no rebuild). Never `*`.
