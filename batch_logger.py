import json
import time
import queue
import threading
import psycopg2
from psycopg2 import sql
import os

class BatchLogger:
    def __init__(self):
        self.log_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._log_worker, daemon=True)
        self.worker_thread.start()
        self.lock = threading.Lock()
        self.DATABASE_URL = os.environ.get('DATABASE_URL')

    def log_batch_status(self, batch_id, status, user_token):
        self.log_queue.put((batch_id, status, user_token))

    def _log_worker(self):
        while True:
            batch_id, status, user_token = self.log_queue.get()
            self._write_log(batch_id, status, user_token)
            self.log_queue.task_done()

    def _write_log(self, batch_id, status, user_token):
        with self.lock:
            conn = psycopg2.connect(self.DATABASE_URL)
            c = conn.cursor()
            
            # Create the batch_logs table if it doesn't exist
            c.execute('''
                CREATE TABLE IF NOT EXISTS batch_logs (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    batch_id TEXT,
                    status TEXT,
                    user_token TEXT,
                    total_requests INTEGER,
                    completed_requests INTEGER,
                    failed_requests INTEGER,
                    created_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    input_file_id TEXT,
                    output_file_id TEXT,
                    remaining_balance INTEGER,
                    completion_window TEXT,
                    endpoint TEXT,
                    metadata TEXT,
                    processing_rate FLOAT,
                    overall_processing_rate FLOAT,
                    estimated_remaining_time FLOAT,
                    total_elapsed_time FLOAT
                )
            ''')
            
            # Insert the log entry
            c.execute('''
                INSERT INTO batch_logs (
                    batch_id, status, user_token, total_requests, completed_requests, 
                    failed_requests, created_at, completed_at, input_file_id, output_file_id,
                    remaining_balance, completion_window, endpoint, metadata, processing_rate,
                    overall_processing_rate, estimated_remaining_time, total_elapsed_time
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                batch_id,
                status['status'],
                user_token,
                status['request_counts']['total'],
                status['request_counts']['completed'],
                status['request_counts']['failed'],
                status['created_at'],
                status.get('completed_at'),
                status['input_file_id'],
                status.get('output_file_id'),
                status.get('remaining_balance'),
                status['completion_window'],
                status['endpoint'],
                json.dumps(status.get('metadata', {})),
                status.get('processing_rate', 0),
                status.get('overall_processing_rate', 0),
                status.get('estimated_remaining_time', 0),
                status.get('total_elapsed_time', 0)
            ))
            
            conn.commit()
            conn.close()

batch_logger = BatchLogger()
