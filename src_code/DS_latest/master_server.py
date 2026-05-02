import socket
import threading
import os
import math
import pickle
import time
import logging

logging.basicConfig(filename='master_server.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

CHUNK_PORTS = [6467, 6468, 6469, 6470]
REPLICATION_FACTOR = 2
HEARTBEAT_INTERVAL = 5
LEASE_DURATION = 30  # Lease duration in seconds

class MasterServer:
    def __init__(self, host, port):
        self.chunksize = 2048
        self.host = host
        self.port = port
        self.file_map = {}  # Maps filenames to their chunk IDs
        self.chunk_locations = {}  # Maps chunk IDs to their respective servers
        self.chunk_servers_info = {p: [] for p in CHUNK_PORTS}  # Tracks chunks held by each server
        self.active_servers = list(CHUNK_PORTS)  # Start with all chunk servers active
        self.leases = {}  # Tracks file leases
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        logging.info("Master Server initialized on host %s, port %d", host, port)

    def start(self):
        """Start the master server and begin listening for connections."""
        self.sock.listen(5)
        threading.Thread(target=self.heartbeat_monitor).start()
        threading.Thread(target=self.check_replication_integrity).start()
        threading.Thread(target=self.lease_expiration_checker).start()
        logging.info("Master Server started, listening for connections.")
        while True:
            client, address = self.sock.accept()
            threading.Thread(target=self.handle_client, args=(client, address)).start()

    def num_chunks(self, size):
        """Calculate the number of chunks required for a given file size."""
        return math.ceil(size / self.chunksize)

    def handle_client(self, client, address):
        """Handle incoming client requests."""
        try:
            request = pickle.loads(client.recv(4096))
            command = request.get('command')

            if command == 'upload':
                filename = request['filename']
                file_size = request['file_size']
                response = self.handle_upload(filename, file_size)
                client.send(pickle.dumps(response))

            elif command == 'download':
                filename = request['filename']
                response = self.get_chunk_locations(filename)
                client.send(pickle.dumps(response))

            elif command == 'list_files':
                response = {'status': 'success', 'files': list(self.file_map.keys())}
                client.send(pickle.dumps(response))

            elif command == 'lease':
                filename = request['filename']
                response = self.lease_file(filename, address)
                client.send(pickle.dumps(response))

            elif command == 'unlease':
                filename = request['filename']
                response = self.unlease_file(filename)
                client.send(pickle.dumps(response))

            elif command == 'heartbeat':
                port = request['port']
                self.update_server_status(port)

            client.close()
        except Exception as e:
            logging.error("Error handling client request: %s", e)
            client.close()

    def handle_upload(self, filename, file_size):
        """Handle file upload requests by allocating chunks and assigning servers."""
        if filename in self.file_map:
            return {'status': 'error', 'message': 'File already exists'}

        num_chunks = self.num_chunks(file_size)
        chunk_ids = [f"{filename}_chunk_{i}" for i in range(num_chunks)]
        self.file_map[filename] = chunk_ids

        # Allocate chunks to servers
        chunk_allocation = self.allocate_chunks(chunk_ids)
        if not chunk_allocation:
            return {'status': 'error', 'message': 'Failed to allocate chunks'}

        logging.info("Chunk allocation for file '%s': %s", filename, chunk_allocation)
        return {'status': 'success', 'chunks': chunk_allocation}

    def get_chunk_locations(self, filename):
        """Return chunk locations for a requested file."""
        if filename not in self.file_map:
            return {'status': 'error', 'message': 'File not found'}

        chunk_locations = {chunk_id: self.chunk_locations.get(chunk_id, []) for chunk_id in self.file_map[filename]}
        return {'status': 'success', 'chunk_locations': chunk_locations}

    def allocate_chunks(self, chunk_ids):
        """Allocate chunks across available servers with replication."""
        chunk_allocation = {}
        round_robin_index = 0

        for chunk_id in chunk_ids:
            servers = []
            for _ in range(REPLICATION_FACTOR):
                if not self.active_servers:
                    logging.error("No active servers available for chunk allocation.")
                    return None

                server = self.active_servers[round_robin_index]
                servers.append(server)
                round_robin_index = (round_robin_index + 1) % len(self.active_servers)

            self.chunk_locations[chunk_id] = servers
            for server in servers:
                self.chunk_servers_info[server].append(chunk_id)

            chunk_allocation[chunk_id] = servers
        return chunk_allocation

    def lease_file(self, filename, client_address):
        """Lease a file to a client for exclusive write access."""
        try:
            # Check if the file exists in the file map
            if filename not in self.file_map:
                logging.error("Lease request failed: File '%s' not found", filename)
                return {'status': 'error', 'message': f"File '{filename}' not found"}

            # Check if the file is already leased and the lease is still valid
            if filename in self.leases:
                lease_info = self.leases[filename]
                if lease_info['expires'] > time.time():
                    logging.warning("File '%s' is already leased by %s", filename, lease_info['client'])
                    return {
                        'status': 'error',
                        'message': f"File '{filename}' is already leased. Lease expires in {int(lease_info['expires'] - time.time())} seconds."
                    }

            # Grant lease and set expiration time
            self.leases[filename] = {
                'expires': time.time() + LEASE_DURATION,
                'client': client_address
            }
            logging.info("Leased file '%s' to client %s for %d seconds", filename, client_address, LEASE_DURATION)
            return {'status': 'success', 'message': f"File '{filename}' leased for {LEASE_DURATION} seconds."}
        except Exception as e:
            logging.error("Error processing lease for file '%s': %s", filename, e)
            return {'status': 'error', 'message': 'Server encountered an error while processing lease request'}

    def unlease_file(self, filename):
        """Release the lease on a file, allowing other clients to access it."""
        try:
            if filename not in self.leases:
                logging.warning("Unlease request failed: File '%s' was not leased", filename)
                return {'status': 'error', 'message': f"File '{filename}' was not leased"}

            del self.leases[filename]
            logging.info("Lease released for file '%s'", filename)
            return {'status': 'success', 'message': f"Lease released for file '{filename}'"}
        except Exception as e:
            logging.error("Error releasing lease for file '%s': %s", filename, e)
            return {'status': 'error', 'message': 'Server encountered an error while releasing lease'}

    def check_replication_integrity(self):
        """Periodically verify that each chunk has the correct replication level."""
        while True:
            time.sleep(HEARTBEAT_INTERVAL * 3)
            for chunk_id, servers in self.chunk_locations.items():
                if len(servers) < REPLICATION_FACTOR:
                    logging.warning("Chunk '%s' under-replicated. Current replicas: %s", chunk_id, servers)
                    self.reallocate_chunk(chunk_id, None)
    def heartbeat_monitor(self):
        """Monitor and validate chunk server heartbeats periodically."""
        while True:
            time.sleep(HEARTBEAT_INTERVAL)
            inactive_servers = set(CHUNK_PORTS) - set(self.active_servers)
            for port in inactive_servers:
                self.handle_server_failure(port)
            self.active_servers = list(set(CHUNK_PORTS) & set(self.active_servers))

    def lease_expiration_checker(self):
        """Periodically check and expire leases that have timed out."""
        while True:
            time.sleep(5)
            expired_leases = [filename for filename, lease in self.leases.items() if lease['expires'] < time.time()]
            for filename in expired_leases:
                del self.leases[filename]
                logging.info("Lease expired for file '%s'", filename)


if __name__ == "__main__":
    master = MasterServer('localhost', 7082)
    logging.info("Master Server Running on port 7082")
    master.start()