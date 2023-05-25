import re
import subprocess
import sys
import os
import requests
import hashlib
from prompt_wizard import Prompt, Snippet, do_request, Config
import spacy
from typing import Tuple

OPENAI_API_KEY = os.environ['OPENAI_API_KEY']

RESULT_TOKENS = 400
TOKENS_PER_REQUEST = 3500

FINAL_PREFIX = """Extract details of the following text. Write an appropriate heading for each talking point, followed by a paragraph explaining what was discussed. 

Here is the text:
```
"""

FINAL_SUFFIX = """
```
"""

COMPRESSION_PREFIX = "Write a paragraph with the important information from the following text: \n\n"
KEYWORD_PREFIX = "List the most relevant keywords (e.g. #tag1, #tag2) (lowercase, single words) for the following text: \n\n"

TEMPERATURE = 0.0


def clean_text(text: str) -> str:
    timestamp_pattern = r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})"
    lines = text.strip().split("\n")
    cleaned_lines = [line for line in lines if not re.match(timestamp_pattern, line) and line != ""]
    return " ".join(cleaned_lines).strip()

def generate_summary(prompt_config, content):
    prompt = Prompt(prompt_config)
    content_snippet = Snippet(content, compression=True, config=prompt_config)
    prompt.add(*content_snippet.subdivide())
    prompt.optimize()
    final_prompt = prompt.build()
    
    final_response = ""
    while True:
        final_response = do_request(prompt_config.openai_api_key, final_prompt,
                                    prompt_config.result_tokens,
                                    prompt_config.max_chars,
                                    prompt_config.temperature)
        last_paragraph = final_response.split('\n\n')[-1]
        last_paragraph_words = last_paragraph.split(' ')
        if len(last_paragraph_words) > 1 and last_paragraph_words[-1].endswith('.'):
            break
        final_response = '\n\n'.join(final_response.split('\n\n')[:-1])
        content_snippet = Snippet(last_paragraph, compression=True, config=prompt_config)
        prompt = Prompt(prompt_config)
        prompt.add(*content_snippet.subdivide())
        prompt.optimize()
        final_prompt = prompt.build()

    return final_response, prompt

def generate_keywords(prompt_config, prompt):
    keyword_prompt = Prompt(prompt_config)
    keyword_prompt.add(*prompt.get_snippets())
    keyword_prompt.optimize()
    return do_request(prompt_config.openai_api_key, keyword_prompt.build(),
                      prompt_config.result_tokens, prompt_config.max_chars, prompt_config.temperature)

def handle_text(text: str, max_section_length: int = 5000) -> str:
    
    transcript_clean = clean_text(text)
    print("1. Cleaning text")
    prompt_config = Config(
        max_tokens=TOKENS_PER_REQUEST,
        result_tokens=RESULT_TOKENS,
        openai_api_key=OPENAI_API_KEY,
        final_suffix=FINAL_SUFFIX,
        final_prefix=FINAL_PREFIX,
        compression_prefix=COMPRESSION_PREFIX,
        temperature=TEMPERATURE
    )

    print("2. Splitting text into sections")

    # Load the spaCy model
    nlp = spacy.load("en_core_web_sm")

    # Split the text into sections using spaCy
    sections = []
    current_section = ""
    doc = nlp(transcript_clean)

    for sent in doc.sents:
        if len(current_section) + len(sent.text) < max_section_length:
            current_section += sent.text
        else:
            sections.append(current_section.strip())
            current_section = sent.text

    sections.append(current_section.strip())

    print("3. Processing sections")
    # Process each section and accumulate the summaries and keywords
    final_summary = ""
    final_keywords = []
    for i, section in enumerate(sections):
        print(f"  3.1. Processing section {i + 1}/{len(sections)}")
        summary, summary_prompt = generate_summary(prompt_config, section)
        final_summary += summary
        print(f"  3.2. Generating keywords for section {i + 1}/{len(sections)}")

        keyword_prompt_config = Config(
            max_tokens=TOKENS_PER_REQUEST,
            result_tokens=RESULT_TOKENS,
            openai_api_key=OPENAI_API_KEY,
            final_suffix="",
            final_prefix=KEYWORD_PREFIX,
            compression_prefix=KEYWORD_PREFIX,
            temperature=TEMPERATURE
        )
        keywords = generate_keywords(keyword_prompt_config, summary_prompt)
        final_keywords.extend(keywords.split())

    print("4. Combining results")

    # Combine the keywords into a single string
    combined_keywords = " ".join(set(final_keywords))  # Using set to remove duplicates

    return final_summary + "\n\n\n" + combined_keywords



def url_to_filename(url):
    new_string = url.replace("/", "-")
    return hashlib.md5(new_string.encode()).hexdigest()+".md"


def handle_url(url: str) -> Tuple[str, str]:
    from bs4 import BeautifulSoup

    # get url contents
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.102 Safari/537.36'}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print("Error fetching url")
        # print response body
        print(response.text)
        sys.exit(1)

    html = response.content

    soup = BeautifulSoup(html, 'html.parser')

    # get the text value of every html element and concatenate it
    text_val = ''
    for element in soup.find_all(["title", "meta", "section", "pre", "code", "p", "h1", "h2", "h3", "h4", "h5", "h6"]):
        element_text = element.text

        if element.name == "meta":
            if element.get("name") is not None and element["name"] in ["description", "keywords", "author", "og:title", "og:description", "og:url"]:
                text_val += element_text + "\n"

            continue
        text_val += element.text.strip() + "\n"

    text_val = text_val.strip()

    prompt_config = Config(
        max_tokens=TOKENS_PER_REQUEST,
        result_tokens=RESULT_TOKENS,
        openai_api_key=OPENAI_API_KEY,
        final_prefix="""Please summarize the following text, write an appropriate heading for each topic, followed by a paragraph explaining what was discussed:
        ```
        """,
        final_suffix="""
        ```
        """,
        compression_prefix=COMPRESSION_PREFIX,
        temperature=TEMPERATURE
    )

    prompt = Prompt(prompt_config)

    prompt.add(*Snippet(text_val, compression=True,
               config=prompt_config).subdivide())

    print("\n\nbefore optimization\n")
    prompt.print_prompt_stats()
    print("\n\n")
    prompt.optimize()

    print("\n\nafter optimization\n")
    prompt.print_prompt_stats()
    final_prompt = prompt.build()

    print("\n\nfinal prompt\n")
    print(final_prompt)

    final_response = do_request(
        prompt_config.openai_api_key,
        final_prompt,
        prompt_config.result_tokens,
        prompt_config.max_chars,
        prompt_config.temperature
    )

    # generate a filename from the URL using md5
    new_filename = url_to_filename(url)

    return new_filename, final_response
