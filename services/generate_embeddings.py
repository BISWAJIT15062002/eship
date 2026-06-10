# scripts/generate_embeddings.py

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from services.embedding_service import (
    get_image_embedding_from_base64
)

INPUT_FILE = BASE_DIR / "data" / "flattened_ships_with_base64.json"
OUTPUT_FILE = BASE_DIR / "data" / "flattened_ships_with_embeddings.json"


def generate_embeddings():

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        ships = json.load(f)

    total = len(ships)

    for index, ship in enumerate(ships, start=1):

        try:

            base64_image = (
                ship.get("ship_image_base64")
                or ship.get("image_base64")
                or ship.get("ship_image")
            )

            if base64_image:

                embedding = get_image_embedding_from_base64(
                    base64_image
                )

                ship["image_embedding"] = embedding

            else:

                ship["image_embedding"] = None

            print(
                f"[{index}/{total}] Processed: "
                f"{ship.get('ship_name', 'Unknown')}"
            )

        except Exception as e:

            print(
                f"Error processing "
                f"{ship.get('ship_name')}: {e}"
            )

            ship["image_embedding"] = None

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            ships,
            f,
            ensure_ascii=False
        )

    print("\nEmbeddings generated successfully.")


if __name__ == "__main__":
    generate_embeddings()
