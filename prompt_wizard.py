import json
import requests
import time
from typing import List
import spacy
import math

nlp = spacy.load("en_core_web_sm")


def split_text_into_chunks(text, max_tokens=4000):
    doc = nlp(text)
    chunks = []
    current_chunk = []
    current_tokens = 0

    for sentence in doc.sents:
        sentence_tokens = len(sentence)
        if current_tokens + sentence_tokens <= max_tokens:
            current_chunk.append(sentence.text)
            current_tokens += sentence_tokens
        else:
            chunks.append(" ".join(current_chunk))
            current_chunk = [sentence.text]
            current_tokens = sentence_tokens

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks


def do_request(api_key, prompt_string, result_tokens, max_chars, temperature=0.7):
    if len(prompt_string) > max_chars:
        raise ValueError("prompt string is too long %d/%d" %
                         (len(prompt_string), max_chars))

    # call the openai completions API
    req_data = {
        "model": "text-davinci-003",
        "prompt": prompt_string,
        "temperature": temperature,
        "max_tokens": result_tokens
    }

    response = requests.post(
        "https://api.openai.com/v1/completions",
        headers={"Authorization": "Bearer " + api_key,
                 "Content-Type": "application/json"},
        data=json.dumps(req_data)
    )

    while not response.json().get("choices"):
        response_json = response.json()

        if response_json.get('error') is not None:
            response_type = response_json.get('error').get('type')
            if response_type in ["insufficient_quota", "invalid_request_error"]:
                print(response_json.get('error').get('message'))
                exit(1)

        print('error doing request, retrying in 5 seconds...')
        time.sleep(5)
        response = requests.post(
            "https://api.openai.com/v1/completions",
            headers={"Authorization": "Bearer " + api_key,
                     "Content-Type": "application/json"},
            data=json.dumps(req_data)
        )

    return response.json().get("choices")[0].get('text').strip()


TOKEN_BUFFER = 100


class Config:
    def __init__(
            self,

            max_tokens: int,
            result_tokens: int,
            final_prefix: str,
            final_suffix: str,
            compression_prefix: str,
            openai_api_key: str,
            temperature: float,
            target_tokens: int = 1500,
    ):
        self.max_tokens = max_tokens-TOKEN_BUFFER
        self.result_tokens = result_tokens-TOKEN_BUFFER
        self.max_chars = (max_tokens - result_tokens) * 4

        self.final_prefix = final_prefix
        self.final_suffix = final_suffix
        self.compression_prefix = compression_prefix
        self.openai_api_key = openai_api_key
        self.temperature = temperature
        self.target_tokens = target_tokens


# a single part of a prompt
class Snippet:
    def __init__(self, text, compression=False, config: Config = None):
        if config is None:
            raise ValueError("config must be provided")

        self._config = config

        # remove trailing/leading whitespace
        self.text = text.strip()
        # ensure there is at least one newline so snippets don't get merged weirdly
        self.text += "\n"

        self.text = text
        self.compression = compression

    def __len__(self):
        return len(self.text)

    def __str__(self):
        return self.text.strip()

    def subdivide(self):
        doc = nlp(self.text)
        sentences = list(doc.sents)

        if len(doc) <= self._config.target_tokens:
            return [self]

        chunks = []
        current_chunk = []
        current_chunk_tokens = 0

        for sent in sentences:
            sent_tokens = len(sent)

            if current_chunk_tokens + sent_tokens > self._config.target_tokens:
                chunks.append(Snippet(" ".join(current_chunk),
                              compression=self.compression, config=self._config))
                current_chunk = []
                current_chunk_tokens = 0

            current_chunk.append(sent.text)
            current_chunk_tokens += sent_tokens

        if current_chunk:
            chunks.append(Snippet(" ".join(current_chunk),
                          compression=self.compression, config=self._config))

        subdivided = []
        for chunk in chunks:
            subdivided.extend(chunk.subdivide())

        return subdivided

    def compress(self, prefix: str = None):
        if prefix is None:
            prefix = self._config.compression_prefix

        self.text = do_request(
            self._config.openai_api_key,
            prefix + self.text,
            self._config.result_tokens,
            self._config.max_chars,
            self._config.temperature
        )


nlp = spacy.load("en_core_web_sm")


class Prompt:
    def __init__(self, config: Config = None):
        """
        Create a prompt with a prefix and suffix
        :param prefix: the prefix snippet
        :param suffix: the suffix snippet
        :param max_tokens: the maximum number of tokens to generate
        :param result_tokens: the number of tokens to be reserved for use by the result,
                              these are subtracted from the max_tokens
        """

        if config is None:
            raise ValueError("config must be provided")

        self._config = config

        self._snippets: List[Snippet] = []
        self._prefix: Snippet = Snippet(
            config.final_prefix, compression=False, config=config)
        self._suffix: Snippet = Snippet(
            config.final_suffix, compression=False, config=config)

    # defragment snippets to fit within the max length
    def defragment(self):
        new_snippets = []

        total_length = 0
        accumulated_snippets = []

        for i in range(len(self._snippets)):

            # if the snippet is not compressible, add it to the accumulated snippets
            # as it cannot be compressed so it must be included in the final prompt regardless
            if not self._snippets[i].compression:
                new_snippets.append(self._snippets[i])
                total_length += len(self._snippets[i])
                continue

            if total_length + len(self._snippets[i]) > self._config.max_chars:
                # combine the accumulated snippets into a single snippet
                new_snippets.append(
                    Snippet("".join([str(s) for s in accumulated_snippets])))
                accumulated_snippets = [self._snippets[i]]
            else:
                accumulated_snippets.append(self._snippets[i])

        # if no new snippets were created, return the original snippets
        if len(new_snippets) == 0:
            return

        # add the remaining snippets
        if len(accumulated_snippets) > 0:
            new_snippets.append(
                Snippet("".join([str(s) for s in accumulated_snippets])))

        self._snippets = new_snippets

    def compress(self, prefix: str = None):
        if prefix is None:
            prefix = self._config.compression_prefix

        # walk backwards through each snippet and compress it,
        # if it allows compression, until the prompt is within the max length
        for i in range(len(self._snippets) - 1, -1, -1):
            if self._snippets[i].compression:
                original_len = len(self._snippets[i])
                self._snippets[i].compress(prefix=prefix)
                new_len = len(self._snippets[i])
                saved = original_len - new_len
                print(
                    "compressed snippet %d/%d from %d->%s (saved %d) chars - total:%d->target:%d" % (
                        i + 1,
                        len(self._snippets),
                        original_len,
                        new_len,
                        saved,
                        len(self),
                        self._config.max_chars
                    )
                )
                if len(self) < self._config.max_chars and False:
                    break

        # defragment the prompt to combine snippets that can be compressed
        # self.defragment()

    # add a snippet to the prompt
    def add(self, *snippets: Snippet):
        self._snippets.extend(snippets)

    # build the full prompt string
    def build(self) -> str:
        prompt = str(self._prefix)
        for s in self._snippets:
            prompt += str(s)
        prompt += str(self._suffix)
        return prompt

    def optimize(self):
        if len(self) < self._config.max_chars:
            return

        # compress the prompt
        self.compress()

        # if the prompt is still too long, join snippets together and subdivide them
        if len(self) > self._config.max_chars:
            print(
                "prompt is still too long, joining snippets together subdividing & compressing...")
            # join all snippets together
            joined = Snippet("".join([str(s) for s in self._snippets]))
            # subdivide the joined snippet
            self._snippets = joined.subdivide()

            # try compressing on a second pass
            self.compress()

    def __str__(self):
        return self.build()

    # calculate the number of characters in the prompt
    def __len__(self):
        return len(self.build())

    def get_snippets(self):
        return self._snippets

    def print_prompt_stats(self):
        print(f"prefix: {len(self._prefix)}")
        print(f"suffix: {len(self._suffix)}")
        print(f"snippets: {len(self._snippets)}")
        for s in self._snippets:
            print(f"  snippet: {len(s)}")
        print(f"total chars: {len(self)}/{self._config.max_chars}")
        print(f"total tokens: {len(self) // 4}/{self._config.max_tokens}")
