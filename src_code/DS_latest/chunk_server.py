import socket
import threading
import os
import sys
import pickle
import hashlib
import logging
import time

logging.basicConfig(filename='chunk_server.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

MASTER_PORT = 7082  # Primary Master Port
HEARTBEAT_INTERVAL = 5

class ChunkServer:
    def __init__(self, host, port, base_directory):
        self.base_directory = base_directory  # Base directory for this chunk server
        self.host = host
        self.port = port
        self.chunkserver_info = []  # List of stored chunks
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))

        # Ensure base directory exists
        os.makedirs(self.base_directory, exist_ok=True)

        logging.info("Chunk Server initialized on host %s, port %d", host, port)

    def start(self):
        """Start the chunk server, begin listening and send periodic heartbeats."""
        threading.Thread(target=self.send_heartbeat).start()
        self.listen()

    def listen(self):
        """Listen for incoming connections and handle each in a separate thread."""
        self.sock.listen(5)
        logging.info("Chunk Server started, listening on port %d", self.port)
        while True:
            client, address = self.sock.accept()
            client.settimeout(60)
            threading.Thread(target=self.handle_request, args=(client, address)).start()

    def send_heartbeat(self):
        """Send periodic heartbeat messages to the MasterServer to indicate server activity."""
        while True:
            time.sleep(HEARTBEAT_INTERVAL)
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect((socket.gethostbyname('localhost'), MASTER_PORT))
                    heartbeat_message = {'command': 'heartbeat', 'port': self.port}
                    s.send(pickle.dumps(heartbeat_message))
                logging.info("Heartbeat sent to MasterServer from port %d", self.port)
            except Exception as e:
                logging.error("Failed to send heartbeat: %s", e)

    def calculate_checksum(self, data):
        """Calculate the checksum of data for integrity checks."""
        return hashlib.sha256(data).hexdigest()

    def store_chunk(self, client, chunk_id, filename, data, checksum, is_replica=False):
        """Store chunk data from client, ensuring data integrity."""
        try:
            # Generate chunk file name (e.g., abhi_chunk_0.txt)
            chunk_suffix = "_replica" if is_replica else ""
            chunk_name = f"{chunk_id}{chunk_suffix}.txt"
            chunk_path = os.path.join(self.base_directory, chunk_name)

            # Check if chunk already exists
            if os.path.exists(chunk_path):
                logging.warning("Chunk %s already exists. Skipping storage.", chunk_name)
                return {'status': 'error', 'message': 'Chunk already exists'}

            # Verify checksum
            if self.calculate_checksum(data) != checksum:
                logging.error("Checksum mismatch for chunk %s, possible data corruption.", chunk_name)
                return {'status': 'error', 'message': 'Checksum mismatch'}

            # Save the chunk data
            with open(chunk_path, 'wb') as f:
                f.write(data)

            logging.info("Stored chunk %s successfully in %s.", chunk_name, chunk_path)
            self.chunkserver_info.append(chunk_name)
            return {'status': 'success'}
        except Exception as e:
            logging.error("Failed to store chunk %s: %s", chunk_id, e)
            return {'status': 'error', 'message': str(e)}

    def handle_request(self, client, address):
        """Handle client and chunk server requests."""
        try:
            request = pickle.loads(client.recv(4096))
            command = request.get('command')

            if command == 'store':
                filename = request['filename']
                chunk_id = request['chunk_id']
                data = request['data']
                checksum = request['checksum']
                response = self.store_chunk(client, chunk_id, filename, data, checksum)
                client.send(pickle.dumps(response))

            elif command == 'download':
                filename = request['filename']
                chunk_id = request['chunk_id']
                response = self.send_chunk(client, chunk_id)
                client.send(pickle.dumps(response))

            elif command == 'replicate':
                filename = request['filename']
                chunk_id = request['chunk_id']
                data = request['data']
                checksum = request['checksum']
                response = self.store_chunk(client, chunk_id, filename, data, checksum, is_replica=True)
                client.send(pickle.dumps(response))

            client.close()
        except Exception as e:
            logging.error("Error handling request from %s: %s", address, e)
        finally:
            client.close()

    def send_chunk(self, client, chunk_id):
        """Send the requested chunk to client, including checksum for verification."""
        try:
            # Generate chunk file name
            chunk_name = f"{chunk_id}.txt"
            chunk_path = os.path.join(self.base_directory, chunk_name)

            with open(chunk_path, 'rb') as f:
                data = f.read()
                checksum = self.calculate_checksum(data)
                return {'status': 'success', 'data': data, 'checksum': checksum}
        except FileNotFoundError:
            logging.error("Requested chunk %s not found", chunk_id)
            return {'status': 'error', 'message': 'Chunk not found'}
        except Exception as e:
            logging.error("Failed to send chunk %s: %s", chunk_id, e)
            return {'status': 'error', 'message': str(e)}


if __name__ == "__main__":
    try:
        port_num = int(sys.argv[1])
        base_directory = os.path.join(os.getcwd(), f"chunk_server_{port_num}")  # Base directory for this server
        os.makedirs(base_directory, exist_ok=True)  # Ensure the base directory exists
        chunk_server = ChunkServer('localhost', port_num, base_directory)
        logging.info("Starting Chunk Server on port %d", port_num)
        chunk_server.start()
    except Exception as e:
        logging.critical("Failed to start chunk server: %s", e)
        sys.exit(1)
