import socket
import os
import pickle
import hashlib
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

MASTER_SERVERS = [('localhost', 7084), ('localhost', 7085), ('localhost', 7086), ('localhost', 7087), ('localhost', 7088)]
CHUNK_SIZE = 2048


class Client:
    def __init__(self):
        self.leader_host = None
        self.leader_port = None

    def discover_leader(self):
        """Discover the current leader by contacting all masters."""
        for master_host, master_port in MASTER_SERVERS:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect((master_host, master_port))
                    request = {'type': 'client_query'}
                    s.send(pickle.dumps(request))
                    response = pickle.loads(s.recv(4096))
                    if response.get('status') == 'success':
                        self.leader_host = master_host
                        self.leader_port = master_port
                        logging.info("Discovered leader at %s:%d", master_host, master_port)
                        return True
                    elif response.get('status') == 'redirect':
                        self.leader_host = 'localhost'
                        self.leader_port = response.get('leader')
                        logging.info("Leader is at %s:%d", self.leader_host, self.leader_port)
                        return True
            except Exception as e:
                logging.error("Failed to contact master at %s:%d - %s", master_host, master_port, e)
        logging.error("Could not discover leader")
        return False

    def send_request_to_leader(self, request):
        """Send a request to the leader master server."""
        if not self.leader_host or not self.leader_port:
            if not self.discover_leader():
                return {"status": "error", "message": "Could not discover leader"}

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as master_sock:
                master_sock.connect((self.leader_host, self.leader_port))
                master_sock.send(pickle.dumps(request))
                response = pickle.loads(master_sock.recv(4096))

            if response.get('status') == 'redirect':
                self.leader_port = response.get('leader')
                logging.info("Redirected to leader at port %d", self.leader_port)
                return self.send_request_to_leader(request)
            else:
                return response

        except Exception as e:
            logging.error("Error communicating with leader: %s", e)
            self.leader_host = None
            self.leader_port = None
            return {"status": "error", "message": str(e)}

    def upload_file(self, filename):
        """Upload a file to the distributed file system."""
        if not os.path.isfile(filename):
            logging.error("File %s does not exist", filename)
            return {"status": "error", "message": "File does not exist"}

        file_size = os.path.getsize(filename)
        num_chunks = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE
        logging.info("Uploading file %s, size %d bytes, %d chunks", filename, file_size, num_chunks)

        upload_request = {'command': 'upload', 'filename': filename, 'file_size': file_size}
        response = self.send_request_to_leader(upload_request)

        if response.get('status') != 'success':
            logging.error("Failed to upload file: %s", response.get('message'))
            return {"status": "error", "message": response.get("message")}

        chunk_allocation = response.get('chunks')
        with open(filename, 'rb') as f:
            for chunk_id, servers in chunk_allocation.items():
                data = f.read(CHUNK_SIZE)
                checksum = self.calculate_checksum(data)

                for server_port in servers:
                    self.send_chunk(server_port, filename, chunk_id, data, checksum)

        return {"status": "success", "message": f"File {filename} uploaded successfully"}

    def calculate_checksum(self, data):
        """Calculate the checksum of data for integrity checks."""
        return hashlib.sha256(data).hexdigest()

    def send_chunk(self, server_port, filename, chunk_id, data, checksum):
        """Send a single chunk to a ChunkServer."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(('localhost', server_port))
                chunk_request = {'command': 'store', 'filename': filename, 'chunk_id': chunk_id, 'data': data, 'checksum': checksum}
                s.send(pickle.dumps(chunk_request))
                response = pickle.loads(s.recv(4096))

                if response.get('status') == 'success':
                    logging.info("Successfully stored chunk %s on server %d", chunk_id, server_port)
                else:
                    logging.error("Failed to store chunk %s on server %d: %s", chunk_id, server_port, response.get('message'))
        except Exception as e:
            logging.error("Error sending chunk %s to server %d: %s", chunk_id, server_port, e)

    def download_file(self, filename):
        """Download a file from the distributed file system."""
        request = {'command': 'download', 'filename': filename}
        response = self.send_request_to_leader(request)

        if response.get('status') != 'success':
            logging.error("Failed to download file: %s", response.get('message'))
            return {"status": "error", "message": response.get("message")}

        chunk_locations = response.get('chunk_locations')
        if not chunk_locations:
            logging.error("No chunks found for file %s", filename)
            return {"status": "error", "message": "No chunks found for file"}

        file_path = f"downloaded_{filename}"
        with open(file_path, 'wb') as f:
            for chunk_id, servers in chunk_locations.items():
                data = self.retrieve_chunk(servers, filename, chunk_id)
                if data:
                    f.write(data)
                else:
                    logging.error("Failed to retrieve chunk %s for file %s", chunk_id, filename)
                    return {"status": "error", "message": f"Failed to retrieve chunk {chunk_id}"}

        logging.info("File %s downloaded successfully as %s", filename, file_path)
        return {"status": "success", "message": f"File downloaded successfully", "path": file_path}

    def retrieve_chunk(self, servers, filename, chunk_id):
        """Retrieve a chunk from available servers and verify its checksum."""
        for server_port in servers:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect(('localhost', server_port))
                    download_request = {'command': 'download', 'filename': filename, 'chunk_id': chunk_id}
                    s.send(pickle.dumps(download_request))
                    response = pickle.loads(s.recv(4096))

                if response.get('status') == 'success':
                    data = response['data']
                    checksum = response['checksum']
                    if self.calculate_checksum(data) == checksum:
                        logging.info("Successfully retrieved and verified chunk %s from server %d", chunk_id, server_port)
                        return data
                    else:
                        logging.warning("Checksum mismatch for chunk %s from server %d, trying next server", chunk_id, server_port)
            except Exception as e:
                logging.error("Failed to retrieve chunk %s from server %d: %s", chunk_id, server_port, e)
        return None
    
    def lease_file(self, filename):
        """Request an exclusive lease on a file."""
        request = {'command': 'lease', 'filename': filename}
        response = self.send_request_to_leader(request)

        if response.get('status') == 'success':
            logging.info("Lease granted for file %s", filename)
            return {"status": "success", "message": f"Lease granted for file {filename}"}
        else:
            logging.warning("Lease request failed for file %s: %s", filename, response.get('message'))
            return {"status": "error", "message": response.get("message")}

    def unlease_file(self, filename):
        """Release the exclusive lease on a file."""
        request = {'command': 'unlease', 'filename': filename}
        response = self.send_request_to_leader(request)

        if response.get('status') == 'success':
            logging.info("Lease released for file %s", filename)
            return {"status": "success", "message": f"Lease released for file {filename}"}
        else:
            logging.warning("Failed to release lease for file %s: %s", filename, response.get('message'))
            return {"status": "error", "message": response.get("message")}


if __name__ == "__main__":
    client = Client()
    # Example usage:
    client.upload_file('example.txt')
    client.download_file('example.txt')
