.PHONY: build push deploy migrate check-proxies sessions-status

IMAGE = registry.lgd.cx/tad/tg-service-v2
TAG ?= latest

build:
	docker build -t $(IMAGE):$(TAG) ..

push: build
	docker push $(IMAGE):$(TAG)

deploy:
	docker compose -f docker-compose.production.yml pull
	docker compose -f docker-compose.production.yml up -d

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
