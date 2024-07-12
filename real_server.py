from flask import Flask, request, jsonify
import os
import secrets
import time
from datetime import datetime, timedelta
import uuid
from threading import Lock
import math

app = Flask(__name__)

# In-memory storage for tokens and usage
tokens = {}
rate_limits = {}
batch_jobs = {}

# Configuration
MAX_BATCH_REQUESTS = 50000
MAX_BATCH_SIZE_MB = 100

# Helper functions for batch processing
def create_batch_job(user_token, file_paths):
    batch_file_id = f"file-{secrets.token_hex(3)}"
    batch_id = f"batch-{uuid.uuid4().hex[:6]}"
    
    batch_jobs[batch_id] = {
        'id': batch_id,
        'status': 'validating',
        'input_file_id': batch_file_id,
        'created_at': datetime.now().timestamp(),
        'file_paths': file_paths,
        'token': user_token
    }
    
    return batch_id, batch_file_id

def process_batch(batch_id):
    batch = batch_jobs[batch_id]
    current_time = datetime.now()
    created_time = datetime.fromtimestamp(batch['created_at'])
    elapsed_time = (current_time - created_time).total_seconds()
    
    if elapsed_time < 10:
        batch['status'] = 'validating'
    elif elapsed_time < 30:
        batch['status'] = 'in_progress'
    else:
        batch['status'] = 'completed'
        if 'decisions' not in batch:
            batch['decisions'] = mock_api_decision(batch['file_paths'])
    
    batch_jobs[batch_id] = batch
    return batch

def get_batch_result(batch_id):
    batch = process_batch(batch_id)
    return {
        'id': batch['id'],
        'status': batch['status'],
        'decisions': batch.get('decisions', []) if batch['status'] == 'completed' else None
    }

# Mock API endpoint
def mock_api_decision(file_paths):
    return [{'file': file_path, 'decision': 'keep' if secrets.randbelow(2) == 0 else 'delete'} 
            for file_path in file_paths]

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

# Endpoints
@app.route('/')
def root():
    return jsonify({"message": "Mock server is running"}), 200

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

    # Process the JSONL file
    batch_id = f"batch-{uuid.uuid4().hex[:6]}"
    file_content = file.read().decode('utf-8').splitlines()
    num_requests = len(file_content)

    # Check if the number of requests exceeds the maximum allowed
    if num_requests > MAX_BATCH_REQUESTS:
        return jsonify({'error': f'Number of requests exceeds maximum allowed ({MAX_BATCH_REQUESTS})'}), 400

    # Create batch job
    batch_jobs[batch_id] = {
        'id': batch_id,
        'status': 'validating',
        'created_at': datetime.now().timestamp(),
        'requests': file_content,
        'token': user_token
    }

    # Deduct initial cost
    initial_cost = num_requests
    with token_lock:
        if tokens[user_token]['amount'] < initial_cost:
            return jsonify({'error': 'Insufficient balance for batch creation'}), 400
        tokens[user_token]['amount'] -= initial_cost

    return jsonify({
        'batch_id': batch_id,
        'status': 'validating',
        'remaining_balance': tokens[user_token]['amount'],
        'total_requests': num_requests,
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

    result = process_batch(batch_id)
    
    # Deduct final cost if batch is completed
    if result['status'] == 'completed':
        final_cost = len(result['file_paths'])
        tokens[user_token]['amount'] -= final_cost

    response = {
        'id': result['id'],
        'status': result['status'],
        'remaining_balance': tokens[user_token]['amount']
    }
    
    if result['status'] == 'completed':
        response['decisions'] = result.get('decisions', [])

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

if __name__ == '__main__':
    app.run(debug=True)
