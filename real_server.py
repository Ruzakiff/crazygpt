from flask import Flask, request, jsonify
import os
import secrets
import time
from datetime import datetime, timedelta
import uuid
from threading import Lock
import math
import requests
from openai import OpenAI

app = Flask(__name__)

# In-memory storage for tokens and usage
tokens = {}
rate_limits = {}
batch_jobs = {}

# Configuration
MAX_BATCH_REQUESTS = 50000
MAX_BATCH_SIZE_MB = 100

# Function to retrieve file content given file_id
@app.route('/retrieve_file_content/<file_id>', methods=['GET'])
def retrieve_file_content(file_id):
    client = OpenAI()
    try:
        content = client.files.content(file_id)
        if isinstance(content, bytes):
            return content.decode('utf-8'), 200
        elif hasattr(content, 'text'):
            return content.text, 200
        else:
            return jsonify({'error': "Unexpected content type"}), 500
    except Exception as e:
        return jsonify({'error': f"Failed to retrieve file content: {str(e)}"}), 500

# Helper functions for batch processing
def create_openai_batch(file_id, user_token):
    client = OpenAI()
    
    try:
        batch = client.batches.create(
            input_file_id=file_id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
            metadata={
                "user_token": user_token
            }
        )
        return batch
    except Exception as e:
        raise Exception(f"Failed to create OpenAI batch: {str(e)}")

# Helper Functions
def generate_token():
    return secrets.token_urlsafe(16)

def create_token(amount):
    user_token = generate_token()
    tokens[user_token] = {'amount': amount, 'used': 0, 'expiry': datetime.now() + timedelta(hours=24)}
    return user_token

def validate_token(token):
    if token in tokens:
        current_time = datetime.now()
        if current_time < tokens[token]['expiry']:
            return tokens[token]['amount'] > 0
        else:
            del tokens[token]  # Remove expired token
    return False

# Rate limiting with thread-safe operations
rate_limit_lock = Lock()

def rate_limited(token):
    current_time = int(time.time())
    with rate_limit_lock:
        if token not in rate_limits:
            rate_limits[token] = [current_time]
            return False
        
        # Allow 5 requests per minute
        rate_limits[token] = [t for t in rate_limits[token] if current_time - t < 60]
        if len(rate_limits[token]) >= 5:
            return True
        
        rate_limits[token].append(current_time)
        return False

def upload_file_to_openai(file):
    """
    Upload a file to OpenAI API.
    
    Args:
    file: FileStorage object from Flask request.files
    
    Returns:
    dict: OpenAI API response containing file information
    """
    openai_api_key = os.environ.get('OPENAI_API_KEY')
    if not openai_api_key:
        raise ValueError('OpenAI API key not configured')

    headers = {
        "Authorization": f"Bearer {openai_api_key}"
    }
    files = {
        'file': (file.filename, file.stream, 'application/octet-stream'),
        'purpose': (None, 'batch')
    }

    response = requests.post(
        "https://api.openai.com/v1/files",
        headers=headers,
        files=files
    )

    if response.status_code != 200:
        raise Exception(f'Failed to upload file to OpenAI API: {response.text}')

    return response.json()

# Add these new functions
def get_user_batch_jobs(user_token):
    print(batch_jobs)
    return [job for job in batch_jobs.values() if job['token'] == user_token]

def get_user_file_ids(user_token):
    return [job['openai_file_id'] for job in batch_jobs.values() if job['token'] == user_token]

# Endpoints
@app.route('/')
def root():
    return jsonify({"message": "Real server is running"}), 200

@app.route('/purchase_tokens', methods=['POST'])
def purchase_tokens():
    data = request.json
    amount = data.get('amount', 1000)
    if amount <= 0:
        return jsonify({'error': 'Invalid token amount'}), 400
    user_token = create_token(amount)
    return jsonify({'user_token': user_token}), 200

@app.route('/check_balance', methods=['POST'])
def check_balance():
    data = request.json
    user_token = data.get('user_token')
    if user_token in tokens:
        return jsonify({'balance': tokens[user_token]['amount']}), 200
    else:
        return jsonify({'error': 'Invalid token'}), 400

token_lock = Lock()

@app.route('/upload_jsonl', methods=['POST'])
def upload_jsonl():
    user_token = request.headers.get('User-Token')
    if not user_token or not validate_token(user_token):
        return jsonify({'error': 'Invalid or expired token'}), 400
    if rate_limited(user_token):
        return jsonify({'error': 'Rate limit exceeded'}), 429

    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if not file.filename.endswith('.jsonl'):
        return jsonify({'error': 'File must be a JSONL file'}), 400

    # Check actual file size
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)  # Reset file pointer to the beginning

    if file_size > MAX_BATCH_SIZE_MB * 1024 * 1024:  # Convert MB to bytes
        return jsonify({'error': f'File size exceeds maximum allowed ({MAX_BATCH_SIZE_MB} MB)'}), 400

    # Upload file to OpenAI API
    try:
        openai_file_info = upload_file_to_openai(file)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    # Create OpenAI batch
    try:
        batch = create_openai_batch(openai_file_info['id'], user_token)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    # Process the JSONL file
    file.seek(0)  # Reset file pointer to the beginning
    file_content = file.read().decode('utf-8').splitlines()
    num_requests = len(file_content)

    # Check if the number of requests exceeds the maximum allowed
    if num_requests > MAX_BATCH_REQUESTS:
        return jsonify({'error': f'Number of requests exceeds maximum allowed ({MAX_BATCH_REQUESTS})'}), 400

    # Create batch job
    batch_jobs[batch.id] = {
        'id': batch.id,
        'status': batch.status,
        'created_at': batch.created_at,
        'requests': file_content,
        'token': user_token,
        'openai_file_id': openai_file_info['id']
    }

    # Deduct initial cost
    initial_cost = num_requests
    with token_lock:
        if tokens[user_token]['amount'] < initial_cost:
            return jsonify({'error': 'Insufficient balance for batch creation'}), 400
        tokens[user_token]['amount'] -= initial_cost

    return jsonify({
        'batch_id': batch.id,
        'status': batch.status,
        'remaining_balance': tokens[user_token]['amount'],
        'total_requests': num_requests,
        'openai_file_id': openai_file_info['id'],
        'message': f'Successfully created batch to process {num_requests} requests.'
    }), 202

@app.route('/batches/<batch_id>', methods=['GET'])
def get_batch_status(batch_id):
    user_token = request.headers.get('User-Token')
    if not user_token or not validate_token(user_token):
        return jsonify({'error': 'Invalid or expired token'}), 400

    if batch_id not in batch_jobs:
        return jsonify({'error': 'Batch not found'}), 404

    if batch_jobs[batch_id]['token'] != user_token:
        return jsonify({'error': 'Unauthorized access to batch'}), 403

    # Retrieve the batch directly from OpenAI
    client = OpenAI()
    try:
        openai_batch = client.batches.retrieve(batch_id)
    except Exception as e:
        return jsonify({'error': f'Failed to retrieve batch from OpenAI: {str(e)}'}), 500

    # Update local batch job status
    batch_jobs[batch_id]['status'] = openai_batch.status

    # Convert the OpenAI response to a dictionary
    response = {k: v for k, v in openai_batch.model_dump().items() if v is not None}
    
    # Add the user's remaining balance
    response['remaining_balance'] = tokens[user_token]['amount']

    return jsonify(response), 200

@app.route('/purchase_tier', methods=['POST'])
def purchase_tier():
    data = request.json
    tier = data.get('tier', 'basic')
    
    tier_pricing = {
        'basic': 1250,
        'standard': 2500,
        'premium': 5000,
    }
    if tier not in tier_pricing:
        return jsonify({'error': 'Invalid tier'}), 400
    
    amount = tier_pricing[tier]
    user_token = create_token(amount)
    return jsonify({'user_token': user_token, 'tier': tier}), 200

# Add these new routes
@app.route('/user/batch_jobs', methods=['GET'])
def get_user_batch_jobs_route():
    user_token = request.headers.get('User-Token')
    if not user_token or not validate_token(user_token):
        return jsonify({'error': 'Invalid or expired token'}), 400

    user_jobs = get_user_batch_jobs(user_token)
    return jsonify({
        'batch_jobs': [{'id': job['id'], 'status': job['status'], 'created_at': job['created_at']} for job in user_jobs]
    }), 200

@app.route('/user/file_ids', methods=['GET'])
def get_user_file_ids_route():
    user_token = request.headers.get('User-Token')
    if not user_token or not validate_token(user_token):
        return jsonify({'error': 'Invalid or expired token'}), 400

    file_ids = get_user_file_ids(user_token)
    return jsonify({'file_ids': file_ids}), 200

if __name__ == '__main__':
    app.run(debug=True)