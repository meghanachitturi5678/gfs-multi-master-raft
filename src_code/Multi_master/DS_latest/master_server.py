import socket
import threading
import pickle
import time
import random
import logging

from flask import jsonify

# Main application log
logging.basicConfig(filename='master_server.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Separate log for tracking masters and leader
masters_log_file = 'masters.log'
# Clear the log file
open(masters_log_file, 'w').close()
masters_logger = logging.getLogger('MastersLogger')
masters_logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(masters_log_file)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
masters_logger.addHandler(file_handler)

CHUNK_PORTS = [6471, 6472, 6473, 6474]
REPLICATION_FACTOR = 2
HEARTBEAT_INTERVAL = 5
ELECTION_TIMEOUT = (15, 30)  # Election timeout range in seconds
MASTER_SERVERS = [('localhost', 7084), ('localhost', 7085), ('localhost', 7086), ('localhost', 7087), ('localhost', 7088)]
LEASE_DURATION = 30     # Lease duration in seconds

class MasterServer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.file_map = {}
        self.chunk_locations = {}
        self.chunk_servers_info = {p: [] for p in CHUNK_PORTS}
        self.active_servers = {p[1]: False for p in MASTER_SERVERS}
        self.leases = {}

        # Raft consensus variables
        self.current_term = 0
        self.voted_for = None
        self.log = []
        self.commit_index = -1
        self.last_applied = -1

        self.state = 'follower'
        self.leader_id = None
        self.election_timeout = random.uniform(*ELECTION_TIMEOUT)
        self.last_heartbeat = time.time()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind((self.host, self.port))
        logging.info("Master Server initialized on host %s, port %d", host, port)

    def start(self):
        """Start the master server and begin listening for connections."""
        threading.Thread(target=self.run_server).start()
        threading.Thread(target=self.run_raft).start()
        threading.Thread(target=self.monitor_masters).start()

    def run_server(self):
        """Handle incoming connections."""
        self.sock.listen(5)
        logging.info("Master Server started, listening on port %d", self.port)
        while True:
            client, address = self.sock.accept()
            threading.Thread(target=self.handle_connection, args=(client, address)).start()

    def run_raft(self):
        """Run the Raft consensus algorithm."""
        while True:
            if self.state == 'leader':
                self.send_heartbeats()
                time.sleep(HEARTBEAT_INTERVAL)
            elif self.state == 'follower':
                if time.time() - self.last_heartbeat > self.election_timeout:
                    self.state = 'candidate'
            elif self.state == 'candidate':
                self.start_election()
            time.sleep(0.1)

    def start_election(self):
        """Start an election to become the leader."""
        self.current_term += 1
        self.voted_for = self.port
        votes = 1
        active_masters = [port for port, active in self.active_servers.items() if active]
        quorum = len(active_masters) // 2 + 1  # Recalculate quorum dynamically
        logging.info("Server %d starting election for term %d", self.port, self.current_term)
        logging.info("Active masters: %s, Quorum required: %d", active_masters, quorum)

        for master in MASTER_SERVERS:
            if master[1] == self.port or master[1] not in active_masters:
                continue
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect(master)
                    request = {'type': 'RequestVote', 'term': self.current_term, 'candidate_id': self.port}
                    s.send(pickle.dumps(request))
                    response = pickle.loads(s.recv(4096))
                    if response.get('vote_granted'):
                        votes += 1
            except Exception as e:
                logging.error("Election: Failed to contact master %s:%d - %s", master[0], master[1], e)
        if votes >= quorum:
            self.state = 'leader'
            self.leader_id = self.port
            logging.info("Server %d became leader for term %d", self.port, self.current_term)
            self.log_active_masters()
        else:
            self.state = 'follower'
            self.voted_for = None
            self.election_timeout = random.uniform(*ELECTION_TIMEOUT)

    def send_heartbeats(self):
        """Send heartbeats to all followers."""
        for master in MASTER_SERVERS:
            if master[1] == self.port:
                continue
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect(master)
                    request = {'type': 'AppendEntries', 'term': self.current_term, 'leader_id': self.port}
                    s.send(pickle.dumps(request))
            except Exception as e:
                logging.error("Heartbeat: Failed to contact master %s:%d - %s", master[0], master[1], e)

    def handle_connection(self, client, address):
        """Handle incoming connections from clients and other masters."""
        try:
            request = pickle.loads(client.recv(4096))
            req_type = request.get('type')

            if req_type == 'RequestVote':
                response = self.handle_request_vote(request)
                client.send(pickle.dumps(response))

            elif req_type == 'AppendEntries':
                self.handle_append_entries(request)

            else:
                if self.state != 'leader':
                    response = {'status': 'redirect', 'leader': self.leader_id}
                    client.send(pickle.dumps(response))
                else:
                    response = self.handle_client_request(request)
                    client.send(pickle.dumps(response))

        except Exception as e:
            logging.error("Error handling connection: %s", e)
        finally:
            client.close()

    def handle_request_vote(self, request):
        """Handle RequestVote RPC from candidates."""
        term = request.get('term')
        candidate_id = request.get('candidate_id')
        if term > self.current_term:
            self.current_term = term
            self.voted_for = None
            self.state = 'follower'
        vote_granted = False
        if (self.voted_for is None or self.voted_for == candidate_id) and term >= self.current_term:
            self.voted_for = candidate_id
            vote_granted = True
            self.last_heartbeat = time.time()
        logging.info("Server %d voted for %d in term %d", self.port, candidate_id, term)
        return {'term': self.current_term, 'vote_granted': vote_granted}

    def handle_append_entries(self, request):
        """Handle AppendEntries (heartbeat) from leader."""
        term = request.get('term')
        leader_id = request.get('leader_id')
        if term >= self.current_term:
            self.current_term = term
            self.state = 'follower'
            self.leader_id = leader_id
            self.last_heartbeat = time.time()
            logging.info("Server %d received heartbeat from leader %d for term %d", self.port, leader_id, term)
        self.log_active_masters()

    def monitor_masters(self):
        """Periodically monitor the status of other master servers."""
        while True:
            for master_host, master_port in MASTER_SERVERS:
                if master_port == self.port:
                    self.active_servers[master_port] = True
                    continue
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.connect((master_host, master_port))
                        self.active_servers[master_port] = True
                except Exception:
                    self.active_servers[master_port] = False
            self.log_active_masters()
            time.sleep(HEARTBEAT_INTERVAL)

    def log_active_masters(self):
        """Log active masters and the current leader."""
        active_master_ports = [port for port, active in self.active_servers.items() if active]
        leader_status = f"Current leader: {self.leader_id if self.leader_id else 'None'}"

        # Log to masters.log
        masters_logger.info("Active masters: %s", active_master_ports)
        masters_logger.info(leader_status)


    def handle_upload(self, filename, file_size):
        """Handle file upload requests by allocating chunks and assigning servers."""
        if filename in self.file_map:
            return {'status': 'error', 'message': 'File already exists'}
        
        
        # If none of the master ports are available, return an error
        # No active servers available
        if not any(self.active_servers.values()):
            return {'status': 'error', 'message': 'No active servers available'}

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

    def lease_file(self, filename, client_address):
        """Lease a file to a client for exclusive write access."""
        if filename in self.leases and self.leases[filename]['expires'] > time.time():
            return {'status': 'error', 'message': f'File {filename} is already leased.'}

        self.leases[filename] = {'expires': time.time() + LEASE_DURATION, 'client': client_address}
        logging.info("Leased file '%s' to client %s for %d seconds", filename, client_address, LEASE_DURATION)
        return {'status': 'success', 'message': f'File {filename} leased for {LEASE_DURATION} seconds.'}

    def unlease_file(self, filename):
        """Release a lease on a file."""
        if filename in self.leases:
            del self.leases[filename]
            logging.info("Unleased file '%s'", filename)
            return {'status': 'success', 'message': f'File {filename} has been unleased.'}
        return {'status': 'error', 'message': f'File {filename} was not leased.'}

    def allocate_chunks(self, chunk_ids):
        """Allocate chunks across available servers with replication."""
        chunk_allocation = {}
        for chunk_id in chunk_ids:
            servers = self.select_chunk_servers(REPLICATION_FACTOR)
            if not servers:
                logging.error("Failed to allocate chunk '%s': No active servers", chunk_id)
                return None

            self.chunk_locations[chunk_id] = servers
            for server in servers:
                self.chunk_servers_info[server].append(chunk_id)

            chunk_allocation[chunk_id] = servers
        return chunk_allocation

    def select_chunk_servers(self, replication_factor):
        """Select servers for chunk replication based on their load."""
        active_servers_info = {s: self.chunk_servers_info[s] for s in self.active_servers}
        available_servers = sorted(active_servers_info.items(), key=lambda x: len(x[1]))
        return [server for server, _ in available_servers[:replication_factor]]

    def update_server_status(self, port):
        """Update the status of a chunk server based on heartbeat signals."""
        self.active_servers.add(port)
        logging.info("Server on port %d is now active", port)

    def heartbeat_monitor(self):
        """Monitor and validate chunk server heartbeats periodically."""
        while True:
            time.sleep(HEARTBEAT_INTERVAL)
            inactive_servers = set(CHUNK_PORTS) - self.active_servers
            for port in inactive_servers:
                self.handle_server_failure(port)
            self.active_servers.clear()

    def handle_server_failure(self, port):
        """Handle chunk server failure by reallocating chunks."""
        logging.warning("Chunk server on port %d has failed", port)
        if port in self.chunk_servers_info:
            for chunk_id in self.chunk_servers_info[port]:
                self.reallocate_chunk(chunk_id, port)
            self.chunk_servers_info[port] = []

    def reallocate_chunk(self, chunk_id, failed_server):
        """Reallocate chunk replicas when a server goes down."""
        if chunk_id in self.chunk_locations:
            self.chunk_locations[chunk_id] = [s for s in self.chunk_locations[chunk_id] if s != failed_server]
            if len(self.chunk_locations[chunk_id]) < REPLICATION_FACTOR:
                new_servers = self.select_chunk_servers(1)
                if new_servers:
                    new_server = new_servers[0]
                    self.chunk_locations[chunk_id].append(new_server)
                    self.chunk_servers_info[new_server].append(chunk_id)
                    logging.info("Reallocated chunk '%s' to server on port %d", chunk_id, new_server)

    def check_replication_integrity(self):
        """Periodically verify that each chunk has the correct replication level."""
        while True:
            time.sleep(HEARTBEAT_INTERVAL * 3)
            for chunk_id, servers in self.chunk_locations.items():
                if len(servers) < REPLICATION_FACTOR:
                    logging.warning("Chunk '%s' under-replicated. Current replicas: %s", chunk_id, servers)
                    self.reallocate_chunk(chunk_id, None)

    def lease_expiration_checker(self):
        """Periodically check and expire leases that have timed out."""
        while True:
            time.sleep(5)
            expired_leases = [filename for filename, lease in self.leases.items() if lease['expires'] < time.time()]
            for filename in expired_leases:
                del self.leases[filename]
                logging.info("Lease expired for file '%s'", filename)

if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python master_server.py <port>")
        sys.exit(1)

    port = int(sys.argv[1])
    master = MasterServer('localhost', port)
    logging.info("Master Server Running on port %d", port)
    master.start()
