#!/usr/bin/env bash
# Deploy the Crisis Resource Navigator — an always-on socket-mode worker.
#
#   deploy/deploy.sh [gce|fly]      (default: gce)
#
# Socket mode opens an OUTBOUND websocket to Slack (no inbound HTTP), so the agent
# must run as a long-lived worker — not a request-driven / scale-to-zero service.
# Secrets come from deploy/.env.deploy (gitignored; copy .env.deploy.example).
# Nothing is deployed unless you run this with real creds — see deploy/README.md.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$SCRIPT_DIR/.env.deploy"
TARGET="${1:-gce}"   # GCE is the default target.

# --- GCE knobs (override via the environment) ---------------------------------
GCE_ZONE="${GCE_ZONE:-us-central1-a}"             # a free-tier region (us-central1/us-west1/us-east1)
GCE_INSTANCE="${GCE_INSTANCE:-crisis-resource-navigator}"
GCE_PROJECT="${GCE_PROJECT:-}"                    # else gcloud's active project
GCE_IMAGE="${GCE_IMAGE:-}"                        # REQUIRED for gce: e.g. us-central1-docker.pkg.dev/PROJ/crn/crn:latest

usage() {
  cat >&2 <<EOF
Usage: $0 [gce|fly]   (default: gce)

  gce   Build+push the image, run it on a free-tier e2-micro (create-with-container).
        Requires: gcloud auth, an Artifact Registry repo, and GCE_IMAGE set.
  fly   Import secrets + fly deploy the worker (one-time: fly launch --no-deploy).

Secrets: $ENV_FILE  (copy from deploy/.env.deploy.example and fill it).
See deploy/README.md.
EOF
  exit 2
}

case "$TARGET" in
  gce|fly) ;;
  -h|--help) usage ;;
  *) echo "ERROR: unknown target '$TARGET'." >&2; usage ;;
esac

# --- load + validate secrets --------------------------------------------------
if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found. Copy deploy/.env.deploy.example to it and fill in your tokens." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

REQUIRED="SLACK_BOT_TOKEN SLACK_APP_TOKEN GOOGLE_VERTEX_API_KEY SLACK_USER_TOKEN CRISIS_CHANNEL"
missing=""
for v in $REQUIRED; do
  eval "val=\${$v:-}"
  [ -n "$val" ] || missing="$missing $v"
done
if [ -n "$missing" ]; then
  echo "ERROR: missing required values in $ENV_FILE:$missing" >&2
  exit 1
fi

# KEY=VALUE lines with comments/blanks stripped — reused by both targets.
env_pairs() { grep -vE '^[[:space:]]*(#|$)' "$ENV_FILE"; }

deploy_fly() {
  command -v fly >/dev/null 2>&1 || { echo "ERROR: fly CLI not found — https://fly.io/docs/flyctl/install/" >&2; exit 1; }
  echo ">> Importing secrets to Fly…"
  env_pairs | fly secrets import -c "$SCRIPT_DIR/fly.toml"
  echo ">> Deploying worker to Fly…"
  fly deploy -c "$SCRIPT_DIR/fly.toml" --dockerfile "$REPO_ROOT/Dockerfile"
  fly scale count 1 -c "$SCRIPT_DIR/fly.toml" || true
  echo ">> Done. Tail logs:  fly logs -c $SCRIPT_DIR/fly.toml"
}

deploy_gce() {
  command -v gcloud >/dev/null 2>&1 || { echo "ERROR: gcloud CLI not found — https://cloud.google.com/sdk/docs/install" >&2; exit 1; }
  command -v docker >/dev/null 2>&1 || { echo "ERROR: docker not found (needed to build+push the image)." >&2; exit 1; }
  [ -n "$GCE_IMAGE" ] || { echo "ERROR: set GCE_IMAGE to your Artifact Registry image (see deploy/README.md)." >&2; exit 1; }

  local proj=(); [ -n "$GCE_PROJECT" ] && proj=(--project "$GCE_PROJECT")
  local container_env; container_env="$(env_pairs | paste -sd, -)"

  echo ">> Building + pushing $GCE_IMAGE (linux/amd64 — GCE VMs are x86_64) …"
  # --platform linux/amd64: the build host may be arm64 (Apple Silicon) but GCE
  # e2-micro is x86_64; without this the container crash-loops on "exec format error".
  docker build --platform linux/amd64 -t "$GCE_IMAGE" "$REPO_ROOT"
  docker push "$GCE_IMAGE"

  if gcloud compute instances describe "$GCE_INSTANCE" --zone "$GCE_ZONE" "${proj[@]}" >/dev/null 2>&1; then
    echo ">> Updating container on existing $GCE_INSTANCE …"
    gcloud compute instances update-container "$GCE_INSTANCE" --zone "$GCE_ZONE" "${proj[@]}" \
      --container-image "$GCE_IMAGE" --container-env "$container_env"
  else
    echo ">> Creating free-tier e2-micro $GCE_INSTANCE in $GCE_ZONE …"
    gcloud compute instances create-with-container "$GCE_INSTANCE" --zone "$GCE_ZONE" "${proj[@]}" \
      --machine-type e2-micro \
      --boot-disk-size 30GB --boot-disk-type pd-standard \
      --container-image "$GCE_IMAGE" \
      --container-env "$container_env" \
      --container-restart-policy always \
      --metadata-from-file startup-script="$SCRIPT_DIR/gce-startup.sh"
  fi
  echo ">> Done. SSH + logs:  gcloud compute ssh $GCE_INSTANCE --zone $GCE_ZONE -- 'sudo docker logs \$(sudo docker ps -q)'"
}

echo ">> Target: $TARGET"
case "$TARGET" in
  gce) deploy_gce ;;
  fly) deploy_fly ;;
esac
