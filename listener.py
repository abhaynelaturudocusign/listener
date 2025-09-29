import os
import pika
import logging
import json
import requests
from flask import Flask, request, Response
from jose import jwt

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration (from environment variables) ---
QUEUE_NAME = 'docusign_jobs'
RABBITMQ_URL = os.environ.get('RABBITMQ_URL')
COGNITO_USER_POOL_ID = os.environ.get('COGNITO_USER_POOL_ID')
COGNITO_REGION = os.environ.get('COGNITO_REGION', 'us-east-1') # e.g., us-east-1
COGNITO_AUDIENCE = os.environ.get('COGNITO_AUDIENCE') # This is the App Client ID from Cognito

# --- JWT Validation ---
# Construct the JWKS URL from your Cognito settings
JWKS_URL = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}/.well-known/jwks.json"
JWKS = requests.get(JWKS_URL).json()["keys"]

def validate_jwt(token):
    """Validates the incoming JWT from DocuSign against AWS Cognito's public keys."""
    try:
        # Get the unverified header from the token
        unverified_header = jwt.get_unverified_header(token)
        
        # Find the correct key to use for verification
        rsa_key = {}
        for key in JWKS:
            if key["kid"] == unverified_header["kid"]:
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"]
                }
        
        if rsa_key:
            # Decode and validate the token
            payload = jwt.decode(
                token,
                rsa_key,
                algorithms=["RS256"],
                audience=COGNITO_AUDIENCE,
                # The issuer URL for a Cognito user pool
                issuer=f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}"
            )
            logging.info("JWT is valid.")
            return True
        
        logging.warning("JWT validation failed: Unable to find a matching key.")
        return False

    except Exception as e:
        logging.error(f"Error during JWT validation: {e}", exc_info=True)
        return False

@app.route('/docusign_webhook', methods=['POST'])
def docusign_webhook():
    """
    Receives the webhook, validates its JWT Bearer token, adds it to the queue,
    and returns 200 OK.
    """
    # --- ADD THIS BLOCK TO PRINT HEADERS ---
    logging.info("--- Incoming Request Headers ---")
    for key, value in request.headers:
        logging.info(f"{key}: {value}")
    logging.info("------------------------------")
    # --- END OF BLOCK ---

    # 1. Validate the JWT Bearer Token
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        logging.warning("Unauthorized webhook: Missing or malformed Authorization header.")
        return Response("Unauthorized", status=401)

    token = auth_header.split(" ")[1]
    if not validate_jwt(token):
        logging.warning("Unauthorized webhook: Invalid JWT.")
        return Response("Unauthorized", status=401)
        
    # 2. If valid, proceed to queue the message
    connection = None
    try:
        connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
        channel = connection.channel()
        channel.queue_declare(queue=QUEUE_NAME, durable=True)
        channel.basic_publish(
            exchange='',
            routing_key=QUEUE_NAME,
            body=request.get_data(),
            properties=pika.BasicProperties(delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE)
        )
        logging.info("Successfully queued a validated job.")
        return Response("Webhook Acknowledged", status=200)
    except Exception as e:
        logging.error(f"Error while queueing webhook: {e}", exc_info=True)
        return Response("Internal Server Error", status=500)
    finally:
        if connection and connection.is_open:
            connection.close()