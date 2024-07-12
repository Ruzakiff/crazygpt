import json
import os
import base64
import requests
from typing import List, Dict
from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()

MAX_REQUESTS_PER_FILE = 50000
MAX_FILE_SIZE_MB = 100

class DeskClient:
    def __init__(self, server_url, user_token):
        self.requests = []
        self.server_url = server_url
        self.user_token = user_token

    def process_folder(self, folder_path: str):
        if not os.path.isdir(folder_path):
            print(f"Error: The folder '{folder_path}' does not exist.")
            return

        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)
            if os.path.isfile(file_path) and self.is_image(file_path):
                print(f"Processing image: {filename}")
                self.process_image(file_path)

    def process_image(self, file_path: str):
        original_path = file_path
        if file_path.lower().endswith('.heic'):
            file_path = self.convert_heic_to_jpg(file_path)

        with open(file_path, "rb") as image_file:
            image_data = image_file.read()

        custom_id = f"request-{os.path.basename(original_path)}"
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

    def process_response_file(self, response_file_path: str):
        with open(response_file_path, 'r') as file:
            for line in file:
                response_data = json.loads(line)
                custom_id = response_data['custom_id']
                response = response_data['response']

                if response and response['status_code'] == 200:
                    content = response['body']['choices'][0]['message']['content']
                    self.update_image_status(custom_id, content)
                else:
                    print(f"Error processing request {custom_id}: {response_data.get('error', 'Unknown error')}")

    def update_image_status(self, custom_id: str, content: str):
        # Extract the original filename from the custom_id
        filename = custom_id.replace('request-', '')
        
        # Determine the action based on the content
        action = 'KEEP' if content.strip().upper() == 'KEEP' else 'DELETE'
        
        # Update the status (you might want to store this information in a database or file)
        print(f"Image {filename}: {action}")
        
        # If the action is DELETE, you might want to actually delete the file
        if action == 'DELETE':
            file_path = os.path.join(self.processed_folder, filename)
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"Deleted {filename}")
            else:
                print(f"File {filename} not found")

# Example usage
if __name__ == "__main__":
    server_url = "http://localhost:5000"  # Local development server URL
    client = DeskClient(server_url, user_token=None)
    
    # Purchase tokens before processing
    token_amount = int(input("Enter the number of tokens to purchase: "))
    client.purchase_tokens(token_amount)
    
    folder_path = input("Enter the folder path: ")
    client.process_folder(folder_path)
    output_base = "batch_requests"
    client.create_batch_jsonl(output_base)
    
    # Upload each created JSONL file
    file_index = 1
    while True:
        file_path = f"{output_base}_{file_index}.jsonl"
        if not os.path.exists(file_path):
            break
        print(f"Uploading {file_path}...")
        client.upload_jsonl(file_path)
        file_index += 1

    # After processing and uploading all batches
    response_file = input("Enter the path to the response file: ")
    client.process_response_file(response_file)