import json
from pathlib import Path
from elasticsearch import Elasticsearch, helpers

from config import ELASTIC_BASIC_AUTH, ELASTIC_INDEX, ELASTIC_URL

# -----------------------------------------
# CONNECT TO ELASTICSEARCH
# -----------------------------------------

es = Elasticsearch(
    ELASTIC_URL,
    basic_auth=ELASTIC_BASIC_AUTH,
    verify_certs=False,
    request_timeout= 120
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
    es.indices.put_mapping(index=INDEX_NAME, body=MAPPING)
else:
    es.indices.create(index=INDEX_NAME, body={"mappings": MAPPING})


def parse_speed(value):
    import re

    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else 0


def slugify(value):
    import re

    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")


def build_class_key(doc):
    return "|".join([
        doc.get("country") or "Unknown",
        doc.get("section") or "Unknown",
        doc.get("class_name") or "Unknown Class",
        doc.get("type") or "Unknown",
    ])

# -----------------------------------------
# LOAD JSON FILE
# -----------------------------------------

BASE_DIR = Path(__file__).resolve().parents[1]
EMBEDDED_DATA_FILE = BASE_DIR / "data" / "flattened_ships_with_embeddings.json"
BASE_DATA_FILE = BASE_DIR / "data" / "flattened_ships_with_base64.json"
DATA_FILE = EMBEDDED_DATA_FILE if EMBEDDED_DATA_FILE.exists() else BASE_DATA_FILE

with open(DATA_FILE, "r", encoding="utf-8") as file:
    data = json.load(file)

print(f"Loaded {len(data)} records from JSON file.")

# -----------------------------------------
# PREPARE DOCUMENTS
# -----------------------------------------

actions = []
seen_ids = {}

for row_number, doc in enumerate(data, start=1):
    specifications = doc.get("specifications", {})
    class_key = build_class_key(doc)
    document_id = doc.get("id") or slugify(
        "|".join([
            class_key,
            doc.get("ship_name") or "",
            doc.get("ship_number") or "",
            str(row_number),
        ])
    )
    seen_ids[document_id] = seen_ids.get(document_id, 0) + 1
    if seen_ids[document_id] > 1:
        document_id = f"{document_id}_{seen_ids[document_id]}"

    source = {
        "id": document_id,
        "class_key": class_key,
        "slug": slugify(class_key),
        "country": doc.get("country", ""),
        "section": doc.get("section", ""),
        "class_name": doc.get("class_name", ""),
        "type": doc.get("type", ""),
        "description": doc.get("description", ""),
        "ship_image": doc.get("ship_image", ""),
        "ship_image_base64": doc.get("ship_image_base64", ""),
        "ship_name": doc.get("ship_name", ""),
        "ship_number": doc.get("ship_number", ""),
        "builder": doc.get("builder", ""),
        "ordered": doc.get("ordered", ""),
        "launched": doc.get("launched", ""),
        "commissioned": doc.get("commissioned", ""),
        "status": doc.get("status", ""),
        "speed_knots": parse_speed(specifications.get("Speed, knots")),
        "specifications": specifications,
    }

    if doc.get("image_embedding"):
        source["image_embedding"] = doc["image_embedding"]

    actions.append({
        "_index": INDEX_NAME,
        "_id": document_id,
        "_source": source
    })

# -----------------------------------------
# INSERT DATA
# -----------------------------------------

helpers.bulk(
    es.options(request_timeout=120),
    actions,
    chunk_size=50,          
    max_retries=5
)

print(f"\nInserted {len(actions)} documents successfully.")

# -----------------------------------------
# REFRESH INDEX
# -----------------------------------------

es.indices.refresh(index=INDEX_NAME)


# TOTAL DOCUMENT COUNT


count = es.count(index=INDEX_NAME)
embedding_count = es.count(
    index=INDEX_NAME,
    query={"exists": {"field": "image_embedding"}},
)

print(f"\nTotal Documents in Index: {count['count']}")
print(f"Documents with Image Embeddings: {embedding_count['count']}")

# testing documents

print("\n========== COUNTRY FILTER ==========\n")

response = es.search(
    index=INDEX_NAME,
    body={
        "size": 5,
        "query": {
            "term": {
                "country": "Albania"
            }
        }
    }
)

for hit in response["hits"]["hits"]:

    source = hit["_source"]

    print(f"Ship Name     : {source['ship_name']}")
    print(f"Class Name    : {source['class_name']}")
    print(f"Country       : {source['country']}")
    print("-" * 50)
