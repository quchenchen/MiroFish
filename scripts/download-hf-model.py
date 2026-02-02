#!/usr/bin/env python3
import os

# Set longer timeout for HuggingFace
os.environ['HF_HUB_CACHE'] = '/root/.cache/huggingface/hub'
os.environ['TRANSFORMERS_CACHE'] = '/root/.cache/huggingface/transformers'
os.environ['HF_HUB_DOWNLOAD_TIMEOUT'] = '120'
os.environ['HF_HUB_ENABLE_HF_TRANSFER'] = '0'

print('Downloading HuggingFace model paraphrase-multilingual-MiniLM-L12-v2...')

# Monkey-patch to increase timeout
import huggingface_hub
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

session = requests.Session()
retry = Retry(total=10, connect=10, read=10, backoff_factor=1)
adapter = HTTPAdapter(max_retries=retry)
session.mount('http://', adapter)
session.mount('https://', adapter)

# Patch huggingface_hub to use our session
original_session = huggingface_hub.utils._requests.HttpBackoff
huggingface_hub.utils._requests.HttpBackoff = lambda: session

from sentence_transformers import SentenceTransformer

# Create model with timeout
model = SentenceTransformer(
    'paraphrase-multilingual-MiniLM-L12-v2',
    cache_folder='/root/.cache/huggingface/hub'
)
print('Model cached successfully!')
