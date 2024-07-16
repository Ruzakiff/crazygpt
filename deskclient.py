import json
import os
import base64
import requests
from typing import List, Dict
from PIL import Image
from pillow_heif import register_heif_opener
import time
import io
import random
import uuid

register_heif_opener()

MAX_REQUESTS_PER_FILE = 50000
MAX_FILE_SIZE_MB = 100

class DeskClient:
    def __init__(self, server_url, user_token):
        self.requests = []
        self.server_url = server_url
        self.user_token = user_token

    def process_folder(self, folder_path: str):
        # Clear previous requests
        self.requests = []

        if not os.path.isdir(folder_path):
            print(f"Error: The folder '{folder_path}' does not exist.")
            return False

        processed_images = 0
        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)
            if os.path.isfile(file_path) and self.is_image(file_path):
                print(f"Processing image: {filename}")
                self.process_image(file_path)
                processed_images += 1

        if processed_images == 0:
            print("No images were processed. The folder might be empty or contain no valid images.")
            return False

        return True

    def process_image(self, file_path: str):
        original_path = file_path
        if file_path.lower().endswith('.heic'):
            file_path = self.convert_heic_to_jpg(file_path)

        with open(file_path, "rb") as image_file:
            image_data = image_file.read()

        # Use the full original path in the custom_id
        custom_id = f"request-{original_path}"
        self.add_request(
            custom_id=custom_id,
            method="POST",
            url="/v1/chat/completions",
            body={
                "model": "gpt-4o",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "DELETE all photos of woman/girls and animals. Include to be deleted images that may seem controversial and disrepectful in the eyes of my controlling girlfriend. output only either DELETE OR KEEP"
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64.b64encode(image_data).decode('utf-8')}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 256,
                "temperature": 0,
                "top_p": 1,
                "frequency_penalty": 0,
                "presence_penalty": 0
            }
        )

    def add_request(self, custom_id: str, method: str, url: str, body: Dict):
        request = {
            "custom_id": custom_id,
            "method": method,
            "url": url,
            "body": body
        }
        self.requests.append(request)

    def create_batch_jsonl(self, output_file_base: str):
        file_index = 1
        requests_processed = 0
        total_requests = len(self.requests)

        while requests_processed < total_requests:
            output_file = f"{output_file_base}_{file_index}.jsonl"
            with open(output_file, 'w') as f:
                file_size = 0
                requests_count = 0

                while requests_processed < total_requests:
                    request = self.requests[requests_processed]
                    json_line = json.dumps(request) + '\n'
                    line_size = len(json_line.encode('utf-8'))

                    if requests_count >= MAX_REQUESTS_PER_FILE or \
                       file_size + line_size > MAX_FILE_SIZE_MB * 1024 * 1024:
                        break

                    f.write(json_line)
                    file_size += line_size
                    requests_count += 1
                    requests_processed += 1

            print(f"Created JSONL file '{output_file}' with {requests_count} requests.")
            print(f"File size: {file_size / (1024 * 1024):.2f} MB")
            file_index += 1

        print(f"Total requests processed: {requests_processed}")
        print(f"Total files created: {file_index - 1}")

    def upload_jsonl(self, file_path: str):
        url = f"{self.server_url}/upload_jsonl"
        headers = {
            'User-Token': self.user_token
        }
        with open(file_path, 'rb') as file:
            files = {'file': (os.path.basename(file_path), file, 'application/jsonl')}
            response = requests.post(url, headers=headers, files=files)
        
        if response.status_code == 202:
            print("Upload successful:")
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"Upload failed with status code {response.status_code}:")
            print(json.dumps(response.json(), indent=2))

    @staticmethod
    def is_image(file_path: str) -> bool:
        return file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.heic'))

    @staticmethod
    def convert_heic_to_jpg(file_path: str) -> str:
        print("Converting HEIC to JPG")
        with Image.open(file_path) as img:
            jpg_path = os.path.splitext(file_path)[0] + '.jpg'
            img.save(jpg_path, 'JPEG')
        return jpg_path

    def purchase_tokens(self, amount: int) -> str:
        url = f"{self.server_url}/purchase_tokens"
        headers = {'Content-Type': 'application/json'}
        data = {'amount': amount}
        
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 200:
            token_data = response.json()
            self.user_token = token_data['user_token']
            print(f"Successfully purchased {amount} tokens.")
            return self.user_token
        else:
            print(f"Failed to purchase tokens. Status code: {response.status_code}")
            print(response.text)
            return None

    def check_balance(self):
        url = f"{self.server_url}/check_balance"
        headers = {
            'Content-Type': 'application/json',
            'User-Token': self.user_token
        }
        data = {'user_token': self.user_token}
        
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 200:
            balance = response.json()['balance']
            print(f"Current token balance: {balance}")
            return balance
        else:
            print(f"Failed to check balance. Status code: {response.status_code}")
            print(response.text)
            return -1  # Return 0 or another appropriate default value instead of None

    def get_batch_status(self, batch_id, retries=3):
        url = f"{self.server_url}/batches/{batch_id}"
        headers = {
            'User-Token': self.user_token
        }
        
        for attempt in range(retries):
            try:
                response = requests.get(url, headers=headers)
                print(f"Attempt {attempt + 1}: Status code {response.status_code}")
                print(f"Response headers: {response.headers}")
                print(f"Response content: {response.text[:1000]}...")  # Print first 1000 characters
                
                response.raise_for_status()  # Raise an exception for bad status codes
                return response.json()
            except requests.exceptions.RequestException as e:
                print(f"Error occurred: {e}")
                if attempt < retries - 1:
                    wait_time = (2 ** attempt) + random.random()
                    print(f"Retrying in {wait_time:.2f} seconds...")
                    time.sleep(wait_time)
                else:
                    print("Max retries reached. Giving up.")
                    return None

    def poll_batch_status(self, batch_id, interval=15, timeout=88200):  # 24.5 hour timeout
        start_time = time.time()
        while time.time() - start_time < timeout:
            status = self.get_batch_status(batch_id)
            if status is None:
                print("Failed to get batch status. Continuing to next attempt...")
                time.sleep(interval)
                continue
            
            if status['status'] == 'completed':
                print(f"Batch {batch_id} completed.")
                self.process_completed_batch(status) 
                return status
            elif status['status'] in ['failed', 'expired', 'cancelled']:
                print(f"Batch {batch_id} {status['status']}.")
                return None
            print(f"Batch {batch_id} status: {status['status']}. Waiting {interval} seconds...")
            time.sleep(interval)
        
        print(f"Timeout reached for batch {batch_id}")
        return None

    def process_completed_batch(self, batch_data):
        """
        Process the completed batch data.
        
        :param batch_data: The completed batch data
        """
        print("Processing completed batch data:")
        print(json.dumps(batch_data, indent=2))
        
        # Process the batch data
        print(f"Batch ID: {batch_data['id']}")
        print(f"Status: {batch_data['status']}")
        print(f"Input File ID: {batch_data['input_file_id']}")
        print(f"Output File ID: {batch_data['output_file_id']}")
        if 'error_file_id' in batch_data:
            print(f"Error File ID: {batch_data['error_file_id']}")
        else:
            print("No Error File ID (batch completed successfully)")
        print(f"Created at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(batch_data['created_at']))}")
        print(f"Completed at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(batch_data['completed_at']))}")
        
        print("Request Counts:")
        print(f"  Total: {batch_data['request_counts']['total']}")
        print(f"  Completed: {batch_data['request_counts']['completed']}")
        print(f"  Failed: {batch_data['request_counts']['failed']}")
        
        if 'metadata' in batch_data and batch_data['metadata']:
            print("Metadata:")
            for key, value in batch_data['metadata'].items():
                print(f"  {key}: {value}")
        
        print(f"Remaining Balance: {batch_data['remaining_balance']}")
        
        # Process the output file
        self.process_output_file(batch_data['output_file_id'])
        
        # After processing, delete the batch files
        deletion_results = self.delete_batch_files(batch_data['id'])
        if deletion_results:
            print("Batch files deletion results:")
            print(json.dumps(deletion_results, indent=2))
        else:
            print("Failed to delete batch files.")

    def retrieve_file_content(self, file_id):
        """
        Retrieve the content of a file using its file ID.
        
        :param file_id: The ID of the file to retrieve
        :return: The content of the file as a string, or None if retrieval fails
        """
        url = f"{self.server_url}/retrieve_file_content/{file_id}"
        headers = {
            'User-Token': self.user_token
        }
        response = requests.get(url, headers=headers)
        
        print(f"Response status code: {response.status_code}")
        print(f"Response headers: {response.headers}")
        print(f"Response content (first 1000 characters): {response.text[:1000]}")
        
        if response.status_code == 200:
            return response.text
        else:
            print(f"Failed to retrieve file content. Status code: {response.status_code}")
            print(response.text)
            return None

    def save_output_file(self, file_id, output_filename):
        """
        Retrieve the content of the output file and save it locally.
        
        :param file_id: The ID of the output file to retrieve
        :param output_filename: The name of the file to save the content to
        :return: True if successful, False otherwise
        """
        content = self.retrieve_file_content(file_id)
        if content is not None:
            with open(output_filename, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Output file saved as {output_filename}")
            return True
        else:
            print("Failed to save output file")
            return False

    def process_output_file(self, file_id):
        """
        Process the output file after a batch job is completed.
        
        :param file_id: The ID of the output file to process
        """
        output_filename = f"output_{file_id}.jsonl"
        if self.save_output_file(file_id, output_filename):
            self.process_batch_results(output_filename)
            # Remove the output file after processing
            try:
                os.remove(output_filename)
                print(f"Removed output file: {output_filename}")
            except OSError as e:
                print(f"Error removing output file {output_filename}: {e}")
        else:
            print("Failed to process output file")

    def process_batch_results(self, results_file):
        """
        Process the batch results from a JSONL file.
        
        :param results_file: Path to the file containing batch results in JSONL format
        """
        if not os.path.exists(results_file):
            print(f"Results file {results_file} not found.")
            return

        with open(results_file, 'r') as f:
            for line in f:
                try:
                    item = json.loads(line.strip())
                    custom_id = item.get('custom_id')
                    content = item.get('response', {}).get('body', {}).get('choices', [{}])[0].get('message', {}).get('content')
                    if custom_id and content:
                        self.update_image_status(custom_id, content)
                    else:
                        print(f"Skipping invalid item: {item}")
                except json.JSONDecodeError as e:
                    print(f"Error decoding JSON: {e}")
                    print(f"Problematic line: {line}")

    def update_image_status(self, custom_id: str, content: str):
        # Extract the original filepath from the custom_id
        filepath = custom_id.replace('request-', '')
        
        # Determine the action based on the content
        action = content.strip().upper()
        
        # Report the status
        print(f"Image {filepath}: {action}")

        # If you want to perform actions based on the status:
        if action == 'DELETE':
            if os.path.exists(filepath):
                print(f"Would delete: {filepath}")
                # Uncomment the following line to actually delete the file
                # os.remove(filepath)
            else:
                print(f"File not found: {filepath}")

    def get_batch_jobs(self):
        url = f"{self.server_url}/user/batch_jobs"
        headers = {
            'User-Token': self.user_token
        }
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            batch_jobs = response.json()['batch_jobs']
            print("Batch jobs:")
            for job in batch_jobs:
                print(f"ID: {job['id']}, Status: {job['status']}, Created at: {job['created_at']}")
            return batch_jobs
        else:
            print(f"Failed to get batch jobs. Status code: {response.status_code}")
            print(response.text)
            return None

    def get_file_ids(self):
        url = f"{self.server_url}/user/file_ids"
        headers = {
            'User-Token': self.user_token
        }
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            file_ids = response.json()['file_ids']
            print("File IDs:")
            for file_id in file_ids:
                print(file_id)
            return file_ids
        else:
            print(f"Failed to get file IDs. Status code: {response.status_code}")
            print(response.text)
            return None

    def delete_batch_files(self, batch_id):
        """
        Delete the input and output files associated with a batch job.
        
        :param batch_id: The ID of the batch job
        :return: A dictionary with the deletion results, or None if the deletion fails
        """
        url = f"{self.server_url}/delete_batch_files/{batch_id}"
        headers = {
            'User-Token': self.user_token
        }
        response = requests.delete(url, headers=headers)
        
        if response.status_code == 200:
            return response.json()['deletion_results']
        else:
            print(f"Failed to delete batch files. Status code: {response.status_code}")
            print(response.text)
            return None

# Example usage
if __name__ == "__main__":
    server_url = "http://localhost:5000"  # Local development server URL
    client = DeskClient(server_url, user_token=None)
    if client.check_balance() < 10:
        print("Insufficient tokens, purchasing more...")
        print(client.purchase_tokens(100))
    else:
        print("Sufficient tokens available.")
    folder_path = input("Enter the folder path: ")
    if client.process_folder(folder_path):
        run_id = uuid.uuid4().hex[:8]  # Generate a unique run ID
        output_base = f"batch_requests_{run_id}"
        client.create_batch_jsonl(output_base)
        
        # Upload each created JSONL file and remove after uploading
        file_index = 1
        while True:
            file_path = f"{output_base}_{file_index}.jsonl"
            if not os.path.exists(file_path):
                break
            print(f"Uploading {file_path}...")
            client.upload_jsonl(file_path)
            try:
                os.remove(file_path)
                print(f"Removed batch request file: {file_path}")
            except OSError as e:
                print(f"Error removing batch request file {file_path}: {e}")
            file_index += 1
    else:
        print("No batch files were created due to lack of processable images.")

    # Check balance after uploading
    client.check_balance()

    # Get batch jobs
    batch_jobs = client.get_batch_jobs()

    if batch_jobs:
        print("Polling all batch jobs...")
        for job in batch_jobs:
            batch_id = job['id']
            print(f"Polling batch job {batch_id}...")
            completed_batch = client.poll_batch_status(batch_id)
            
            if completed_batch:
                print(f"Batch {batch_id} completed successfully.")
                # Process the completed batch
            else:
                print(f"Batch {batch_id} processing failed or timed out.")
    else:
        print("No batch jobs found.")

    # Check final balance
    client.check_balance()

    client.get_file_ids()

