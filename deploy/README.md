# T02 private entry deployment

This stack is an entry-validation environment, not an accepted production research service. It currently contains the product identity DB/API and a named Tunnel connector. The research source fails closed until an explicitly configured T02 synthetic probe is supplied; it does not run an Agent or Temporal workflow. T09 recovery gates remain required before private research records are enabled.

## Configuration

Copy `.env.example` to ignored `.env`, generate a project-only database password, and set the three Auth0/API values. Store the named Tunnel connector token in ignored `secrets/tunnel-token`. Keep both files outside git with restricted host permissions. The connector's container user must be able to read its mounted token; do not print it or pass it as a command-line argument.

The Docker context is an allowlist of package source, migrations and lockfiles. Images pin manifest digests with Linux ARM64 support. The runtime contains the non-editable installed package, runs as UID 10001, and has a read-only filesystem. PostgreSQL and API publish no host ports. Only the project's connector shares their dedicated Compose network; no existing host service, volume or credential is reused.

## Launch and verify

From the repository root, after setting `WHISKY_RELEASE` to the application commit:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.yaml build api
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d api
docker compose --env-file deploy/.env -f deploy/compose.yaml ps
docker compose --env-file deploy/.env -f deploy/compose.yaml exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8417/health/live').status)"
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d tunnel
```

`api` waits for the one-shot migration, which waits for PostgreSQL. Liveness does not prove DB, authentication, VPC, SSE or recovery readiness. Record those checks separately. Keep exactly one API container/process: the two-connections-per-owner limiter is process-local. No rolling overlap or `--scale api` is allowed until that limiter is replaced and revalidated.

Register an HTTP Workers VPC Service against this named Tunnel, hostname `api`, HTTP port `8417`, and bind it as `WHISKY_API`. The Tunnel uses QUIC; do not use a public hostname, Quick Tunnel or a general-purpose upstream proxy. The Web proxy retains its path/method allowlist and the API verifies Auth0 tokens.

## Stop / rollback

Use this Compose file and project name only. Stop `tunnel` and `api` before changing the API release, then select a previously verified compatible image tag and start `api`, followed by `tunnel`. Do not downgrade schema automatically. Stop only this project's containers; never use global Docker prune, remove shared networks, or delete the database volume. This stop/start release strategy preserves the single-process observation limit.

Database backups and an isolated restore are not established by this entry stack. T09 must add and prove them before accepting durable research data.

## Explicit synthetic entry probe

After real Auth0 login establishes the dedicated test actor, set `WHISKY_PROBE_OWNER` to that internal UUID. Stop the API before launching with both `-f deploy/compose.yaml -f deploy/compose.probe.yaml`. The extra file mounts `entry_probe.py` read-only and replaces the API command. The normal image command never enables this source. It accepts exactly the fixed task/run/revision in the script and the configured owner, while using the same real JWT verification, live actor checks, polling, lifetime and connection limits as the API. Its in-memory snapshots are explicitly synthetic, contain no whisky/user research, and reset only when the probe process restarts. Do not interpret them as durable task state.

For the temporary browser harness, run `node --env-file=.env.local scripts/build-live-probe.mjs` from `apps/web` **after** the production build and before deployment. This adds `__entry_probe.html` and its bundle to the generated assets only; regular builds omit them. Allow the exact `https://<this-worker>/__entry_probe.html` Auth0 callback temporarily. The page uses memory-only Auth0 tokens and prints only actor UUID, safe HTTP statuses, snapshot versions and relative timings. It does not print or persist tokens.

After measuring flush/reconnect/multi-tab behavior, stop the probe API, start the normal Compose configuration without the override, remove the temporary Auth0 callback, and deploy a fresh normal Web build. Verify the generated assets omit the probe and normal observation fails closed until the product's durable source is implemented. Record the release and measurements in the implementation plan.
