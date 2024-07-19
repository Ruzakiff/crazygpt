import csv
import os
from datetime import datetime
import json
import time
import queue
import threading

class BatchLogger:
    def __init__(self, log_file='batch_status_log.csv'):
        self.log_file = log_file
        self.last_logged_state = {}
        self.log_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._log_worker, daemon=True)
        self.worker_thread.start()
        self.lock = threading.Lock()

    def log_batch_status(self, batch_id, status, user_token):
        # Instead of writing directly, add to queue
        self.log_queue.put((batch_id, status, user_token))

    def _log_worker(self):
        while True:
            batch_id, status, user_token = self.log_queue.get()
            self._write_log(batch_id, status, user_token)
            self.log_queue.task_done()

    def _write_log(self, batch_id, status, user_token):
        with self.lock:
            file_exists = os.path.isfile(self.log_file)
            
            current_time = time.time()
            current_time_iso = datetime.fromtimestamp(current_time).isoformat()
            
            # Calculate time since last log and request increment
            last_state = self.last_logged_state.get(batch_id, {})
            time_since_last_log = current_time - last_state.get('timestamp', current_time)
            completed_increment = status['request_counts']['completed'] - last_state.get('completed_requests', 0)
            failed_increment = status['request_counts']['failed'] - last_state.get('failed_requests', 0)
            
            # Handle case where there's no progress
            if completed_increment == 0 and failed_increment == 0:
                time_per_request = 0
                processing_rate = 0
            else:
                time_per_request = time_since_last_log / (completed_increment + failed_increment) if (completed_increment + failed_increment) > 0 else 0
                processing_rate = completed_increment / time_since_last_log if time_since_last_log > 0 else 0

            # Calculate overall processing rate
            total_time = current_time - status['created_at']
            overall_processing_rate = status['request_counts']['completed'] / total_time if total_time > 0 else 0

            # Estimate remaining time
            remaining_requests = status['request_counts']['total'] - status['request_counts']['completed'] - status['request_counts']['failed']
            estimated_remaining_time = remaining_requests / overall_processing_rate if overall_processing_rate > 0 else 0

            data = {
                'timestamp': current_time_iso,
                'batch_id': batch_id,
                'status': status['status'],
                'user_token': user_token,
                'total_requests': status['request_counts']['total'],
                'completed_requests': status['request_counts']['completed'],
                'failed_requests': status['request_counts']['failed'],
                'created_at': datetime.fromtimestamp(status['created_at']).isoformat(),
                'completed_at': datetime.fromtimestamp(status['completed_at']).isoformat() if status.get('completed_at') else '',
                'input_file_id': status['input_file_id'],
                'output_file_id': status.get('output_file_id', ''),
                'remaining_balance': status.get('remaining_balance', ''),
                'completion_window': status['completion_window'],
                'endpoint': status['endpoint'],
                'metadata': json.dumps(status.get('metadata', {})),
                'time_since_last_log': time_since_last_log,
                'completed_increment': completed_increment,
                'failed_increment': failed_increment,
                'time_per_request': time_per_request,
                'processing_rate': processing_rate,
                'overall_processing_rate': overall_processing_rate,
                'estimated_remaining_time': estimated_remaining_time,
                'total_elapsed_time': total_time,
            }
            
            with open(self.log_file, 'a', newline='') as csvfile:
                fieldnames = data.keys()
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                if not file_exists:
                    writer.writeheader()
                
                writer.writerow(data)

            # Update the last logged state
            self.last_logged_state[batch_id] = {
                'timestamp': current_time,
                'completed_requests': status['request_counts']['completed'],
                'failed_requests': status['request_counts']['failed'],
            }

batch_logger = BatchLogger()
