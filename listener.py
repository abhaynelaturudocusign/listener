import os
import pika
import logging
from flask import Flask, request, Response

# Set up detailed logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
RABBITMQ_URL = "amqps://rbqzmjme:EFGff2DRN2B95OP8a5zy3HN1tV4BQZdM@puffin.rmq2.cloudamqp.com/rbqzmjme"
QUEUE_NAME = 'docusign_jobs'

#if not RABBITMQ_URL:
 #   logging.critical("FATAL ERROR: RABBITMQ_URL environment variable not set.")
    # This will cause the worker to fail to boot, which is what we want if the URL is missing.
  #  raise ValueError("No RABBITMQ_URL set for the Listener application")

app = Flask(__name__)

@app.route('/docusign_webhook', methods=['POST'])
def docusign_webhook():
    """
    Receives a webhook, connects to RabbitMQ, adds the job to the queue,
    and then closes the connection.
    """
    connection = None
    try:
        # 1. Connect to RabbitMQ for this specific request
        logging.info("Attempting to connect to RabbitMQ...")
        connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
        channel = connection.channel()
        logging.info("Successfully connected to RabbitMQ.")

        # 2. Ensure the queue exists
        channel.queue_declare(queue=QUEUE_NAME, durable=True)

        # 3. Publish the message
        channel.basic_publish(
            exchange='',
            routing_key=QUEUE_NAME,
            body=request.get_data(),
            properties=pika.BasicProperties(
                delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE
            ))
        
        logging.info("Successfully queued a new job.")
        return Response("Webhook Acknowledged", status=200)

    except Exception as e:
        # This will now print the detailed Python error to your log
        logging.error(f"An unexpected error occurred: {e}", exc_info=True)
        return Response("Internal Server Error", status=500)
    finally:
        # 4. Ensure the connection is closed
        if connection and connection.is_open:
            connection.close()
            logging.info("RabbitMQ connection closed.")
