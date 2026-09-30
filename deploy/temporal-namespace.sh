#!/bin/sh
set -eu

: "${TEMPORAL_ADDRESS:?set private Temporal address}"
: "${WHISKY_TEMPORAL_NAMESPACE:?set dedicated namespace}"
temporal operator cluster health --address "$TEMPORAL_ADDRESS" >/dev/null
if ! temporal operator namespace describe --address "$TEMPORAL_ADDRESS" \
    --namespace "$WHISKY_TEMPORAL_NAMESPACE" -o json >/dev/null 2>&1; then
    temporal operator namespace create --address "$TEMPORAL_ADDRESS" \
        --namespace "$WHISKY_TEMPORAL_NAMESPACE" --retention 30d
fi
actual=$(temporal operator namespace describe --address "$TEMPORAL_ADDRESS" \
    --namespace "$WHISKY_TEMPORAL_NAMESPACE" -o json | \
    jq -r '.config.workflowExecutionRetentionTtl')
if [ "$actual" != 2592000s ]; then
    echo "Temporal namespace retention differs from 30d" >&2
    exit 1
fi
