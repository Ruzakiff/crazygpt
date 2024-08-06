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
from dotenv import load_dotenv
import logging
import sys

# Configure logging to write to stdout
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()
logger.info("Environment variables loaded from .env file")

# Set OpenAI API key as an environment variable
os.environ['OPENAI_API_KEY'] = os.getenv('OPENAI_API_KEY')
logger.info("OpenAI API key set from environment variable")

app = Flask(__name__)
logger.info("Flask app initialized")

# All locks declared at the top
token_lock = Lock()
rate_limit_lock = Lock()
logger.info("Locks initialized")

# In-memory storage for rate limits
rate_limits = {}

# Configuration
MAX_BATCH_REQUESTS = 50000
MAX_BATCH_SIZE_MB = 100
DB_NAME = 'app_database.sqlite'
logger.info(f"Configuration set: MAX_BATCH_REQUESTS={MAX_BATCH_REQUESTS}, MAX_BATCH_SIZE_MB={MAX_BATCH_SIZE_MB}, DB_NAME={DB_NAME}")

# Initialize database
def init_db():
    logger.info("Initializing database")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tokens
                 (token TEXT PRIMARY KEY, amount INTEGER, used INTEGER, expiry TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS batch_jobs
                 (id TEXT PRIMARY KEY, status TEXT, created_at TEXT, token TEXT, openai_file_id TEXT, output_file_id TEXT)''')
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")

# Database operations
def db_create_token(token, amount):
    logger.info(f"Creating token: {token} with amount: {amount}")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    expiry = (datetime.now() + timedelta(hours=24)).isoformat()
    c.execute("INSERT INTO tokens VALUES (?, ?, ?, ?)", (token, amount, 0, expiry))
    conn.commit()
    conn.close()
    logger.info(f"Token created successfully: {token}")

def db_get_token(token):
    logger.info(f"Retrieving token: {token}")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM tokens WHERE token = ?", (token,))
    result = c.fetchone()
    conn.close()
    if result:
        logger.info(f"Token retrieved: {token}")
        return {'token': result[0], 'amount': result[1], 'used': result[2], 'expiry': result[3]}
    logger.warning(f"Token not found: {token}")
    return None

def db_update_token_amount(token, new_amount):
    logger.info(f"Updating token amount: {token} to {new_amount}")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE tokens SET amount = ? WHERE token = ?", (new_amount, token))
    conn.commit()
    conn.close()
    logger.info(f"Token amount updated successfully: {token}")

def db_delete_token(token):
    logger.info(f"Deleting token: {token}")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM tokens WHERE token = ?", (token,))
    conn.commit()
    conn.close()
    logger.info(f"Token deleted successfully: {token}")

def db_create_batch_job(batch_id, status, created_at, token, openai_file_id, output_file_id=None):
    logger.info(f"Creating batch job: {batch_id}")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO batch_jobs VALUES (?, ?, ?, ?, ?, ?)", 
              (batch_id, status, created_at, token, openai_file_id, output_file_id))
    conn.commit()
    conn.close()
    logger.info(f"Batch job created successfully: {batch_id}")

def db_get_batch_job(batch_id):
    logger.info(f"Retrieving batch job: {batch_id}")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM batch_jobs WHERE id = ?", (batch_id,))
    result = c.fetchone()
    conn.close()
    if result:
        logger.info(f"Batch job retrieved: {batch_id}")
        return {'id': result[0], 'status': result[1], 'created_at': result[2], 
                'token': result[3], 'openai_file_id': result[4], 'output_file_id': result[5]}
    logger.warning(f"Batch job not found: {batch_id}")
    return None

def db_update_batch_job(batch_id, status=None, output_file_id=None):
    logger.info(f"Updating batch job: {batch_id}")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if status:
        c.execute("UPDATE batch_jobs SET status = ? WHERE id = ?", (status, batch_id))
        logger.info(f"Updated status for batch job {batch_id}: {status}")
    if output_file_id:
        c.execute("UPDATE batch_jobs SET output_file_id = ? WHERE id = ?", (output_file_id, batch_id))
        logger.info(f"Updated output_file_id for batch job {batch_id}: {output_file_id}")
    conn.commit()
    conn.close()
    logger.info(f"Batch job updated successfully: {batch_id}")

def db_delete_batch_job(batch_id):
    logger.info(f"Deleting batch job: {batch_id}")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM batch_jobs WHERE id = ?", (batch_id,))
    conn.commit()
    conn.close()
    logger.info(f"Batch job deleted successfully: {batch_id}")

def db_get_user_batch_jobs(user_token):
    logger.info(f"Retrieving user batch jobs for token: {user_token}")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, status, created_at FROM batch_jobs WHERE token = ?", (user_token,))
    results = c.fetchall()
    conn.close()
    logger.info(f"Retrieved {len(results)} batch jobs for user token: {user_token}")
    return [{'id': r[0], 'status': r[1], 'created_at': r[2]} for r in results]

def db_get_user_file_ids(user_token):
    logger.info(f"Retrieving user file IDs for token: {user_token}")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT openai_file_id FROM batch_jobs WHERE token = ?", (user_token,))
    results = c.fetchall()
    conn.close()
    logger.info(f"Retrieved {len(results)} file IDs for user token: {user_token}")
    return [r[0] for r in results]

# Helper functions
def generate_token():
    token = secrets.token_urlsafe(16)
    logger.info(f"Generated new token: {token}")
    return token

def create_token(amount):
    user_token = generate_token()
    db_create_token(user_token, amount)
    logger.info(f"Created token with amount {amount}: {user_token}")
    return user_token

def validate_token(token):
    logger.info(f"Validating token: {token}")
    token_data = db_get_token(token)
    if token_data:
        current_time = datetime.now()
        if current_time < datetime.fromisoformat(token_data['expiry']):
            logger.info(f"Token validated successfully: {token}")
            return token_data['amount'] > 0
        else:
            logger.warning(f"Token expired: {token}")
            db_delete_token(token)  # Remove expired token
    logger.warning(f"Token validation failed: {token}")
    return False

def get_token_balance(token):
    logger.info(f"Getting balance for token: {token}")
    token_data = db_get_token(token)
    balance = token_data['amount'] if token_data else None
    logger.info(f"Balance for token {token}: {balance}")
    return balance

def update_token_balance(token, amount):
    logger.info(f"Updating balance for token {token} by {amount}")
    token_data = db_get_token(token)
    if token_data:
        new_amount = token_data['amount'] + amount
        db_update_token_amount(token, new_amount)
        logger.info(f"New balance for token {token}: {new_amount}")

def delete_token(token):
    logger.info(f"Deleting token: {token}")
    db_delete_token(token)

def create_openai_batch(file_id, user_token):
    logger.info(f"Creating OpenAI batch for file {file_id} and user token {user_token}")
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
        logger.info(f"OpenAI batch created successfully: {batch.id}")
        # Store the batch information in the database
        db_create_batch_job(batch.id, batch.status, batch.created_at, user_token, file_id, batch.output_file_id)
        return batch
    except Exception as e:
        logger.error(f"Failed to create OpenAI batch: {str(e)}")
        raise Exception(f"Failed to create OpenAI batch: {str(e)}")

def rate_limited(token):
    logger.info(f"Checking rate limit for token: {token}")
    current_time = int(time.time())
    with rate_limit_lock:
        if token not in rate_limits:
            rate_limits[token] = [current_time]
            logger.info(f"No rate limit for token: {token}")
            return False
        
        # Allow 5 requests per minute per token
        rate_limits[token] = [t for t in rate_limits[token] if current_time - t < 60]
        if len(rate_limits[token]) >= 5:
            logger.warning(f"Rate limit exceeded for token: {token}")
            return True
        
        rate_limits[token].append(current_time)
        logger.info(f"Rate limit not exceeded for token: {token}")
        return False

def upload_file_to_openai(file):
    logger.info(f"Uploading file to OpenAI: {file.filename}")
    headers = {
        "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"
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
        logger.error(f"Failed to upload file to OpenAI API: {response.text}")
        raise Exception(f'Failed to upload file to OpenAI API: {response.text}')

    logger.info(f"File uploaded successfully to OpenAI: {file.filename}")
    return response.json()

# Initialize the BatchLogger
batch_logger = BatchLogger()
logger.info("BatchLogger initialized")

# Endpoints
@app.route('/')
def root():
    logger.info("Root endpoint accessed")
    return jsonify({"message": "Real server is running"}), 200

@app.route('/purchase_tokens', methods=['POST'])
def purchase_tokens():
    logger.info("Purchase tokens endpoint accessed")
    data = request.json
    amount = data.get('amount', 1000)
    if amount <= 0:
        logger.warning(f"Invalid token amount requested: {amount}")
        return jsonify({'error': 'Invalid token amount'}), 400
    user_token = create_token(amount)
    logger.info(f"Tokens purchased successfully: {amount} for token {user_token}")
    return jsonify({'user_token': user_token}), 200

@app.route('/check_balance', methods=['POST'])
def check_balance():
    logger.info("Check balance endpoint accessed")
    data = request.json
    user_token = data.get('user_token')
    if not user_token or not validate_token(user_token):
        logger.warning(f"Invalid or expired token: {user_token}")
        return jsonify({'error': 'Invalid or expired token'}), 400
    if rate_limited(user_token):
        logger.warning(f"Rate limit exceeded for token: {user_token}")
        return jsonify({'error': 'Rate limit exceeded for this token'}), 429

    token_data = db_get_token(user_token)
    if token_data:
        logger.info(f"Balance checked successfully for token {user_token}: {token_data['amount']}")
        return jsonify({'balance': token_data['amount']}), 200
    else:
        logger.warning(f"Invalid token: {user_token}")
        return jsonify({'error': 'Invalid token'}), 400

@app.route('/upload_jsonl', methods=['POST'])
def upload_jsonl():
    logger.info("Upload JSONL endpoint accessed")
    user_token = request.headers.get('User-Token')
    if not user_token or not validate_token(user_token):
        logger.warning(f"Invalid or expired token: {user_token}")
        return jsonify({'error': 'Invalid or expired token'}), 400
    if rate_limited(user_token):
        logger.warning(f"Rate limit exceeded for token: {user_token}")
        return jsonify({'error': 'Rate limit exceeded for this token'}), 429
    
    if 'file' not in request.files:
        logger.warning("No file part in the request")
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        logger.warning("No selected file")
        return jsonify({'error': 'No selected file'}), 400
    
    if not file.filename.endswith('.jsonl'):
        logger.warning(f"Invalid file type: {file.filename}")
        return jsonify({'error': 'File must be a JSONL file'}), 400

    # Check actual file size
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)  # Reset file pointer to the beginning

    if file_size > MAX_BATCH_SIZE_MB * 1024 * 1024:  # Convert MB to bytes
        logger.warning(f"File size exceeds maximum allowed: {file_size} bytes")
        return jsonify({'error': f'File size exceeds maximum allowed ({MAX_BATCH_SIZE_MB} MB)'}), 400

    # Upload file to OpenAI API
    try:
        logger.info(f"Attempting to upload file {file.filename} to OpenAI")
        openai_file_info = upload_file_to_openai(file)
        logger.info(f"File {file.filename} successfully uploaded to OpenAI with ID: {openai_file_info['id']}")
    except Exception as e:
        logger.error(f"Failed to upload file to OpenAI: {str(e)}")
        return jsonify({'error': str(e)}), 500

    # Create OpenAI batch
    try:
        logger.info(f"Creating OpenAI batch for file ID: {openai_file_info['id']}")
        batch = create_openai_batch(openai_file_info['id'], user_token)
        logger.info(f"OpenAI batch created successfully with ID: {batch.id}")
    except Exception as e:
        logger.error(f"Failed to create OpenAI batch: {str(e)}")
        return jsonify({'error': str(e)}), 500

    # Process the JSONL file
    file.seek(0)  # Reset file pointer to the beginning
    file_content = file.read().decode('utf-8').splitlines()
    num_requests = len(file_content)

    logger.info(f"JSONL file contains {num_requests} requests")

    # Check if the number of requests exceeds the maximum allowed
    if num_requests > MAX_BATCH_REQUESTS:
        logger.warning(f"Number of requests ({num_requests}) exceeds maximum allowed ({MAX_BATCH_REQUESTS})")
        return jsonify({'error': f'Number of requests exceeds maximum allowed ({MAX_BATCH_REQUESTS})'}), 400

    # Deduct initial cost
    initial_cost = num_requests
    current_balance = get_token_balance(user_token)
    if current_balance < initial_cost:
        logger.warning(f"Insufficient balance for batch creation. Required: {initial_cost}, Available: {current_balance}")
        return jsonify({'error': 'Insufficient balance for batch creation'}), 400
    
    logger.info(f"Deducting initial cost of {initial_cost} tokens from user balance")
    update_token_balance(user_token, -initial_cost)

    remaining_balance = get_token_balance(user_token)
    logger.info(f"Batch created successfully. Remaining balance: {remaining_balance}")

    return jsonify({
        'batch_id': batch.id,
        'status': batch.status,
        'remaining_balance': remaining_balance,
        'total_requests': num_requests,
        'openai_file_id': openai_file_info['id'],
        'message': f'Successfully created batch to process {num_requests} requests.'
    }), 202

@app.route('/batches/<batch_id>', methods=['GET'])
def get_batch_status(batch_id):
    logger.info(f"Get batch status endpoint accessed for batch ID: {batch_id}")
    user_token = request.headers.get('User-Token')
    if not user_token or not validate_token(user_token):
        logger.warning(f"Invalid or expired token: {user_token}")
        return jsonify({'error': 'Invalid or expired token'}), 400

    batch_job = db_get_batch_job(batch_id)
    if not batch_job:
        logger.warning(f"Batch not found: {batch_id}")
        return jsonify({'error': 'Batch not found'}), 404

    if batch_job['token'] != user_token:
        logger.warning(f"Unauthorized access to batch {batch_id} by token {user_token}")
        return jsonify({'error': 'Unauthorized access to batch'}), 403

    # Retrieve the batch directly from OpenAI
    client = OpenAI()
    try:
        logger.info(f"Retrieving batch {batch_id} from OpenAI")
        openai_batch = client.batches.retrieve(batch_id)
        logger.info(f"Successfully retrieved batch {batch_id} from OpenAI")
    except Exception as e:
        logger.error(f"Failed to retrieve batch {batch_id} from OpenAI: {str(e)}")
        return jsonify({'error': f'Failed to retrieve batch from OpenAI: {str(e)}'}), 500

    # Update local batch job status and output_file_id
    logger.info(f"Updating local batch job {batch_id} status to {openai_batch.status}")
    db_update_batch_job(batch_id, status=openai_batch.status, output_file_id=openai_batch.output_file_id)

    # Convert the OpenAI response to a dictionary
    response = {k: v for k, v in openai_batch.model_dump().items() if v is not None}
    
    # Add the user's remaining balance
    remaining_balance = get_token_balance(user_token)
    response['remaining_balance'] = remaining_balance
    logger.info(f"User {user_token} remaining balance: {remaining_balance}")

    # Log the batch status with enhanced data
    logger.info(f"Logging batch status for batch {batch_id}")
    batch_logger.log_batch_status(batch_id, response, user_token)

    return jsonify(response), 200

@app.route('/purchase_tier', methods=['POST'])
def purchase_tier():
    logger.info("Purchase tier endpoint accessed")
    data = request.json
    tier = data.get('tier', 'basic')
    
    tier_pricing = {
        'basic': 1250,
        'standard': 2500,
        'premium': 5000,
    }
    if tier not in tier_pricing:
        logger.warning(f"Invalid tier requested: {tier}")
        return jsonify({'error': 'Invalid tier'}), 400
    
    amount = tier_pricing[tier]
    user_token = create_token(amount)
    logger.info(f"Tier {tier} purchased successfully. Token created: {user_token}")
    return jsonify({'user_token': user_token, 'tier': tier}), 200

@app.route('/user/batch_jobs', methods=['GET'])
def get_user_batch_jobs_route():
    logger.info("Get user batch jobs endpoint accessed")
    user_token = request.headers.get('User-Token')
    if not user_token or not validate_token(user_token):
        logger.warning(f"Invalid or expired token: {user_token}")
        return jsonify({'error': 'Invalid or expired token'}), 400

    user_jobs = db_get_user_batch_jobs(user_token)
    logger.info(f"Retrieved {len(user_jobs)} batch jobs for user {user_token}")
    return jsonify({
        'batch_jobs': user_jobs
    }), 200

@app.route('/user/file_ids', methods=['GET'])
def get_user_file_ids_route():
    logger.info("Get user file IDs endpoint accessed")
    user_token = request.headers.get('User-Token')
    if not user_token or not validate_token(user_token):
        logger.warning(f"Invalid or expired token: {user_token}")
        return jsonify({'error': 'Invalid or expired token'}), 400

    file_ids = db_get_user_file_ids(user_token)
    logger.info(f"Retrieved {len(file_ids)} file IDs for user {user_token}")
    return jsonify({'file_ids': file_ids}), 200

def delete_file(file_id):
    logger.info(f"Attempting to delete file with ID: {file_id}")
    client = OpenAI()
    try:
        response = client.files.delete(file_id)
        logger.info(f"File {file_id} deleted successfully")
        return response
    except Exception as e:
        logger.error(f"Failed to delete file {file_id}: {str(e)}")
        raise Exception(f"Failed to delete file {file_id}: {str(e)}")

@app.route('/delete_batch_files/<batch_id>', methods=['DELETE'])
def delete_batch_files(batch_id):
    logger.info(f"Delete batch files endpoint accessed for batch ID: {batch_id}")
    user_token = request.headers.get('User-Token')
    if not user_token or not validate_token(user_token):
        logger.warning(f"Invalid or expired token: {user_token}")
        return jsonify({'error': 'Invalid or expired token'}), 400

    batch_job = db_get_batch_job(batch_id)
    if not batch_job or batch_job['token'] != user_token:
        logger.warning(f"Batch not found or unauthorized access: {batch_id}")
        return jsonify({'error': 'Batch not found or unauthorized'}), 404

    try:
        output_file_id = batch_job.get('output_file_id')
        input_file_id = batch_job['openai_file_id']

        deletion_results = {}

        if output_file_id:
            logger.info(f"Attempting to delete output file: {output_file_id}")
            output_delete_response = delete_file(output_file_id)
            deletion_results['output_file'] = output_delete_response.deleted
            logger.info(f"Output file {output_file_id} deletion result: {output_delete_response.deleted}")

        logger.info(f"Attempting to delete input file: {input_file_id}")
        input_delete_response = delete_file(input_file_id)
        deletion_results['input_file'] = input_delete_response.deleted
        logger.info(f"Input file {input_file_id} deletion result: {input_delete_response.deleted}")

        logger.info(f"Deleting batch job {batch_id} from database")
        db_delete_batch_job(batch_id)

        logger.info(f"Batch files deletion completed for batch {batch_id}")
        return jsonify({
            'message': 'Batch files deletion attempted',
            'deletion_results': deletion_results
        }), 200

    except Exception as e:
        logger.error(f"Failed to delete batch files for batch {batch_id}: {str(e)}")
        return jsonify({'error': f"Failed to delete batch files: {str(e)}"}), 500

@app.route('/retrieve_file_content/<file_id>', methods=['GET'])
def retrieve_file_content(file_id):
    logger.info(f"Retrieve file content endpoint accessed for file ID: {file_id}")
    user_token = request.headers.get('User-Token')
    if not user_token or not validate_token(user_token):
        logger.warning(f"Invalid or expired token: {user_token}")
        return jsonify({'error': 'Invalid or expired token'}), 400

    client = OpenAI()
    try:
        logger.info(f"Retrieving content for file {file_id}")
        response = client.files.content(file_id)
        
        # Determine the content type and decode if necessary
        if isinstance(response, bytes):
            file_content = response.decode('utf-8')
        elif hasattr(response, 'text'):
            file_content = response.text
        else:
            file_content = response.read().decode('utf-8')

        logger.info(f"Content retrieved successfully for file {file_id}")

        # Update the output_file_id in the database if necessary
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("UPDATE batch_jobs SET output_file_id = ? WHERE token = ? AND output_file_id = ?", 
                  (file_id, user_token, file_id))
        conn.commit()
        conn.close()
        logger.info(f"Updated output_file_id in database for file {file_id}")

        return file_content, 200, {'Content-Type': 'text/plain'}

    except Exception as e:
        logger.error(f"Failed to retrieve file content for file {file_id}: {str(e)}")
        return jsonify({'error': f"Failed to retrieve file content: {str(e)}"}), 500

if __name__ == '__main__':
    init_db()
    app.run(debug=True)

