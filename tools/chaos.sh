#!/usr/bin/env bash
# DeliverIQ Chaos Engineering Script
# Injects realistic failures to test distributed transaction resiliency,
# compensation sagas, and circuit breakers.

set -e

ACTION=${1:-"help"}

case "$ACTION" in
  kill-payment)
    echo "💥 Chaos: Stopping Payment Service (triggers immediate order cancellation)..."
    docker compose -f ops/docker-compose.yml stop payment-service
    echo "Payment service stopped. Orders will fail during authorization."
    ;;

  kill-inventory)
    echo "💥 Chaos: Stopping Inventory Service (triggers compensating payment refund)..."
    docker compose -f ops/docker-compose.yml stop inventory-service
    echo "Inventory service stopped. Orders will authorize payment then refund & cancel."
    ;;

  kill-eta)
    echo "💥 Chaos: Stopping ETA Service (triggers graceful degradation, order stays confirmed)..."
    docker compose -f ops/docker-compose.yml stop eta-service
    echo "ETA service stopped. Orders will confirm with degraded fallback ETA."
    ;;

  restart-redis)
    echo "💥 Chaos: Restarting Redis..."
    docker compose -f ops/docker-compose.yml restart redis
    echo "Redis restarted. Stream consumers will reconnect."
    ;;

  restore)
    echo "🟢 Chaos: Restoring all services..."
    docker compose -f ops/docker-compose.yml start payment-service inventory-service eta-service
    echo "All services restored and running."
    ;;

  status)
    echo "📋 Stack Status:"
    docker compose -f ops/docker-compose.yml ps
    ;;

  *)
    echo "Usage: $0 {kill-payment|kill-inventory|kill-eta|restart-redis|restore|status}"
    exit 1
    ;;
esac
