# T02 private entry deployment

This stack is an entry-validation environment, not an accepted production research service. Its target contains a native Next.js/Node Web container, product identity DB/API and named Tunnel connector. Deployment progress is recorded in the implementation plan. The research source fails closed unless the explicit synthetic probe is mounted. T09 recovery gates remain required before private research records are enabled.

## Configuration

Copy `.env.example` to ignored `.env`, generate a project-only database password, and set the three Auth0/API values. Store the named Tunnel connector token in ignored `secrets/tunnel-token`. Keep both files outside git with restricted host permissions. The connector's container user must be able to read its mounted token; do not print it or pass it as a command-line argument.

The Docker context allowlists package source, public contracts/configuration, migrations and lockfiles, excluding environment files and credentials. Images pin ARM64-capable digests. The installed Python package runs as UID 10001; native Next.js standalone runs as UID 1000. Both use read-only filesystems. Web, PostgreSQL and API publish no host ports and share only the dedicated project network with its connector. No other project's services, volumes or credentials are reused. Auth0 domain/client ID/audience are public Web build arguments; private API origin is runtime-only.

## Launch and verify

From the repository root, set immutable `WHISKY_RELEASE` (API) and `WHISKY_WEB_RELEASE` tags plus the public Auth0 values:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.yaml build api web
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d api web
docker compose --env-file deploy/.env -f deploy/compose.yaml ps
docker compose --env-file deploy/.env -f deploy/compose.yaml exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8417/health/live').status)"
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d tunnel
```

`api` waits for the one-shot migration, which waits for PostgreSQL. Liveness does not prove DB, authentication, VPC, SSE or recovery readiness. Record those checks separately. Keep exactly one API container/process: the two-connections-per-owner limiter is process-local. No rolling overlap or `--scale api` is allowed until that limiter is replaced and revalidated.

Register an HTTP Workers VPC Service against this named Tunnel, hostname `web`, HTTP port `3417`, and bind it as `WHISKY_WEB` in `apps/edge`. After Web health and private-network checks, deploy with `pnpm --filter @whisky/edge run deploy` (`run` distinguishes the script from pnpm's built-in deploy command). This replaces the former SSR Worker at the same public URL. The Tunnel uses QUIC; no public Tunnel hostname or Quick Tunnel. The thin Worker forwards only to its fixed binding, preserves the public forwarded origin, and never follows redirects. Node Web retains the API path/method allowlist, Bearer-only forwarding and no-store; FastAPI remains the authentication/owner authority.

## Stop / rollback

Use this Compose project only. Stop `api` before changing its release, select a verified compatible image, then start it without overlap. Web may be stopped/replaced independently; never restore an older database over current data. For the initial Web cutover, retain the previous SSR Worker version and original API VPC service until acceptance; rollback the public Worker to that version before stopping the candidate Web. After acceptance, normal rollback selects the prior Web image while keeping the thin Worker and Web VPC binding. Do not downgrade schema automatically, prune Docker, or remove shared resources. The API stop/start strategy preserves the process-local connection limit.

Database backups and an isolated restore are not established by this entry stack. T09 must add and prove them before accepting durable research data.

## Explicit synthetic entry probe

After real Auth0 login establishes the dedicated test actor, set `WHISKY_PROBE_OWNER` to that internal UUID. Stop the API before launching with both `-f deploy/compose.yaml -f deploy/compose.probe.yaml`. The extra file mounts `entry_probe.py` read-only and replaces the API command. The normal image command never enables this source. It accepts exactly the fixed task/run/revision in the script and the configured owner, while using the same real JWT verification, live actor checks, polling, lifetime and connection limits as the API. Its in-memory snapshots are explicitly synthetic, contain no whisky/user research, and reset only when the probe process restarts. Do not interpret them as durable task state.

For the temporary browser harness, run `node --env-file=.env.local scripts/build-live-probe.mjs` from `apps/web`. Copy its `.artifacts/live-probe/` output to ignored `deploy/probe-public/` on the target. The explicit override mounts that directory read-only as the Web public directory; restart Web with the override. Normal images contain no probe assets. Allow exactly `https://<this-worker>/__entry_probe.html` as a temporary Auth0 callback. The page uses memory-only tokens and prints only actor UUID, safe HTTP statuses, snapshot versions and relative timings, never tokens.

After measuring flush/reconnect/multi-tab behavior, stop the probe API/Web and start their normal Compose configuration without the override. Remove the temporary Auth0 callback. Verify the probe URL is 404 and normal observation fails closed until the durable source is implemented. Record the release and measurements in the implementation plan.
