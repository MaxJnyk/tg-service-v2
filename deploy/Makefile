.PHONY: build push deploy migrate check-proxies sessions-status

IMAGE = registry.lgd.cx/tad/tg-service-v2
TAG ?= latest

build:
	docker build -t $(IMAGE):$(TAG) ..

push: build
	docker push $(IMAGE):$(TAG)

deploy:
	TAG=$(TAG) docker compose -f docker-compose.production.yml pull
	TAG=$(TAG) docker compose -f docker-compose.production.yml up -d

deploy-specific:
	@echo "Deploying version: $(TAG)"
	docker compose -f docker-compose.production.yml pull tg-service
	docker compose -f docker-compose.production.yml up -d tg-service

# Rollback to previous version
rollback:
	docker compose -f docker-compose.production.yml stop tg-service
	docker compose -f docker-compose.production.yml rm -f tg-service
	docker compose -f docker-compose.production.yml up -d tg-service

# Initial setup on new server
setup:
	@echo "Creating external network tad-network..."
	docker network create tad-network 2>/dev/null || true
	@echo "Setup complete. Copy .env.production to .env and configure."

migrate:
	docker compose -f docker-compose.production.yml exec tg-service alembic upgrade head

check-proxies:
	docker compose -f docker-compose.production.yml exec tg-service python -m src.cli.proxies check

sessions-status:
	docker compose -f docker-compose.production.yml exec tg-service python -m src.cli.sessions status

logs:
	docker compose -f docker-compose.production.yml logs -f tg-service --tail=100

restart:
	docker compose -f docker-compose.production.yml restart tg-service
