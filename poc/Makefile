.PHONY: up down logs v1 v2 v3 reset

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f scraper agent

v1:
	@SITE_VERSION=v1 docker compose up -d --force-recreate mock_site >/dev/null 2>&1 && echo "mock_site flipped to v1"

v2:
	@SITE_VERSION=v2 docker compose up -d --force-recreate mock_site >/dev/null 2>&1 && echo "mock_site flipped to v2"

v3:
	@SITE_VERSION=v3 docker compose up -d --force-recreate mock_site >/dev/null 2>&1 && echo "mock_site flipped to v3"

reset:
	./reset.sh
