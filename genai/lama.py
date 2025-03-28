import requests
import json
import streamlit as st
from datetime import datetime
import time
import operation.dboperation
import operation.fileoperations
import os
import genai
import genai.gemini as gemini
# LM Studio API endpoint
LM_STUDIO_API_URL = "http://127.0.0.1:1234/v1/chat/completions"

sql_model = {"llama-3.2-1b-instruct":0, "llama-3.2-1b-instruct:2":0}
# query_model = ["meta-llama-3.1-8b-instruct@q4_k_m", "meta-llama-3.1-8b-instruct@q4_k_m:2", "meta-llama-3.1-8b-instruct@q4_k_m:3"]
query_model = {
    "meta-llama-3.1-8b-instruct@q4_k_m":0,
    "meta-llama-3.1-8b-instruct@q4_k_m:2":0,
    "meta-llama-3.1-8b-instruct@q4_k_m:3":0,
    "meta-llama-3.1-8b-instruct@q4_k_m:4":0
}

# query_model = {
#     "deepseek-r1-distill-llama-8b":0,
#     "deepseek-r1-distill-llama-8b:2":0
# }
# from sentence_transformers import SentenceTransformer
import torch
import numpy as np

# Load the semantic model (use a small model for faster inference)
# semantic_model = SentenceTransformer('all-MiniLM-L6-v2')

import numpy as np
import torch  # Required for tensor operations
import operation.dboperation
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Initialize TF-IDF Vectorizer
tfidf_vectorizer = TfidfVectorizer()

def get_cached_answer_semantically(question, threshold=0.9):
    """
    Checks for a semantically similar question in the cache.
    Returns the cached answer if a similar question is found.
    """
    conn = operation.dboperation.create_connection()
    cursor = conn.cursor()

    # Retrieve all questions and answers from the cache
    cursor.execute("SELECT id, question, answer FROM cache")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return None

    # Extract cached questions
    cached_questions = [row[1] for row in rows]

    # Fit and transform the questions using TF-IDF
    all_questions = [question] + cached_questions  # Include input question
    tfidf_matrix = tfidf_vectorizer.fit_transform(all_questions)

    # Compute cosine similarity
    similarities = cosine_similarity(tfidf_matrix[0], tfidf_matrix[1:])  # Compare input question with cached ones
    similarities = similarities.flatten()

    # Get the most similar question
    max_similarity_idx = np.argmax(similarities)
    max_similarity_score = similarities[max_similarity_idx]

    if max_similarity_score >= threshold:
        id = rows[max_similarity_idx][0]
        conn = operation.dboperation.create_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE cache
            SET frequency = frequency + 1, timestamp = CURRENT_TIMESTAMP
            WHERE id = ?;
        """, (id,))
        conn.commit()
        conn.close()

        return rows[max_similarity_idx][2]  # Return the cached answer

    return None

def update_cache_with_semantics(question,answer,role):
    """
    Updates the cache with semantic checking to avoid duplicate entries.
    If a similar question exists, updates its entry; otherwise, inserts a new row.
    """
    conn = operation.dboperation.create_connection()
    cursor = conn.cursor()
    similar_answer = get_cached_answer_semantically(question)
    if similar_answer:
        # If a similar question exists, update its entry
        cursor.execute("""
            UPDATE cache
            SET answer = ?, frequency = frequency + 1, timestamp = CURRENT_TIMESTAMP
            WHERE question = ?
        """, (answer, question))
        print("updated")
    else:
        # Insert a new row
        cursor.execute("""
    SELECT count(*) FROM cache;
    """)
    row_count = cursor.fetchone()[0]  # Get the actual count
    print(role)
    if not role == 'student_details' and not role == 'staff_details':
        if row_count < 100:
            cursor.execute("""
                INSERT INTO cache (question, answer, frequency)
                VALUES (?, ?, ?)
            """, (question, answer, 1))
            print("Inserted")
        else:
            # Delete entries with frequency = 1, ordered by timestamp
            cursor.execute("""
                DELETE FROM cache 
                WHERE frequency = 1
                AND timestamp = (SELECT MIN(timestamp) FROM cache WHERE frequency = 1)
            """)
            print("Deleted least recently used row")

    
    conn.commit()
    conn.close()

import random

def set_model(model=None):
    # selected_model = random.choice(list(query_model.keys()))
    selected_model = min(model,key=model.get)
    model[selected_model]+=1
    return selected_model,model

def retrive_sql_query(prompt, context):
    """
    Retrieves SQL query by interacting with the model.
    """
    global query_model
    model,models = set_model(query_model)
    query_model=models
    if not model:
        return None
    print("model:",model)
    current_datetime = datetime.now()
    formatted_datetime = current_datetime.strftime("%A, %B %d, %Y, at %I:%M %p").lower()
    role = str(st.session_state.role)
    formatted_role = role.replace("_details", '')

    prompt_role = 'student counsellor' if formatted_role == 'student' else 'staff assistant'
    context_with_datetime = f"{context} Today’s date and time: {formatted_datetime}."

    headers = {"Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": f"You are a helpful {prompt_role}."},
            {"role": "user", "content": f"Context: {context_with_datetime}\n\nQuestion: {prompt}"}
        ],
        "temperature": 0.7,
        "max_tokens": 2000,
    }

    try:
        # response = requests.post(LM_STUDIO_API_URL, headers=headers, json=payload)
        # response.raise_for_status()  # Check for HTTP errors
        # response_data = response.json()
        response=gemini.get_gemini_response(f"system:You are a helpful {prompt_role}."+f"user:Context: {context_with_datetime}\n\nQuestion: {prompt}")
        query_model[model]-=1
        return response
        # return response_data["choices"][0]["message"]["content"]
    except requests.RequestException as e:
        st.error(f"Request failed: {e}")
        return None
def backup_sql_query_maker(context,prompt,sql_data,query):
    """
    Retrieves SQL query by interacting with the model.
    """
    global sql_model
    model,models = set_model(sql_model)
    sql_model=models
    if not model:
        return None
    print("model:",model)
    current_datetime = datetime.now()
    formatted_datetime = current_datetime.strftime("%A, %B %d, %Y, at %I:%M %p").lower()
    role = str(st.session_state.role)
    formatted_role = role.replace("_details", '')

    prompt_role = 'student counsellor' if formatted_role == 'student' else 'staff assistant'
    context_with_datetime = f"{context} Today’s date and time: {formatted_datetime}."

    headers = {"Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": f"You are a helpful {prompt_role}."},
            {"role": "user", "content": f"Context: {context_with_datetime}\n\nQuestion: {prompt}\n\nworng query:{query}\n\nwrong answer:{sql_data}"}
        ],
        "temperature": 0.7,
        "max_tokens": 2000,
    }

    try:
        # response = requests.post(LM_STUDIO_API_URL, headers=headers, json=payload)
        # response.raise_for_status()  # Check for HTTP errors
        # response_data = response.json()
        response=gemini.get_gemini_response(f"system:You are a helpful {prompt_role}."+f"user:Context: {context_with_datetime}\n\nQuestion: {prompt}")
        sql_model[model]-=1
        return response
        # return response_data["choices"][0]["message"]["content"]
    except requests.RequestException as e:
        st.error(f"Request failed: {e}")
        return None
def query_lm_studio(prompt, context):
    """
    Queries the LM Studio model with a word scramble game running until the first token is generated.
    """
    cached_answer = get_cached_answer_semantically(prompt)
    if cached_answer:
        with st.chat_message('ai'):
            st.markdown(cached_answer)
        return cached_answer

    global query_model
    model, models = set_model(query_model)
    query_model = models
    role = st.session_state.get("role", "user")
    if role == 'student':
        prompt_role= 'student counsellor'
    elif role == 'staff' :
        prompt_role='staff_assistant'
    else:
        prompt_role='AI assistant'

    headers = {"Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": f"You are a helpful {prompt_role}."},
            {"role": "user", "content": f"Context: {context}\n\nQuestion: {prompt}"}
        ],
        "temperature": 0.7,
        "max_tokens": 2000,
        "stream": True
    }

    content_accumulated = ""
    first_token_received = False

    try:
        with st.status("generating data...", expanded=True) as status:
    
            response = gemini.get_gemini_response(f"system:You are a helpful {prompt_role}."+f"user:Context: {context}\n\nQuestion: {prompt}")
            # Start the model query in a streaming request
            # with requests.post(LM_STUDIO_API_URL, headers=headers, json=payload, stream=True) as response:
            #     response.raise_for_status()

            #     # Display the game until the first token is generated
                

            #     with st.chat_message("assistant"):
            #         content_placeholder = st.empty()
            #         container =st.container()
            #         with container:
            #             pass
            #             # word_scramble_game()
            #         status.update(label="Analysing...", state="running", expanded=True)

            #         # for line in response.iter_lines():
            #         #     if line:
            #         #         decoded_line = line.decode("utf-8").strip()
            #         #         if decoded_line.startswith("data:"):
            #         #             decoded_line = decoded_line[len("data:"):].strip()

            #         #         if decoded_line == "DONE":
            #         #             break

            #         #         try:
            #         #             status.update(label="generating...", state="running", expanded=True)
            #         #             json_data = json.loads(decoded_line)
            #         #             # print(json_data)
            #         #             content = json_data["choices"][0]["delta"].get("content", "")
            #         #             # content = json_data["choices"][0].get("text", "")
            #         #             if content:
            #         #                 container.empty()
            #         #                 content_accumulated += content
            #         #                 content_placeholder.markdown(content_accumulated)
            #         #                 # first_token_received = True  # Stop the game once the first token is generated
            #         #         except json.JSONDecodeError:
            #         #             continue
                    
            # Your long-running task code here
            status.update(label="generate complete!", state="complete", expanded=True)  
        # print(f"context :`{context}`")
        if context:                  
            update_cache_with_semantics(prompt, content_accumulated,role)
        query_model[model] -= 1
        # operation.fileoperations.append_to_file(os.path.abspath(os.path.join(os.path.dirname(__file__), "../dbs/data.txt")),f"\n\nQuestion:{prompt}\n\nrole:{prompt_role}\n\ntime:{datetime.now()}\n\nAnswer:{content_accumulated}")
        with open(os.path.abspath(os.path.join(os.path.dirname(__file__), "../dbs/data.txt")),"a") as f:
            f.write(f"\n\nQuestion:{prompt}\n\nrole:{prompt_role}\n\ntime:{datetime.now()}\n\nAnswer:{content_accumulated}")
        return response
    except requests.RequestException as e:
        st.error(f"An error occurred: {e}")
        return None

def query_heading_maker(prompt):
    """
    Retrieves SQL query by interacting with the model.
    """
    global query_model
    model,models = set_model(query_model)
    query_model=models
    if not model:
        return None
    print("model:",model)
    
    
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": f"You are a helpful single word creater."},
            {"role": "user", "content":"question :" + prompt+" ,reform the question into meaning full single word without any addtional and special characters"}
        ],
        "temperature": 0.7,
        "max_tokens": 20,
    }

    try:
        # response = requests.post(LM_STUDIO_API_URL, headers=headers, json=payload)
        # response.raise_for_status()  # Check for HTTP errors
        # response_data = response.json()
        response = gemini.get_gemini_response(f"system:You are a helpful single word creater."+f"user:question :" + prompt+" ,reform the question into meaning full single word without any addtional and special characters")
        query_model[model]-=1
        return response
        # return response_data["choices"][0]["message"]["content"]
    except requests.RequestException as e:
        st.error(f"Request failed: {e}")
        return None
def word_scramble_game():
    """
    A simple word scramble game that runs until the first token is generated.
    """
    st.title("🔀 Word Scramble Game")
    st.write("Unscramble the word and type your answer!")

    words = ["streamlit", "python", "programming", "developer", "challenge"]

    if "scrambled_word" not in st.session_state:
        original_word = random.choice(words)
        scrambled_word = "".join(random.sample(original_word, len(original_word)))
        st.session_state.scrambled_word = scrambled_word
        st.session_state.original_word = original_word

    # Display scrambled word
    st.write(f"Scrambled word: **{st.session_state.scrambled_word}**")

    # Input for the user's guess
    user_guess = st.text_input("Your guess:")
    if user_guess:
        if user_guess.lower() == st.session_state.original_word:
            st.success("🎉 Correct! You unscrambled the word.")
            # Reset the game
            original_word = random.choice(words)
            scrambled_word = "".join(random.sample(original_word, len(original_word)))
            st.session_state.scrambled_word = scrambled_word
            st.session_state.original_word = original_word
        else:
            st.error("❌ Incorrect! Try again.")

    # Return True if a token is generated to exit the game loop
    return st.session_state.get("first_token_generated", False)
