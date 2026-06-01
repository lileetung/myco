.PHONY: up logs agent-logs v1 v2 v3 reset

up:
	docker compose up -d --build
	@PID=$$(cat .agent.lock 2>/dev/null); \
	if [ -n "$$PID" ] && kill -0 "$$PID" 2>/dev/null && ps -p "$$PID" -o command= 2>/dev/null | grep -q auto_healer; then \
		echo "auto-healer already running (pid $$PID)"; \
	else \
		nohup python3 auto_healer.py >/dev/null 2>&1 & \
		sleep 0.5; \
		NEW_PID=$$(cat .agent.lock 2>/dev/null); \
		if [ -n "$$NEW_PID" ] && kill -0 "$$NEW_PID" 2>/dev/null; then \
			echo "auto-healer started (pid $$NEW_PID)"; \
		else \
			echo "auto-healer failed to start (check workspace/agent.log)"; \
		fi; \
	fi

logs:
	docker compose logs -f scraper

agent-logs:
	tail -f workspace/agent.log

v1:
	@SITE_VERSION=v1 docker compose up -d --force-recreate mock_site >/dev/null 2>&1 && echo "mock_site flipped to v1"

v2:
	@SITE_VERSION=v2 docker compose up -d --force-recreate mock_site >/dev/null 2>&1 && echo "mock_site flipped to v2"

v3:
	@SITE_VERSION=v3 docker compose up -d --force-recreate mock_site >/dev/null 2>&1 && echo "mock_site flipped to v3"

reset:
	./reset.sh
