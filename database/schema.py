import sys
from pathlib import Path

from elasticsearch import Elasticsearch

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from config import ELASTIC_BASIC_AUTH, ELASTIC_INDEX, ELASTIC_URL


es = Elasticsearch(
    ELASTIC_URL,
    basic_auth=ELASTIC_BASIC_AUTH,
    verify_certs=False,
    request_timeout=60,
)

INDEX_NAME = ELASTIC_INDEX

MAPPING = {
    "properties": {
        "id": {"type": "keyword"},
        "class_key": {"type": "keyword"},
        "slug": {"type": "keyword"},
        "country": {"type": "keyword"},
        "section": {"type": "keyword"},
        "class_name": {
            "type": "text",
            "fields": {"keyword": {"type": "keyword"}},
        },
        "type": {"type": "keyword"},
        "description": {"type": "text"},
        "ship_image": {"type": "keyword"},
        "ship_name": {
            "type": "text",
            "fields": {"keyword": {"type": "keyword"}},
        },
        "ship_number": {"type": "keyword"},
        "builder": {
            "type": "text",
            "fields": {"keyword": {"type": "keyword"}},
        },
        "ordered": {"type": "text"},
        "launched": {"type": "text"},
        "commissioned": {"type": "text"},
        "status": {"type": "text"},
        "speed_knots": {"type": "integer"},
        "ship_image_base64": {"type": "text", "index": False},
        "specifications": {"type": "object", "dynamic": True},
        "image_embedding": {
            "type": "dense_vector",
            "dims": 512,
            "index": True,
            "similarity": "cosine",
        },
    }
}


if es.indices.exists(index=INDEX_NAME):
    print("INDEX_NAME =", INDEX_NAME)

    try:
        print(es.info())
    except Exception as e:
        print("Connection Error:", e)

    print("Creating index...")
else:
    try:
        es.indices.create(
            index=INDEX_NAME,
            body={"mappings": MAPPING}
        )
        print("Index created successfully")
    except Exception as e:
        print("ERROR:")
        print(e)
