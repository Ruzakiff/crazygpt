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
import csv
import json
import sqlite3
from batch_logger import BatchLogger  # Import the BatchLogger class

app = Flask(__name__)

# All locks declared at the top
token_lock = Lock()
rate_limit_lock = Lock()

# In-memory storage for rate limits
rate_limits = {}

# Configuration
MAX_BATCH_REQUESTS = 50000
MAX_BATCH_SIZE_MB = 100
DB_NAME = 'app_database.sqlite'

# Initialize database
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tokens
                 (token TEXT PRIMARY KEY, amount INTEGER, used INTEGER, expiry TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS batch_jobs
                 (id TEXT PRIMARY KEY, status TEXT, created_at TEXT, token TEXT, openai_file_id TEXT, output_file_id TEXT)''')
    conn.commit()
    conn.close()

# Database operations
def db_create_token(token, amount):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    expiry = (datetime.now() + timedelta(hours=24)).isoformat()
    c.execute("INSERT INTO tokens VALUES (?, ?, ?, ?)", (token, amount, 0, expiry))
    conn.commit()
    conn.close()

def db_get_token(token):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM tokens WHERE token = ?", (token,))
    result = c.fetchone()
    conn.close()
    if result:
        return {'token': result[0], 'amount': result[1], 'used': result[2], 'expiry': result[3]}
    return None

def db_update_token_amount(token, new_amount):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE tokens SET amount = ? WHERE token = ?", (new_amount, token))
    conn.commit()
    conn.close()

def db_delete_token(token):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM tokens WHERE token = ?", (token,))
    conn.commit()
    conn.close()

def db_create_batch_job(batch_id, status, created_at, token, openai_file_id, output_file_id=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO batch_jobs VALUES (?, ?, ?, ?, ?, ?)", 
              (batch_id, status, created_at, token, openai_file_id, output_file_id))
    conn.commit()
    conn.close()

def db_get_batch_job(batch_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM batch_jobs WHERE id = ?", (batch_id,))
    result = c.fetchone()
    conn.close()
    if result:
        return {'id': result[0], 'status': result[1], 'created_at': result[2], 
                'token': result[3], 'openai_file_id': result[4], 'output_file_id': result[5]}
    return None

def db_update_batch_job(batch_id, status=None, output_file_id=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if status:
        c.execute("UPDATE batch_jobs SET status = ? WHERE id = ?", (status, batch_id))
    if output_file_id:
        c.execute("UPDATE batch_jobs SET output_file_id = ? WHERE id = ?", (output_file_id, batch_id))
    conn.commit()
    conn.close()

def db_delete_batch_job(batch_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM batch_jobs WHERE id = ?", (batch_id,))
    conn.commit()
    conn.close()

def db_get_user_batch_jobs(user_token):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, status, created_at FROM batch_jobs WHERE token = ?", (user_token,))
    results = c.fetchall()
    conn.close()
    return [{'id': r[0], 'status': r[1], 'created_at': r[2]} for r in results]

def db_get_user_file_ids(user_token):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT openai_file_id FROM batch_jobs WHERE token = ?", (user_token,))
    results = c.fetchall()
    conn.close()
    return [r[0] for r in results]

# Helper functions
def generate_token():
    return secrets.token_urlsafe(16)

def create_token(amount):
    user_token = generate_token()
    db_create_token(user_token, amount)
    return user_token

def validate_token(token):
    token_data = db_get_token(token)
    if token_data:
        current_time = datetime.now()
        if current_time < datetime.fromisoformat(token_data['expiry']):
            return token_data['amount'] > 0
        else:
            db_delete_token(token)  # Remove expired token
    return False

def get_token_balance(token):
    token_data = db_get_token(token)
    return token_data['amount'] if token_data else None

def update_token_balance(token, amount):
    token_data = db_get_token(token)
    if token_data:
        new_amount = token_data['amount'] + amount
        db_update_token_amount(token, new_amount)

def delete_token(token):
    db_delete_token(token)

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
        # Store the batch information in the database
        db_create_batch_job(batch.id, batch.status, batch.created_at, user_token, file_id, batch.output_file_id)
        return batch
    except Exception as e:
        raise Exception(f"Failed to create OpenAI batch: {str(e)}")

def rate_limited(token):
    current_time = int(time.time())
    with rate_limit_lock:
        if token not in rate_limits:
            rate_limits[token] = [current_time]
            return False
        
        # Allow 5 requests per minute per token
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

# Initialize the BatchLogger
batch_logger = BatchLogger()

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
    if not user_token or not validate_token(user_token):
        return jsonify({'error': 'Invalid or expired token'}), 400
    if rate_limited(user_token):
        return jsonify({'error': 'Rate limit exceeded for this token'}), 429

    token_data = db_get_token(user_token)
    if token_data:
        return jsonify({'balance': token_data['amount']}), 200
    else:
        return jsonify({'error': 'Invalid token'}), 400

@app.route('/upload_jsonl', methods=['POST'])
def upload_jsonl():
    user_token = request.headers.get('User-Token')
    if not user_token or not validate_token(user_token):
        return jsonify({'error': 'Invalid or expired token'}), 400
    if rate_limited(user_token):
        return jsonify({'error': 'Rate limit exceeded for this token'}), 429
    
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

    # Deduct initial cost
    initial_cost = num_requests
    current_balance = get_token_balance(user_token)
    if current_balance < initial_cost:
        return jsonify({'error': 'Insufficient balance for batch creation'}), 400
    update_token_balance(user_token, -initial_cost)

    return jsonify({
        'batch_id': batch.id,
        'status': batch.status,
        'remaining_balance': get_token_balance(user_token),
        'total_requests': num_requests,
        'openai_file_id': openai_file_info['id'],
        'message': f'Successfully created batch to process {num_requests} requests.'
    }), 202

@app.route('/batches/<batch_id>', methods=['GET'])
def get_batch_status(batch_id):
    user_token = request.headers.get('User-Token')
    if not user_token or not validate_token(user_token):
        return jsonify({'error': 'Invalid or expired token'}), 400

    batch_job = db_get_batch_job(batch_id)
    if not batch_job:
        return jsonify({'error': 'Batch not found'}), 404

    if batch_job['token'] != user_token:
        return jsonify({'error': 'Unauthorized access to batch'}), 403

    # Retrieve the batch directly from OpenAI
    client = OpenAI()
    try:
        openai_batch = client.batches.retrieve(batch_id)
    except Exception as e:
        return jsonify({'error': f'Failed to retrieve batch from OpenAI: {str(e)}'}), 500

    # Update local batch job status and output_file_id
    db_update_batch_job(batch_id, status=openai_batch.status, output_file_id=openai_batch.output_file_id)

    # Convert the OpenAI response to a dictionary
    response = {k: v for k, v in openai_batch.model_dump().items() if v is not None}
    
    # Add the user's remaining balance
    response['remaining_balance'] = get_token_balance(user_token)

    # Log the batch status with enhanced data
    batch_logger.log_batch_status(batch_id, response, user_token)

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

@app.route('/user/batch_jobs', methods=['GET'])
def get_user_batch_jobs_route():
    user_token = request.headers.get('User-Token')
    if not user_token or not validate_token(user_token):
        return jsonify({'error': 'Invalid or expired token'}), 400

    user_jobs = db_get_user_batch_jobs(user_token)
    return jsonify({
        'batch_jobs': user_jobs
    }), 200

@app.route('/user/file_ids', methods=['GET'])
def get_user_file_ids_route():
    user_token = request.headers.get('User-Token')
    if not user_token or not validate_token(user_token):
        return jsonify({'error': 'Invalid or expired token'}), 400

    file_ids = db_get_user_file_ids(user_token)
    return jsonify({'file_ids': file_ids}), 200

def delete_file(file_id):
    client = OpenAI()
    try:
        response = client.files.delete(file_id)
        return response
    except Exception as e:
        raise Exception(f"Failed to delete file {file_id}: {str(e)}")

@app.route('/delete_batch_files/<batch_id>', methods=['DELETE'])
def delete_batch_files(batch_id):
    user_token = request.headers.get('User-Token')
    if not user_token or not validate_token(user_token):
        return jsonify({'error': 'Invalid or expired token'}), 400

    batch_job = db_get_batch_job(batch_id)
    if not batch_job or batch_job['token'] != user_token:
        return jsonify({'error': 'Batch not found or unauthorized'}), 404

    try:
        output_file_id = batch_job.get('output_file_id')
        input_file_id = batch_job['openai_file_id']

        deletion_results = {}

        if output_file_id:
            output_delete_response = delete_file(output_file_id)
            deletion_results['output_file'] = output_delete_response.deleted

        input_delete_response = delete_file(input_file_id)
        deletion_results['input_file'] = input_delete_response.deleted

        db_delete_batch_job(batch_id)

        return jsonify({
            'message': 'Batch files deletion attempted',
            'deletion_results': deletion_results
        }), 200

    except Exception as e:
        return jsonify({'error': f"Failed to delete batch files: {str(e)}"}), 500

@app.route('/retrieve_file_content/<file_id>', methods=['GET'])
def retrieve_file_content(file_id):
    user_token = request.headers.get('User-Token')
    if not user_token or not validate_token(user_token):
        return jsonify({'error': 'Invalid or expired token'}), 400

    client = OpenAI()
    try:
        # Retrieve content
        response = client.files.content(file_id)
        
        # Determine the content type and decode if necessary
        if isinstance(response, bytes):
            file_content = response.decode('utf-8')
        elif hasattr(response, 'text'):
            file_content = response.text
        else:
            file_content = response.read().decode('utf-8')

        # Update the output_file_id in the database if necessary
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("UPDATE batch_jobs SET output_file_id = ? WHERE token = ? AND output_file_id = ?", 
                  (file_id, user_token, file_id))
        conn.commit()
        conn.close()

        return file_content, 200, {'Content-Type': 'text/plain'}

    except Exception as e:
        return jsonify({'error': f"Failed to retrieve file content: {str(e)}"}), 500

if __name__ == '__main__':
    init_db()
    app.run(debug=True)

