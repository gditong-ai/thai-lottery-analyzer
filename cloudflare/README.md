# Cloudflare migration (in progress)

Original Render/FastAPI deployment remains unchanged. This directory is a Cloudflare Workers + D1 port of the public API and existing dashboard. **Not production-ready** until migration and tests finish.

1. Create a D1 database named thai-lottery-analyzer using Cloudflare dashboard or Wrangler.
2. Set its actual database_id in wrangler.toml.
3. Apply schema.sql to the remote D1 database.
4. Export all historical rows from Render PostgreSQL and import them into D1, preserving draw_date and lunar_side.
5. Validate record counts and oldest/newest dates against Render.
6. Run `npx wrangler deploy --config cloudflare/wrangler.toml` from repository root, then test dashboard and API.

**Known blockers:** The original Python implementation uses pythaidate to compute lunar_side. The Worker port currently requires a valid lunar_side in imports; GLO import endpoints return items without this field. A compatible lunar-calendar conversion must be added before enabling GLO imports. For range imports, also use background jobs or batching to avoid Worker request duration limits. Protect all write endpoints with ADMIN_TOKEN before production deployment; the existing dashboard has no authentication and must be updated to use a secure authorization flow. Do not deploy publicly as-is. Cloudflare account access is required to create the D1 database and deploy.
