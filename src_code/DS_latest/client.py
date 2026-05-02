import socket
import os
import pickle
import hashlib
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

MASTER_SERVER_PORT = 7082
CHUNK_SIZE = 2048  # Consistent with the chunk size used in Master and ChunkServer

class Client:
    def __init__(self, master_host='localhost', master_port=MASTER_SERVER_PORT):
        self.master_host = master_host
        self.master_port = master_port

    def calculate_checksum(self, data):
        """Calculate the checksum of data for integrity checks."""
        return hashlib.sha256(data).hexdigest()

    def safe_recv(self, sock, buffer_size=4096):
        """Safely receive data from a socket and handle empty or malformed responses."""
        try:
            data = sock.recv(buffer_size)
            if not data:
                raise ValueError("Received empty response from the server")
            return pickle.loads(data)
        except (pickle.UnpicklingError, EOFError, ValueError) as e:
            logging.error("Failed to decode server response: %s", e)
            return {"status": "error", "message": "Malformed or empty response from server"}
        except Exception as e:
            logging.error("Error receiving data from server: %s", e)
            return {"status": "error", "message": "Failed to receive response from server"}

    def upload_file(self, filename):
        """Upload a file to the distributed file system."""
        if not os.path.isfile(filename):
            logging.error("File %s does not exist", filename)
            return {"status": "error", "message": "File does not exist"}

        file_size = os.path.getsize(filename)
        num_chunks = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE
        logging.info("Uploading file %s, size %d bytes, %d chunks", filename, file_size, num_chunks)

        # Request chunk allocation from the master server
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as master_sock:
            master_sock.connect((self.master_host, self.master_port))
            upload_request = {'command': 'upload', 'filename': filename, 'file_size': file_size}
            master_sock.send(pickle.dumps(upload_request))
            response = self.safe_recv(master_sock)

        if response.get('status') != 'success':
            logging.error("Failed to upload file: %s", response.get('message'))
            return {"status": "error", "message": response.get("message")}

        chunk_allocation = response.get('chunks')
        base_filename, _ = os.path.splitext(os.path.basename(filename))

        # Read and send chunks to allocated servers
        with open(filename, 'rb') as f:
            for chunk_id, servers in chunk_allocation.items():
                data = f.read(CHUNK_SIZE)
                checksum = self.calculate_checksum(data)

                # Send each chunk to all allocated servers for replication
                for server_port in servers:
                    self.send_chunk(server_port, base_filename, chunk_id, data, checksum)

        logging.info("File %s uploaded successfully.", filename)
        return {"status": "success", "message": f"File {filename} uploaded successfully"}

    def send_chunk(self, server_port, base_filename, chunk_id, data, checksum):
        """Send a single chunk to a ChunkServer."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(('localhost', server_port))
                chunk_request = {
                    'command': 'store',
                    'filename': base_filename,
                    'chunk_id': chunk_id,
                    'data': data,
                    'checksum': checksum
                }
                s.send(pickle.dumps(chunk_request))
                response = self.safe_recv(s)

                if response.get('status') == 'success':
                    logging.info("Successfully stored chunk %s on server %d", chunk_id, server_port)
                else:
                    logging.error("Failed to store chunk %s on server %d: %s", chunk_id, server_port, response.get('message'))
        except Exception as e:
            logging.error("Error sending chunk %s to server %d: %s", chunk_id, server_port, e)

    def lease_file(self, filename):
        """Request an exclusive lease on a file."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as master_sock:
                master_sock.connect((self.master_host, self.master_port))
                lease_request = {'command': 'lease', 'filename': filename}
                master_sock.send(pickle.dumps(lease_request))
                
                # Safely receive the response
                response = self.safe_recv(master_sock)
                
                # Validate the response
                if not response or not isinstance(response, dict):
                    logging.warning("Received invalid or empty response for lease request.")
                    return {"status": "error", "message": "Malformed or empty response from server"}

                if response.get('status') == 'success':
                    logging.info("Lease granted for file %s", filename)
                    return {"status": "success", "message": f"Lease granted for file {filename}"}
                else:
                    logging.warning("Lease request failed for file %s: %s", filename, response.get('message'))
                    return {"status": "error", "message": response.get("message")}
        except Exception as e:
            logging.error("Failed to lease file %s: %s", filename, e)
            return {"status": "error", "message": "Failed to lease file due to an error"}

    def unlease_file(self, filename):
        """Release the exclusive lease on a file."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as master_sock:
                master_sock.connect((self.master_host, self.master_port))
                unlease_request = {'command': 'unlease', 'filename': filename}
                master_sock.send(pickle.dumps(unlease_request))
                response = self.safe_recv(master_sock)

            if response.get('status') == 'success':
                logging.info("Lease released for file %s", filename)
                return {"status": "success", "message": f"Lease released for file {filename}"}
            else:
                logging.warning("Failed to release lease for file %s: %s", filename, response.get('message'))
                return {"status": "error", "message": response.get("message")}
        except Exception as e:
            logging.error("Failed to unlease file %s: %s", filename, e)
            return {"status": "error", "message": "Failed to unlease file due to an error"}

    # Additional methods for download_file, retrieve_chunk, and list_files would remain unchanged
    
    def download_file(self, filename):
        """Download a file from the distributed file system."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as master_sock:
            master_sock.connect((self.master_host, self.master_port))
            download_request = {'command': 'download', 'filename': filename}
            master_sock.send(pickle.dumps(download_request))
            response = pickle.loads(master_sock.recv(4096))

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

    def list_files(self):
        """Request a list of files from the MasterServer and return the list."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as master_sock:
            master_sock.connect((self.master_host, self.master_port))
            list_request = {'command': 'list_files'}
            master_sock.send(pickle.dumps(list_request))
            response = pickle.loads(master_sock.recv(4096))

        if isinstance(response, list):
            logging.info("Files available on the server: %s", response)
            return {"status": "success", "files": response}
        else:
            logging.error("Failed to retrieve file list: %s", response.get('message'))
            return {"status": "error", "message": response.get("message")}