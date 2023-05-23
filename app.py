import os
import uuid
import datetime

import requests
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from llama_index import GPTSimpleVectorIndex, SimpleDirectoryReader, Document
from newspaper import Article
from summarize import handle_text

# Set up Flask app
app = Flask(__name__)
CORS(app)

# API Key
API_KEY = os.getenv("OPENAI_API_KEY")

current_date = datetime.datetime.now().strftime('%Y-%m-%d')

# Initialize conversation history and index path
index_path = "index.json"
conversation_history = []  # Define conversation_history as a global variable


# Load or create the index and initialize conversation history
def load_or_create_index():
    global conversation_history
    conversation_history = []

    with open("system.txt", "r") as file:
        system_content = file.read()

    conversation_history.append({"role": "system", "content": system_content})

    if os.path.exists(index_path):
        return GPTSimpleVectorIndex.load_from_disk(index_path)
    else:
        documents = SimpleDirectoryReader('data').load_data()
        index = GPTSimpleVectorIndex.from_documents(documents)
        index.save_to_disk(index_path)
        return index

llama_index = load_or_create_index()

# Update index with the initial conversation_history
def update_index(content, role, doc_id):
    doc = Document(content, doc_id=doc_id)
    llama_index.insert(doc)
    llama_index.save_to_disk(index_path)


# Save content to data directory and return file_id
def save_to_data_directory(content):
    if not os.path.exists("data"):
        os.makedirs("data")

    file_id = str(uuid.uuid4())
    file_path = os.path.join("data", f"{file_id}.txt")

    with open(file_path, "w") as file:
        file.write(content)

    return file_id


def scrape_url(url):
    try:
        article = Article(url)
        article.download()
        article.parse()

        text = article.text
        return text
    except:
        return None


# Count characters in a text
def count_characters(text):
    return len(text)


# Truncate conversation_history to keep it below 8000 characters
def truncate_conversation_history():
    global conversation_history
    total_characters = sum([count_characters(msg["content"]) for msg in conversation_history])
    while total_characters > 8000:
        removed_message = conversation_history.pop(0)
        total_characters -= count_characters(removed_message["content"])


def reset_conversation_history():
    global conversation_history
    conversation_history = []

    with open("system.txt", "r") as file:
        system_content = file.read()

    conversation_history.append({"role": "system", "content": system_content})


def summarize_text(text):
    summary = handle_text(text)

    filename = "notes/" + datetime.datetime.now().strftime('%Y-%m-%d_%H_%M_%S') + "_summary.md"

    os.makedirs(os.path.dirname(filename), exist_ok=True)

    with open(filename, "w") as file:
        file.write(summary)
        file.flush()
        file.close()

    return summary

# Get GPT response based on user input
def get_gpt_response(action, prompt):
    global conversation_history
    if action == "summarize":
        # Add the original text to the index before summarization
        file_id_original = save_to_data_directory(prompt)
        update_index(prompt, "user", file_id_original)

        bot_response = summarize_text(prompt)

        # Add the summarized text to the index after summarization
        file_id_summary = save_to_data_directory(bot_response)
        update_index(bot_response, "assistant", file_id_summary)
    elif action == "query":
        response = llama_index.query(prompt)
        bot_response = str(response)
    elif action == "archive":
        # Combine the content of conversation_history into a single string
        content = "\n".join([msg["content"] for msg in conversation_history])
        bot_response = summarize_text(content)

        # Add the original content to the index before summarization
        file_id_original = save_to_data_directory(content)
        update_index(content, "user", file_id_original)

        # Add the summarized content to the index after summarization
        file_id_summary = save_to_data_directory(bot_response)
        update_index(bot_response, "assistant", file_id_summary)
    elif action == "reset":
        reset_conversation_history()
        bot_response = "Conversation history has been reset."

    elif action == "url":
        content = scrape_url(prompt)
        if content:
            bot_response = summarize_text(content)

            # Add the original content to the index before summarization
            file_id_original = save_to_data_directory(content)
            update_index(content, "user", file_id_original)

            # Add the summarized content to the index after summarization
            file_id_summary = save_to_data_directory(bot_response)
            update_index(bot_response, "assistant", file_id_summary)
        else:
            bot_response = "Error: Unable to retrieve or process content from the provided URL."
    else:
        headers = {"Authorization": f"Bearer {API_KEY}"}
        conversation_history.append({"role": "user", "content": prompt})
        update_index(prompt, "user", f"user_{len(conversation_history) - 1}")
        truncate_conversation_history()
        data = {
            "model": "gpt-3.5-turbo",
            "messages": conversation_history,
            "max_tokens": 500,
            "temperature": 0.9,
        }
        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data)

        if response.status_code == 200:
            bot_response = response.json()['choices'][0]['message']['content'].strip()
        else:
            return f"Error: {response.status_code}"

    conversation_history.append({"role": "assistant", "content": bot_response})
    update_index(bot_response, "assistant", f"assistant_{len(conversation_history) - 1}")
    return bot_response


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/system', methods=['GET'])
def get_system_content():
    with open("system.txt", "r") as file:
        content = file.read()
    return jsonify({'content': content})

@app.route('/system', methods=['POST'])
def update_system_content():
    content = request.form['content']
    with open("system.txt", "w") as file:
        file.write(content)
    return jsonify({'message': 'System content updated successfully'})

@app.route('/message', methods=['POST'])
def message():
    user_input = request.form['input']
    action = request.form['action']
    print(f"Action: {action}")
    response = get_gpt_response(action, user_input)
    if response.startswith("Error"):
        return jsonify({'response_type': 'error', 'response': response})
    else:
        return jsonify({'response_type': 'success', 'response': response})


if __name__ == '__main__':
    app.run(host="127.0.0.1", port=5000, debug=True)
