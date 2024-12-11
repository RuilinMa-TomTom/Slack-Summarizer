import streamlit as st
import requests
from requests.auth import HTTPBasicAuth
import json
from bs4 import BeautifulSoup
import os
from urllib.parse import urlparse, parse_qs
import re
import warnings
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from datetime import datetime, timedelta
from openai import AzureOpenAI
from flask import Flask, request, jsonify
from slack_sdk.errors import SlackApiError
import logging
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_bolt import App
import time

# Create a logger object
logger = logging.getLogger()

# Set the logging level to INFO
logging.basicConfig(level=logging.INFO)

# Constants
os.environ['OPENAI_API_KEY'] = os.getenv('OPENAI_API_KEY')
os.environ["AZURE_OPENAI_ENDPOINT"] = os.getenv('AZURE_OPENAI_ENDPOINT')

slack_token = os.getenv('SLACK_TOKEN')
slack_client = WebClient(token=slack_token)

# Initialize Azure OpenAI client
client = AzureOpenAI(
    azure_endpoint=os.getenv('AZURE_OPENAI_ENDPOINT'),
    api_key= os.getenv('OPENAI_API_KEY'),
    api_version="2024-02-01",
)

def get_channel_id(channel_name):
    try:
        # Initialize empty list for all channels
        all_channels = []
        # Get first page
        result = slack_client.conversations_list(limit=100)
        all_channels.extend(result["channels"])
        # Get additional pages if cursor is present
        while result.get("response_metadata", {}).get("next_cursor"):
            cursor = result["response_metadata"]["next_cursor"]
            result = slack_client.conversations_list(cursor=cursor, limit=100)
            all_channels.extend(result["channels"])
            
        for channel in all_channels:
            if channel["name"] == channel_name:
                return channel["id"]
    except SlackApiError as e:
        print(f"Error: {e}")
    return None

def get_latest_message(channel_id):
    try:
        result = slack_client.conversations_history(
            channel=channel_id,
            limit=1
        )
        if result["messages"]:
            return result["messages"][0]
        return None
    except SlackApiError as e:
        print(f"Error: {e}")
        return None

def process_with_azure_openai(message, system_prompt):
    message_text = extract_links_from_message(message["text"])
    try:
        response = client.chat.completions.create(
            model="dep-gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message_text}
            ],
            temperature=0.2,
            max_tokens=4096
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error in Azure OpenAI processing: {e}")
        return None

def extract_links_from_message(message):
    # Find URLs in the message using Slack's hyperlink syntax
    links = re.findall(r'\<([^|]+)\|([^>]+)\>', message)
    # for url, label in links:
        # Use the proper Slack link format: <URL|text>
        # message = message.replace(f"<{url}|{label}>", f"<{url}|here>")
    #     logger.info(message)
    return message

def send_direct_message(user_id, message):
    try:
        result = slack_client.chat_postMessage(
            channel=user_id,
            text=message,
            mrkdwn=True  # Only this parameter is needed for proper link formatting
        )
        print(f"Message sent successfully to user {user_id}")
        return result
    except SlackApiError as e:
        print(f"Error sending message: {e}")
        return None
    
system_prompt =  """You are an AI assistant in the company called Tomtom that analyzes internal Slack conversations. You are getting a post from an internal company announcement channel. 
    Your job is to analyze the post, and extarct the most important information for the company's employees who prefer TLDR and don't want to look at the full post. 
    Remember, your outcome must fully follow the original post, without adding or removing information. Your outcome should be within 3 sentenses, or 60 words in total. 
    So be precise, concise and infomative. For any urls detected in the original text, it will be presented in the form of '<actual-url | some content>'. In your generated outcome, 
    this should be kept exactly the same format as a whole for all urls, as this will make the urls embedded into the words and make the paagraphs more readable. 
    You also need to pay attention to the terms and special wordings that might be present, and you need to maintain the professional and accurate manner when summarizing. 
    The user must be able to see all important points accurately in your generated response. Also, your reponse must only include the summarization of the original post, no additional comments are allowed."""

def monitor_channel(channel_id, user_id):
    last_timestamp = None
    while True:
        try:
            # Get latest message
            latest_message = get_latest_message(channel_id)
    
            if latest_message:
                current_timestamp = latest_message["ts"]
                if last_timestamp != current_timestamp:
                    logger.info('-----------------------------------------')
                    logger.info('New message retrived.')
                    summary = process_with_azure_openai(latest_message, system_prompt)
                    if summary:
                        logger.info('Summary generated by the model. Sending to users right now.')
                        send_direct_message(user_id, summary)
                        logger.info('-----------------------------------------')
                    last_timestamp = current_timestamp
            
            time.sleep(5)  # Wait 5 seconds before next check
            
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    logger.info('Channel monitoring has started.')
    channel_id = get_channel_id('announcements-test')
    user_id = "U07P5J7AAEP"
    monitor_channel(channel_id, user_id)
