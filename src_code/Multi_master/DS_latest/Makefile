# Makefile to manage GFS Master Servers, Chunk Servers, and Web Server

.PHONY: all start_masters start_chunks start_webserver start_all stop_masters stop_chunks stop_webserver stop_all logs_dir

# Define the master and chunk server ports
MASTER_PORTS = 7082 7083 7084
CHUNK_PORTS = 6467 6468 6469 6470

# Default target
all: start_all

logs_dir:
	@mkdir -p logs

start_masters: logs_dir
	@echo "Starting Master Servers..."
	@for port in $(MASTER_PORTS); do \
		echo "Starting Master Server on port $$port"; \
		nohup python master_server.py $$port > logs/master_$$port.log 2>&1 & \
		echo $$! > master_$$port.pid; \
	done

start_chunks: logs_dir
	@echo "Starting Chunk Servers..."
	@for port in $(CHUNK_PORTS); do \
		echo "Starting Chunk Server on port $$port"; \
		nohup python chunk_server.py $$port > logs/chunk_$$port.log 2>&1 & \
		echo $$! > chunk_$$port.pid; \
	done

start_webserver: logs_dir
	@echo "Starting Web Server..."
	@nohup python websocket_server.py > logs/webserver.log 2>&1 & \
	echo $$! > webserver.pid

start_all: start_masters start_chunks start_webserver
	@echo "All servers started."

stop_masters:
	@echo "Stopping Master Servers..."
	@for port in $(MASTER_PORTS); do \
		if [ -f master_$$port.pid ]; then \
			kill `cat master_$$port.pid` 2>/dev/null || true; \
			rm -f master_$$port.pid; \
			echo "Stopped Master Server on port $$port"; \
		else \
			echo "Master Server on port $$port is not running."; \
		fi; \
	done

stop_chunks:
	@echo "Stopping Chunk Servers..."
	@for port in $(CHUNK_PORTS); do \
		if [ -f chunk_$$port.pid ]; then \
			kill `cat chunk_$$port.pid` 2>/dev/null || true; \
			rm -f chunk_$$port.pid; \
			echo "Stopped Chunk Server on port $$port"; \
		else \
			echo "Chunk Server on port $$port is not running."; \
		fi; \
	done

stop_webserver:
	@echo "Stopping Web Server..."
	@if [ -f webserver.pid ]; then \
		kill `cat webserver.pid` 2>/dev/null || true; \
		rm -f webserver.pid; \
		echo "Web Server stopped."; \
	else \
		echo "Web Server is not running."; \
	fi

stop_all: stop_masters stop_chunks stop_webserver
	@echo "All servers stopped."
