import { useState, useEffect } from 'react';
import { FileInfo, ActiveLeases } from '../types';

export function useGFSOperations() {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedOperation, setSelectedOperation] = useState('');
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [activeLeases, setActiveLeases] = useState<ActiveLeases>({});
  const [storageUsed, setStorageUsed] = useState(0); // Tracks total storage used in GFS

  useEffect(() => {
    fetchStorageUsed(); // Fetch storage used on component mount
    handleListFiles(); // Fetch initial list of files
  }, []);

  const fetchStorageUsed = () => {
    console.log("Fetching storage used...");
    fetch('http://localhost:7083/storage_used')
      .then(response => response.json())
      .then(data => {
        if (data.status === "success") {
          setStorageUsed(data.storageUsed);
        } else {
          console.error("Failed to fetch storage used:", data.message);
        }
      })
      .catch(error => console.error("Error fetching storage used:", error));
  };

  const handleServerResponse = (data: any) => {
    switch (data.command) {
      case 'list_files_response':
        if (data.status === 'success') {
          const formattedFiles = data.files.map((file: any) => ({
            id: file.name,
            name: file.name,
            size: file.size || 0, // Default to 0 if size is undefined
            lastModified: new Date(file.lastModified * 1000).toISOString(),
          }));
          setFiles(formattedFiles);
        } else {
          console.error(data.message);
        }
        break;
      case 'upload_response':
        if (data.status === 'success') {
          handleListFiles(); // Refresh file list
          fetchStorageUsed(); // Refresh storage used
        } else {
          console.error(data.message);
        }
        break;
      case 'download_response':
        if (data.status === 'success') {
          const blob = new Blob([data.fileContent], { type: 'text/plain' });
          const url = window.URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = data.fileName;
          a.click();
          window.URL.revokeObjectURL(url);
        } else {
          console.error(data.message);
        }
        break;
      case 'lease_response':
        if (data.status === 'success') {
          setActiveLeases(prev => ({ ...prev, [data.fileName]: true }));
        } else {
          console.error(data.message);
        }
        break;
      case 'unlease_response':
        if (data.status === 'success') {
          setActiveLeases(prev => {
            const updatedLeases = { ...prev };
            delete updatedLeases[data.fileName];
            return updatedLeases;
          });
        } else {
          console.error(data.message);
        }
        break;
      default:
        console.warn("Unknown response command:", data.command);
    }
  };

  const handleFileUpload = (file: File) => {
    const formData = new FormData();
    formData.append('file', file);

    fetch('http://localhost:7083/upload', { method: 'POST', body: formData })
      .then(response => response.json())
      .then(data => handleServerResponse({ command: 'upload_response', ...data }))
      .catch(error => console.error("Upload failed:", error));
  };

  const handleListFiles = () => {
    console.log("Listing files...");
    fetch('http://localhost:7083/list_files', { method: 'GET' })
      .then(response => response.json())
      .then(data => handleServerResponse({ command: 'list_files_response', ...data }))
      .catch(error => console.error("Failed to list files:", error));
  };

  // In useGFSOperations.ts
const handleLease = (fileName: string) => {
  fetch('http://localhost:7083/lease', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename: fileName })
  })
    .then(response => response.json())
    .then(data => {
      if (data.status === 'success') {
        setActiveLeases(prev => ({ ...prev, [fileName]: true }));
      } else {
        console.error("Lease request failed:", data.message);
      }
    })
    .catch(error => console.error("Lease request failed:", error));
};


  // In useGFSOperations.ts

  const handleUnlease = (fileName: string) => {
    fetch('http://localhost:7083/unlease', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: fileName })
    })
      .then(response => response.json())
      .then(data => {
        if (data.status === 'success') {
          // Remove the file from activeLeases to update its status to "Available"
          setActiveLeases(prev => {
            const updatedLeases = { ...prev };
            delete updatedLeases[fileName];
            return updatedLeases;
          });
        } else {
          console.error("Unlease request failed:", data.message);
        }
      })
      .catch(error => console.error("Unlease request failed:", error));
  };


  const handleDownload = (fileName: string) => {
    fetch('http://localhost:7083/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: fileName })
    })
      .then(response => response.blob())
      .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = fileName;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
      })
      .catch(error => console.error("Download failed:", error));
  };

  const handleOperation = (operation: string, data: any) => {
    switch (operation) {
      case 'upload':
        handleFileUpload(data.file);
        break;
      case 'download':
        handleDownload(data.fileName);
        break;
      case 'list_files':
        handleListFiles();
        break;
      case 'lease':
        handleLease(data.fileName);
        break;
      case 'unlease':
        handleUnlease(data.fileName);
        break;
      default:
        console.warn(`Unknown operation: ${operation}`);
    }
  };

  return {
    isModalOpen,
    setIsModalOpen,
    selectedOperation,
    setSelectedOperation,
    handleFileUpload,
    handleOperation,
    handleListFiles,
    handleDownload,
    handleLease,
    handleUnlease,
    files,
    activeLeases,
    storageUsed,
  };
}
