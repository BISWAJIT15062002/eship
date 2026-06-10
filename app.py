from __future__ import annotations

import re
import base64
import json
from pathlib import Path
from typing import Any
from functools import lru_cache

from flask import Flask, abort, jsonify, render_template, request
from elasticsearch import Elasticsearch, helpers

from config import ELASTIC_BASIC_AUTH, ELASTIC_INDEX, ELASTIC_URL


BASE_DIR = Path(__file__).resolve().parent

INDEX_NAME = ELASTIC_INDEX

es = Elasticsearch(
    ELASTIC_URL,
    basic_auth=ELASTIC_BASIC_AUTH,
    verify_certs=False,
    ssl_show_warn=False,
    request_timeout=10,
    max_retries=2,
    retry_on_timeout=True,
)

ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_SEARCH_DOCUMENTS = 1000
MAX_INNER_SHIPS = 100
TEXT_FIELDS = [
    "country^4",
    "section^3",
    "type^4",
    "class_name^5",
    "ship_name^5",
    "ship_number^2",
    "builder^3",
    "description^2",
    "status",
    "ordered",
    "launched",
    "commissioned",
    "specifications.*",
]


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

    @app.get("/")
    def home():
        return render_template("index.html", facets=build_elastic_facets(empty_search_request()))

    @app.get("/classes/<slug>")
    def class_details(slug: str):
        ship_class = find_ship_class_by_slug(slug)
        if ship_class is None:
            abort(404)
        return render_template("details.html", ship_class=ship_class)

    @app.get("/image-search")
    def image_search():
        return render_template("image_search.html", matches=[], uploaded_image="")

    @app.post("/image-search")
    def image_search_upload():
        image_file = request.files.get("ship_image")
        if image_file is None or not image_file.filename:
            return render_template(
                "image_search.html",
                matches=[],
                uploaded_image="",
                error="Please choose a ship image before searching.",
            ), 400

        if not is_allowed_image(image_file.filename):
            return render_template(
                "image_search.html",
                matches=[],
                uploaded_image="",
                error="Upload a JPG, PNG, or WEBP image.",
            ), 400

        image_bytes = image_file.read()
        if not image_bytes:
            return render_template(
                "image_search.html",
                matches=[],
                uploaded_image="",
                error="The selected image is empty.",
            ), 400

        mimetype = image_file.mimetype or "image/jpeg"
        uploaded_image = (
            f"data:{mimetype};base64,"
            f"{base64.b64encode(image_bytes).decode('ascii')}"
        )

        try:
            query_embedding = get_query_image_embedding(uploaded_image)
            hits = search_similar_ship_documents(query_embedding, k=60)
            matches = normalize_similarity_hits(hits)[:12]
        except Exception as exc:
            return render_template(
                "image_search.html",
                matches=[],
                uploaded_image=uploaded_image,
                error=f"Image similarity search failed: {exc}",
            ), 500

        return render_template(
            "image_search.html",
            matches=matches,
            uploaded_image=uploaded_image,
        )

    @app.get("/api/classes")
    def api_classes():
        search_request = get_search_request()
        result = search_ship_classes(search_request)

        return jsonify({
            "items": result["items"],
            "total": result["total"],
            "page": search_request["page"],
            "page_size": search_request["page_size"],
            "facets": result["facets"],
        })

    @app.get("/api/classes/<slug>")
    def api_class_details(slug: str):
        ship_class = find_ship_class_by_slug(slug)
        if ship_class is None:
            abort(404)
        return jsonify(ship_class)

    @app.post("/api/chat")
    def api_chat():
        payload = request.get_json(silent=True) or {}
        message = str(payload.get("message", "")).strip()
        if not message:
            return jsonify({"reply": "Please ask about a ship class, country, type, speed, or builder."})

        reply = build_chat_reply(message)
        return jsonify({"reply": reply})

    return app


@lru_cache(maxsize=1)
def load_ship_classes() -> list[dict[str, Any]]:
    try:
        raw_data = fetch_elastic_sources({"match_all": {}})
    except Exception:
        raw_data = load_local_ship_data()

    if raw_data and isinstance(raw_data[0], dict) and "data" in raw_data[0]:
        return normalize_merged_output(raw_data)

    if raw_data and isinstance(raw_data[0], dict) and "ship_name" in raw_data[0]:
        return normalize_flattened_ships(raw_data)

    return [
        normalize_class(item, index)
        for index, item in enumerate(raw_data, start=1)
    ]


def get_search_request() -> dict[str, Any]:
    search_request = empty_search_request()
    search_request.update({
        "query": request.args.get("q", "").strip(),
        "country": request.args.get("country", "").strip(),
        "section": request.args.get("section", "").strip(),
        "type": request.args.get("type", "").strip(),
        "builder": request.args.get("builder", "").strip(),
        "speed": request.args.get("speed", "").strip(),
        "page": positive_int(request.args.get("page"), 1),
        "page_size": min(positive_int(request.args.get("page_size"), 20), 100),
    })
    return search_request


def empty_search_request() -> dict[str, Any]:
    return {
        "query": "",
        "country": "",
        "section": "",
        "type": "",
        "builder": "",
        "speed": "",
        "page": 1,
        "page_size": 20,
    }


def positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def search_ship_classes(search_request: dict[str, Any]) -> dict[str, Any]:
    query = build_elastic_query(search_request)
    page = search_request["page"]
    page_size = search_request["page_size"]
    offset = (page - 1) * page_size

    try:
        response = es.options(request_timeout=30).search(
            index=INDEX_NAME,
            body={
                "from": offset,
                "size": page_size,
                "query": query,
                "sort": [
                    {"_score": "desc"},
                    {"country": "asc"},
                    {"class_name.keyword": "asc"},
                ],
                "collapse": {
                    "field": "class_key",
                    "inner_hits": {
                        "name": "ships",
                        "size": MAX_INNER_SHIPS,
                        "sort": [{"ship_name.keyword": "asc"}],
                    },
                },
            },
        )
        hits = response.get("hits", {}).get("hits", [])
        classes = normalize_collapsed_hits(hits)
        total = count_matching_classes(query)
    except Exception:
        try:
            records = fetch_elastic_sources(query, limit=MAX_SEARCH_DOCUMENTS)
        except Exception:
            records = []
        all_classes = normalize_elastic_records(records)
        total = len(all_classes)
        classes = all_classes[offset:offset + page_size]

    return {
        "items": classes,
        "total": total,
        "facets": build_elastic_facets(search_request),
    }


def find_ship_class_by_slug(slug: str) -> dict[str, Any] | None:
    classes = normalize_elastic_records(fetch_elastic_sources({"term": {"slug": slug}}, limit=MAX_INNER_SHIPS))
    if classes:
        return classes[0]

    classes = normalize_elastic_records(fetch_elastic_sources({"match_all": {}}, limit=MAX_SEARCH_DOCUMENTS))
    return next((item for item in classes if item["slug"] == slug), None)


def build_elastic_query(search_request: dict[str, Any]) -> dict[str, Any]:
    filters: list[dict[str, Any]] = []
    inferred_filters = infer_filters_from_text(search_request.get("query", ""))
    for key in ("country", "section", "type"):
        value = search_request.get(key) or inferred_filters.get(key)
        if value:
            filters.append({"term": {key: value}})

    builder = search_request.get("builder") or inferred_filters.get("builder")
    if builder:
        filters.append({"term": {"builder.keyword": builder}})

    speed = parse_speed(search_request.get("speed"))
    if speed:
        filters.append({"range": {"speed_knots": {"gte": speed}}})

    text = clean_user_query(remove_inferred_terms(search_request.get("query", ""), inferred_filters))
    must: list[dict[str, Any]] = []
    should: list[dict[str, Any]] = []
    if text:
        if len(text.split()) > 1:
            must.append(
                {
                    "multi_match": {
                        "query": text,
                        "fields": TEXT_FIELDS,
                        "type": "cross_fields",
                        "operator": "and",
                    }
                }
            )
        should.extend([
            {
                "multi_match": {
                    "query": text,
                    "fields": TEXT_FIELDS,
                    "type": "phrase",
                    "slop": 3,
                    "boost": 3,
                }
            },
            {
                "multi_match": {
                    "query": text,
                    "fields": TEXT_FIELDS,
                    "type": "cross_fields",
                    "operator": "and",
                    "boost": 2,
                }
            },
            {
                "multi_match": {
                    "query": text,
                    "fields": TEXT_FIELDS,
                    "type": "best_fields",
                    "operator": "or",
                    "fuzziness": "AUTO",
                }
            },
            {
                "simple_query_string": {
                    "query": text,
                    "fields": TEXT_FIELDS,
                    "default_operator": "or",
                }
            },
        ])

    if not filters and not must and not should:
        return {"match_all": {}}

    query: dict[str, Any] = {"bool": {}}
    if filters:
        query["bool"]["filter"] = filters
    if must:
        query["bool"]["must"] = must
    if should:
        query["bool"]["should"] = should
        query["bool"]["minimum_should_match"] = 1
    return query


def infer_filters_from_text(value: str) -> dict[str, str]:
    normalized = normalize_query_text(value)
    if not normalized:
        return {}

    inferred: dict[str, str] = {}
    for key, field in (
        ("country", "country"),
        ("section", "section"),
        ("type", "type"),
        ("builder", "builder.keyword"),
    ):
        for option in get_filter_terms(field):
            option_text = normalize_query_text(option)
            if option_text and re.search(rf"\b{re.escape(option_text)}\b", normalized):
                inferred[key] = option
                break
    return inferred


def remove_inferred_terms(value: str, inferred_filters: dict[str, str]) -> str:
    cleaned = value
    for term in inferred_filters.values():
        cleaned = re.sub(re.escape(term), " ", cleaned, flags=re.IGNORECASE)
    return cleaned


def normalize_query_text(value: str) -> str:
    return " ".join(re.findall(r"[a-zA-Z0-9]+", str(value).lower()))


@lru_cache(maxsize=16)
def get_filter_terms(field: str) -> tuple[str, ...]:
    try:
        response = es.options(request_timeout=5).search(
            index=INDEX_NAME,
            body={
                "size": 0,
                "aggs": {
                    "values": {
                        "terms": {
                            "field": field,
                            "size": 1000,
                        }
                    }
                },
            },
        )
    except Exception:
        return ()

    buckets = response.get("aggregations", {}).get("values", {}).get("buckets", [])
    return tuple(bucket["key"] for bucket in buckets if bucket.get("key"))


def clean_user_query(value: str) -> str:
    stop_words = {
        "a", "an", "the", "have", "has", "with", "from", "also", "and", "or",
        "of", "in", "is", "are", "show", "find", "search", "ship", "ships",
        "class", "classes", "please", "me", "give", "tell", "about",
    }
    tokens = re.findall(r"[a-zA-Z0-9]+", value.lower())
    meaningful = [token for token in tokens if token not in stop_words]
    return " ".join(meaningful)


def fetch_elastic_sources(query: dict[str, Any], limit: int = MAX_SEARCH_DOCUMENTS) -> list[dict[str, Any]]:
    results = helpers.scan(
        es.options(request_timeout=45),
        index=INDEX_NAME,
        query={
            "query": query,
            "sort": ["_score", {"country": "asc"}, {"class_name.keyword": "asc"}],
        },
        size=500,
        preserve_order=True,
    )

    records: list[dict[str, Any]] = []
    for hit in results:
        source = hit.get("_source", {})
        if source:
            records.append(source)
        if len(records) >= limit:
            break
    return records


def count_matching_classes(query: dict[str, Any]) -> int:
    try:
        response = es.search(
            index=INDEX_NAME,
            body={
                "size": 0,
                "query": query,
                "aggs": {
                    "classes": {
                        "cardinality": {
                            "field": "class_key",
                            "precision_threshold": 40000,
                        }
                    }
                },
            },
        )
        return int(response.get("aggregations", {}).get("classes", {}).get("value", 0))
    except Exception:
        return 0


def normalize_collapsed_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for hit in hits:
        inner_hits = (
            hit.get("inner_hits", {})
            .get("ships", {})
            .get("hits", {})
            .get("hits", [])
        )
        if inner_hits:
            records.extend(inner_hit.get("_source", {}) for inner_hit in inner_hits)
        else:
            records.append(hit.get("_source", {}))

    return normalize_elastic_records([record for record in records if record])


def normalize_elastic_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if records and isinstance(records[0], dict) and "data" in records[0]:
        return normalize_merged_output(records)
    if records and isinstance(records[0], dict) and "ship_name" in records[0]:
        return normalize_flattened_ships(records)
    return [
        normalize_class(item, index)
        for index, item in enumerate(records, start=1)
    ]


def load_local_ship_data() -> list[dict[str, Any]]:
    embedded_file = BASE_DIR / "data" / "flattened_ships_with_embeddings.json"
    base_file = BASE_DIR / "data" / "flattened_ships_with_base64.json"
    data_file = embedded_file if embedded_file.exists() else base_file

    if not data_file.exists():
        return []

    with data_file.open("r", encoding="utf-8") as file:
        return json.load(file)


def search_similar_ship_documents(query_embedding: list[float], k: int = 10) -> list[dict[str, Any]]:
    if len(query_embedding) != 512:
        raise RuntimeError(
            f"Image embedding has {len(query_embedding)} dimensions; Elasticsearch expects 512."
        )

    embedding_count = count_documents_with_image_embeddings()
    if embedding_count == 0:
        raise RuntimeError(
            "No image embeddings found in Elasticsearch. Run database/doc_mapping.py to index embedded ship data."
        )
    effective_k = min(k, embedding_count)
    num_candidates = min(max(effective_k * 10, 50), embedding_count)

    search = es.options(request_timeout=45)
    source_filter = {"excludes": ["image_embedding"]}

    try:
        response = search.search(
            index=INDEX_NAME,
            size=effective_k,
            source=source_filter,
            knn={
                "field": "image_embedding",
                "query_vector": query_embedding,
                "k": effective_k,
                "num_candidates": num_candidates,
                "filter": {"exists": {"field": "image_embedding"}},
            },
        )
    except Exception:
        response = search.search(
            index=INDEX_NAME,
            body={
                "size": effective_k,
                "_source": source_filter,
                "query": {
                    "script_score": {
                        "query": {"exists": {"field": "image_embedding"}},
                        "script": {
                            "source": "cosineSimilarity(params.query_vector, 'image_embedding') + 1.0",
                            "params": {"query_vector": query_embedding},
                        },
                    }
                },
            },
        )
    return response["hits"]["hits"]


def count_documents_with_image_embeddings() -> int:
    try:
        return int(
            es.options(request_timeout=10).count(
                index=INDEX_NAME,
                query={"exists": {"field": "image_embedding"}},
            )["count"]
        )
    except Exception:
        return 0


def get_query_image_embedding(base64_image: str) -> list[float]:
    from services.embedding_service import get_image_embedding_from_base64

    return get_image_embedding_from_base64(base64_image)


def normalize_similarity_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = [hit.get("_source", {}) for hit in hits]
    if not records:
        return []

    if records and "ship_name" in records[0]:
        matches = normalize_flattened_ships(records)
    else:
        matches = [
            normalize_class(record, index)
            for index, record in enumerate(records, start=1)
        ]

    scores: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for hit in hits:
        record = hit.get("_source", {})
        key = class_key(record)
        score = float(hit.get("_score") or 0)
        current = scores.get(key)
        if current is None or score > current["score"]:
            scores[key] = {
                "score": score,
                "ship_name": record.get("ship_name") or "",
            }

    for match in matches:
        score_data = scores.get(class_key(match), {"score": 0, "ship_name": ""})
        match["match_score"] = round(score_data["score"], 4)
        match["matched_ship"] = score_data["ship_name"]

    return sorted(matches, key=lambda item: item.get("match_score", 0), reverse=True)


def class_key(record: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        record.get("country") or "Unknown",
        record.get("section") or "Unknown",
        record.get("class_name") or "Unknown Class",
        record.get("type") or "Unknown",
    )


def build_facets(classes: list[dict[str, Any]]) -> dict[str, list[Any]]:
    return {
        "countries": sorted({item["country"] for item in classes}),
        "sections": sorted({item["section"] for item in classes}),
        "types": sorted({item["type"] for item in classes}),
        "builders": sorted(
            {item["builder"] for item in classes if item.get("builder")}
        ),
        "speeds": sorted(
            {item["speed_knots"] for item in classes if item.get("speed_knots")},
        ),
    }


def empty_facets() -> dict[str, list[Any]]:
    return {
        "countries": [],
        "sections": [],
        "types": [],
        "builders": [],
        "speeds": [],
    }


def build_elastic_facets(search_request: dict[str, Any]) -> dict[str, list[Any]]:
    facets = empty_facets()
    aggregations = {
        "countries": {"terms": {"field": "country", "size": 1000}},
        "sections": {"terms": {"field": "section", "size": 1000}},
        "types": {"terms": {"field": "type", "size": 1000}},
        "builders": {"terms": {"field": "builder.keyword", "size": 1000}},
    }

    for facet_key, request_key in (
        ("countries", "country"),
        ("sections", "section"),
        ("types", "type"),
        ("builders", "builder"),
    ):
        scoped_request = dict(search_request)
        scoped_request[request_key] = ""
        try:
            response = es.search(
                index=INDEX_NAME,
                body={
                    "size": 0,
                    "query": build_elastic_query(scoped_request),
                    "aggs": {facet_key: aggregations[facet_key]},
                },
            )
            facets[facet_key] = sorted(
                bucket["key"]
                for bucket in response.get("aggregations", {})
                .get(facet_key, {})
                .get("buckets", [])
                if bucket.get("key")
            )
        except Exception:
            facets[facet_key] = []

    return facets


def normalize_merged_output(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    used_slugs: set[str] = set()

    for record in records:
        data = record.get("data") or {}
        country = data.get("country", "Unknown")
        section = data.get("section", "Unknown")
        source_image = record.get("source_image", "")

        for item in data.get("classes", []):
            ship_class = normalize_class(
                item,
                len(normalized) + 1,
                country=country,
                section=section,
                source_image=source_image,
            )
            ship_class["slug"] = unique_slug(ship_class["slug"], used_slugs)
            used_slugs.add(ship_class["slug"])
            normalized.append(ship_class)

    return normalized


def normalize_flattened_ships(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    for record in records:
        key = (
            record.get("country") or "Unknown",
            record.get("section") or "Unknown",
            record.get("class_name") or "Unknown Class",
            record.get("type") or "Unknown",
        )

        if key not in grouped:
            specifications = record.get("specifications") or {}
            image = record.get("ship_image_base64") or record.get("ship_image") or ""
            grouped[key] = {
                "slug": record.get("slug") or "",
                "class_name": key[2],
                "country": key[0],
                "section": key[1],
                "type": key[3],
                "description": record.get("description") or "No description available.",
                "builder": record.get("builder") or "Unknown",
                "speed_knots": parse_speed(specifications.get("Speed, knots")),
                "range": specifications.get("Range, n miles") or "Unknown",
                "displacement": specifications.get("Displacement") or "Unknown",
                "length": specifications.get("Dimensions") or "Unknown",
                "beam": "See dimensions",
                "draft": "See dimensions",
                "crew": specifications.get("Complement") or "Unknown",
                "commissioned": record.get("commissioned") or "Unknown",
                "ships": [],
                "images": normalize_images([image] if image else []),
                "specifications": specifications,
            }

        ship_class = grouped[key]
        image = record.get("ship_image_base64") or record.get("ship_image") or ""
        if image and not ship_class["images"]:
            ship_class["images"] = normalize_images([image])

        if ship_class["builder"] == "Unknown" and record.get("builder"):
            ship_class["builder"] = record["builder"]
        if ship_class["commissioned"] == "Unknown" and record.get("commissioned"):
            ship_class["commissioned"] = record["commissioned"]

        ship_class["ships"].append(
            normalize_ship(
                {
                    "name": record.get("ship_name"),
                    "number": record.get("ship_number"),
                    "builder": record.get("builder"),
                    "ordered": record.get("ordered"),
                    "launched": record.get("launched"),
                    "commissioned": record.get("commissioned"),
                    "status": record.get("status"),
                }
            )
        )

    normalized: list[dict[str, Any]] = []
    used_slugs: set[str] = set()

    for index, ship_class in enumerate(grouped.values(), start=1):
        slug_base = slugify(
            f"{ship_class['country']} {ship_class['section']} {ship_class['class_name']}"
        ) or f"class-{index}"
        ship_class["slug"] = ship_class.get("slug") or unique_slug(slug_base, used_slugs)
        used_slugs.add(ship_class["slug"])
        normalized.append(ship_class)

    return normalized


def normalize_class(
    item: dict[str, Any],
    index: int,
    country: str | None = None,
    section: str | None = None,
    source_image: str = "",
) -> dict[str, Any]:
    specifications = item.get("specifications") or {}
    ships = [normalize_ship(ship) for ship in item.get("ships", [])]
    builder = item.get("builder") or first_value(ship.get("builder") for ship in ships)
    speed = parse_speed(item.get("speed_knots") or specifications.get("Speed, knots"))
    images = normalize_images(item.get("images", []), source_image)
    class_name = item.get("class_name") or f"Class {index}"

    return {
        "slug": slugify(class_name) or f"class-{index}",
        "class_name": class_name,
        "country": country or item.get("country") or "Unknown",
        "section": section or item.get("section") or "Unknown",
        "type": item.get("type") or "Unknown",
        "builder": builder or "Unknown",
        "speed_knots": speed,
        "range": item.get("range") or specifications.get("Range, n miles") or "Unknown",
        "displacement": item.get("displacement") or specifications.get("Displacement") or "Unknown",
        "length": item.get("length") or specifications.get("Dimensions") or "Unknown",
        "beam": item.get("beam") or "See dimensions",
        "draft": item.get("draft") or "See dimensions",
        "crew": item.get("crew") or specifications.get("Complement") or "Unknown",
        "commissioned": item.get("commissioned") or first_value(ship.get("commissioned") for ship in ships) or "Unknown",
        "description": item.get("description") or "No description available.",
        "ships": ships,
        "images": images,
        "specifications": specifications,
    }


def normalize_ship(ship: dict[str, Any]) -> dict[str, str]:
    return {
        "name": ship.get("name") or "Unknown",
        "pennant": ship.get("pennant") or ship.get("number") or "",
        "status": ship.get("status") or "Unknown",
        "builder": ship.get("builder") or "",
        "ordered": ship.get("ordered") or "",
        "launched": ship.get("launched") or "",
        "commissioned": ship.get("commissioned") or "",
    }


def normalize_images(images: list[Any], source_image: str = "") -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []

    for image in images:
        if isinstance(image, str):
            url = normalize_image_url(image)
            if url:
                normalized.append({"url": url, "alt": "Ship class image"})
        elif isinstance(image, dict):
            url = image.get("url") or image.get("path") or image.get("src")
            url = normalize_image_url(url or "")
            if url:
                normalized.append({"url": url, "alt": image.get("alt") or "Ship class image"})

    if not normalized and is_web_image_path(source_image):
        normalized.append({"url": source_image, "alt": "Source page image"})

    return normalized


def parse_speed(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else 0


def first_value(values: Any) -> str:
    for value in values:
        if value:
            return str(value)
    return ""


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug


def unique_slug(slug: str, used_slugs: set[str]) -> str:
    if slug not in used_slugs:
        return slug

    counter = 2
    while f"{slug}-{counter}" in used_slugs:
        counter += 1
    return f"{slug}-{counter}"


def is_web_image_path(value: str) -> bool:
    return value.startswith(("http://", "https://", "/static/", "data:image/"))


def normalize_image_url(value: str) -> str:
    if is_web_image_path(value):
        return value

    if looks_like_base64_image(value):
        return f"data:image/jpeg;base64,{value}"

    clean_value = value.replace("\\", "/").lstrip("/")
    static_path = BASE_DIR / "static" / clean_value
    if clean_value and static_path.exists():
        return f"/static/{clean_value}"

    return ""


def looks_like_base64_image(value: str) -> bool:
    value = str(value or "").strip()
    if len(value) < 80 or re.search(r"[^A-Za-z0-9+/=]", value):
        return False
    return value.startswith(("/9j/", "iVBOR", "UklGR"))


def is_allowed_image(filename: str) -> bool:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return suffix in ALLOWED_IMAGE_EXTENSIONS


def build_chat_reply(message: str) -> str:
    text = message.lower()

    if any(word in text for word in ("fastest", "speed", "quickest")):
        try:
            response = es.search(
                index=INDEX_NAME,
                body={
                    "size": 1,
                    "query": build_elastic_query(empty_search_request() | {"query": message}),
                    "sort": [{"speed_knots": "desc"}],
                    "collapse": {"field": "class_key"},
                },
            )
            classes = normalize_collapsed_hits(response.get("hits", {}).get("hits", []))
        except Exception:
            classes = []
        if classes:
            fastest = classes[0]
            return (
                f"The fastest class in Elasticsearch is {fastest['class_name']} "
                f"at {fastest['speed_knots']} knots."
            )

    search_request = empty_search_request()
    search_request.update({"query": message, "page_size": 5})
    result = search_ship_classes(search_request)
    matches = result["items"]

    if matches:
        names = ", ".join(
            f"{item['class_name']} ({item['country']}, {item['type']})"
            for item in matches[:5]
        )
        extra = "" if result["total"] <= 5 else f" and about {result['total'] - 5} more"
        return f"I found {result['total']} matching class record(s) in Elasticsearch: {names}{extra}."

    if "help" in text or "what can" in text:
        return (
            "You can ask about class names, ship names, countries, ship types, "
            "builders, or speeds. Example: show Algeria frigates."
        )

    return (
        "I could not find a matching ship class. Try asking by "
        "country, class name, ship name, type, builder, sensors, weapons, or speed."
    )


def text_matches_class(text: str, ship_class: dict[str, Any]) -> bool:
    fields = [
        ship_class.get("class_name", ""),
        ship_class.get("country", ""),
        ship_class.get("section", ""),
        ship_class.get("type", ""),
        ship_class.get("builder", ""),
        str(ship_class.get("speed_knots", "")),
    ]
    fields.extend(ship.get("name", "") for ship in ship_class.get("ships", []))
    haystack = " ".join(fields).lower()
    terms = [term for term in text.split() if len(term) > 2]
    return any(term in haystack for term in terms)


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)


# if __name__ == "__main__":
#     app.run(
#         host="0.0.0.0",
#         port=5000,
#         debug=True,
#         use_reloader=False
#     )
